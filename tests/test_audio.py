"""Pencereli ses akisi.

Buradaki iki davranis 8 GB hedefi ve metin kalitesi icin belirleyici:

1. Tepe bellek video uzunlugundan bagimsiz olmali (pencere boyu sabit kalmali).
2. Pencere siniri kelimeyi ortadan bolmemeli: once sessizlik araniyor,
   bulunamazsa bindirme uygulanip dikis segments katmaninda temizleniyor.
"""

from __future__ import annotations

import numpy as np
import pytest
from helpers import silence, speech_like

from palaskript.audio import (
    SAMPLE_RATE,
    AudioDecodeError,
    find_silence_cut,
    iter_windows,
    probe_duration,
)


class TestFindSilenceCut:
    def test_finds_the_gap(self, rng):
        # 10 sn konusma, 1 sn sessizlik, 10 sn konusma
        samples = np.concatenate([speech_like(10, rng), silence(1.0), speech_like(10, rng)])
        target = int(10.5 * SAMPLE_RATE)
        cut = find_silence_cut(samples, target, int(15 * SAMPLE_RATE))
        assert cut is not None
        # Kesim sessizligin icine dusmeli (10.0 - 11.0 sn araligi)
        assert 10.0 * SAMPLE_RATE <= cut <= 11.0 * SAMPLE_RATE

    def test_returns_none_in_continuous_speech(self, rng):
        samples = speech_like(25, rng)
        assert find_silence_cut(samples, int(10 * SAMPLE_RATE), int(5 * SAMPLE_RATE)) is None

    def test_ignores_silence_outside_the_search_window(self, rng):
        # Sessizlik 1. saniyede ama hedef 20. saniye ve slack 2 saniye:
        # arama penceresine girmiyor.
        samples = np.concatenate([speech_like(1, rng), silence(1.0), speech_like(25, rng)])
        cut = find_silence_cut(samples, int(20 * SAMPLE_RATE), int(2 * SAMPLE_RATE))
        assert cut is None

    def test_picks_longest_silence(self, rng):
        samples = np.concatenate(
            [speech_like(5, rng), silence(0.4), speech_like(2, rng), silence(2.0), speech_like(5, rng)]
        )
        cut = find_silence_cut(samples, int(8 * SAMPLE_RATE), int(4 * SAMPLE_RATE))
        assert cut is not None
        # Uzun olan (7.4 - 9.4 sn) tercih edilmeli
        assert 7.4 * SAMPLE_RATE <= cut <= 9.4 * SAMPLE_RATE

    def test_rejects_too_short_silence(self, rng):
        # 100 ms'lik bir soluk kesim noktasi sayilmamali (esik 300 ms).
        samples = np.concatenate([speech_like(10, rng), silence(0.1), speech_like(10, rng)])
        cut = find_silence_cut(samples, int(10 * SAMPLE_RATE), int(1 * SAMPLE_RATE))
        assert cut is None

    def test_adapts_to_recording_level(self, rng):
        """Esik mutlak degil: kisik kayitta da sessizlik bulunmali."""
        quiet = np.concatenate(
            [
                speech_like(10, rng, amplitude=0.02),
                silence(1.0),
                speech_like(10, rng, amplitude=0.02),
            ]
        )
        cut = find_silence_cut(quiet, int(10.5 * SAMPLE_RATE), int(15 * SAMPLE_RATE))
        assert cut is not None

    def test_handles_too_short_input(self):
        assert find_silence_cut(np.zeros(10, dtype=np.float32), 5, 2) is None


class TestIterWindows:
    def test_covers_whole_file_without_gaps(self, rng, make_wav):
        samples = np.concatenate(
            [speech_like(10, rng), silence(1.0), speech_like(10, rng), silence(1.0), speech_like(10, rng)]
        )
        path = make_wav(samples)
        windows = list(iter_windows(path, window_seconds=10))

        assert windows
        assert windows[0].start == pytest.approx(0.0, abs=0.05)
        assert windows[-1].end == pytest.approx(32.0, abs=0.2)
        for previous, current in zip(windows, windows[1:], strict=False):
            # Bosluk olmamali: her pencere oncekinin bittigi yerde ya da geride baslar.
            assert current.start <= previous.end + 0.01
            assert current.start >= previous.start

    def test_window_size_is_bounded(self, rng, make_wav):
        """Tepe bellegi sinirlayan sey bu: pencereler video uzadikca buyumuyor."""
        path = make_wav(speech_like(70, rng))
        windows = list(iter_windows(path, window_seconds=10))
        limit = 10 + 15 + 1  # pencere + slack + tolerans
        assert all(window.duration <= limit for window in windows)

    def test_longer_file_does_not_grow_windows(self, rng, make_wav):
        short = list(iter_windows(make_wav(speech_like(40, rng), "a.wav"), window_seconds=10))
        long = list(iter_windows(make_wav(speech_like(120, rng), "b.wav"), window_seconds=10))
        assert max(w.duration for w in long) <= max(w.duration for w in short) + 1.0

    def test_silence_aligned_windows_are_not_marked_overlapped(self, rng, make_wav):
        samples = np.concatenate(
            [speech_like(10, rng), silence(1.5), speech_like(10, rng), silence(1.5), speech_like(10, rng)]
        )
        path = make_wav(samples)
        windows = list(iter_windows(path, window_seconds=10))
        assert not windows[0].overlapped
        # Sessizlikler bol; en az bir temiz kesim olmali.
        assert any(not w.overlapped for w in windows[1:]) or len(windows) == 1

    def test_continuous_speech_falls_back_to_overlap(self, rng, make_wav):
        """Sessizlik yoksa kelimeyi bolmemek icin bindirme uygulanmali."""
        path = make_wav(speech_like(60, rng))
        windows = list(iter_windows(path, window_seconds=10))
        assert len(windows) > 1
        assert any(w.overlapped for w in windows[1:])
        # Bindirilen pencere geriden basliyor, yani onceki pencerenin sonunu asmiyor.
        for previous, current in zip(windows, windows[1:], strict=False):
            if current.overlapped:
                assert current.start < previous.end

    def test_alignment_can_be_disabled(self, rng, make_wav):
        path = make_wav(speech_like(45, rng))
        windows = list(iter_windows(path, window_seconds=10, align_to_silence=False))
        assert all(not w.overlapped for w in windows)

    def test_start_at_resumes_from_offset(self, rng, make_wav):
        """Ara kayittan devam: bastan cozmemeli."""
        path = make_wav(speech_like(60, rng))
        windows = list(iter_windows(path, window_seconds=10, start_at=30.0))
        assert windows[0].start == pytest.approx(30.0, abs=1.0)
        assert windows[-1].end == pytest.approx(60.0, abs=1.5)

    def test_samples_are_float32_mono_at_16k(self, rng, make_wav):
        path = make_wav(speech_like(30, rng))
        window = next(iter(iter_windows(path, window_seconds=10)))
        assert window.samples.dtype == np.float32
        assert window.samples.ndim == 1
        assert window.duration == pytest.approx(len(window.samples) / SAMPLE_RATE)

    def test_window_indices_are_sequential(self, rng, make_wav):
        path = make_wav(speech_like(70, rng))
        windows = list(iter_windows(path, window_seconds=10))
        assert [w.index for w in windows] == list(range(len(windows)))

    def test_short_file_yields_single_window(self, rng, make_wav):
        path = make_wav(speech_like(4, rng))
        windows = list(iter_windows(path, window_seconds=10))
        assert len(windows) == 1
        assert windows[0].duration == pytest.approx(4.0, abs=0.2)

    def test_rejects_non_positive_window(self, rng, make_wav):
        path = make_wav(speech_like(5, rng))
        with pytest.raises(ValueError):
            list(iter_windows(path, window_seconds=0))

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(AudioDecodeError):
            list(iter_windows(tmp_path / "yok.wav", window_seconds=10))


class TestProbeDuration:
    def test_reads_duration(self, rng, make_wav):
        path = make_wav(speech_like(12.5, rng))
        assert probe_duration(path) == pytest.approx(12.5, abs=0.1)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(AudioDecodeError):
            probe_duration(tmp_path / "yok.wav")
