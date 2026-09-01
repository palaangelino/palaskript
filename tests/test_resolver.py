"""Girdi cozumleme.

Kullanici tek kutuya link ve dosya yolu karisik yapistiriyor. Burasi hangisinin
ne oldugunu ayirip tekrarlari eleyen yer. Onemli davranis: bir girdinin bozuk
olmasi digerlerinin eklenmesini engellememeli.
"""

from __future__ import annotations

import numpy as np
import pytest
from helpers import speech_like

from transkript.source import file_source, resolver


class TestParseInputLines:
    def test_splits_on_newlines(self):
        text = "https://a.com/1\nhttps://a.com/2\n\nC:\\video.mp4"
        assert resolver.parse_input_lines(text) == [
            "https://a.com/1",
            "https://a.com/2",
            "C:\\video.mp4",
        ]

    def test_keeps_paths_with_spaces_intact(self):
        """Bosluga gore bolmuyoruz: dosya yollarinda bosluk olabiliyor."""
        assert resolver.parse_input_lines("C:\\Belgeler\\benim videom.mp4") == [
            "C:\\Belgeler\\benim videom.mp4"
        ]

    def test_strips_surrounding_quotes(self):
        # Windows'ta "yol olarak kopyala" tirnak ekliyor.
        assert resolver.parse_input_lines('"C:\\a b\\video.mp4"') == ["C:\\a b\\video.mp4"]

    def test_handles_crlf(self):
        assert len(resolver.parse_input_lines("a\r\nb\r\n")) == 2

    def test_empty_input(self):
        assert resolver.parse_input_lines("   \n\n  ") == []


class TestIsUrl:
    @pytest.mark.parametrize(
        "text",
        [
            "https://www.youtube.com/watch?v=abc",
            "http://example.com",
            "www.youtube.com/watch?v=abc",
        ],
    )
    def test_recognises_urls(self, text: str):
        assert resolver.is_url(text)

    @pytest.mark.parametrize("text", ["C:\\video.mp4", "/home/a/video.mp4", "video.mp4"])
    def test_rejects_paths(self, text: str):
        assert not resolver.is_url(text)


class TestFileResolution:
    def test_resolves_a_media_file(self, tmp_path, rng, make_wav):
        path = make_wav(speech_like(3, rng), "konusma.wav")
        results = resolver.resolve_one(str(path))
        assert len(results) == 1
        assert results[0].kind == "file"
        assert results[0].title == "konusma"
        assert results[0].duration == pytest.approx(3.0, abs=0.2)

    def test_missing_path_raises_resolve_error(self, tmp_path):
        with pytest.raises(resolver.ResolveError):
            resolver.resolve_one(str(tmp_path / "yok.mp4"))

    def test_directory_expands_to_media_files(self, tmp_path, rng, make_wav):
        make_wav(speech_like(2, rng), "bir.wav")
        make_wav(speech_like(2, rng), "iki.wav")
        (tmp_path / "notlar.txt").write_text("medya degil", encoding="utf-8")

        results = resolver.resolve_one(str(tmp_path))
        assert len(results) == 2
        assert {r.title for r in results} == {"bir", "iki"}

    def test_empty_directory_raises(self, tmp_path):
        (tmp_path / "notlar.txt").write_text("medya degil", encoding="utf-8")
        with pytest.raises(resolver.ResolveError):
            resolver.resolve_one(str(tmp_path))

    def test_blank_input_returns_nothing(self):
        assert resolver.resolve_one("   ") == []

    def test_corrupt_media_file_raises_readable_error(self, tmp_path):
        broken = tmp_path / "bozuk.mp4"
        broken.write_bytes(b"bu bir video degil")
        with pytest.raises(ValueError) as excinfo:
            file_source.probe(broken)
        assert "ses" in str(excinfo.value).lower()


class TestSourceId:
    def test_is_case_insensitive_on_windows_paths(self, tmp_path):
        """Ayni dosya iki farkli yazimla iki kez kuyruga girmemeli."""
        lower = file_source.source_id_for(tmp_path / "Video.MP4")
        upper = file_source.source_id_for(tmp_path / "VIDEO.mp4")
        assert lower == upper

    def test_differs_between_files(self, tmp_path):
        assert file_source.source_id_for(tmp_path / "a.mp4") != file_source.source_id_for(
            tmp_path / "b.mp4"
        )


class TestResolveMany:
    def test_one_bad_input_does_not_block_the_others(self, tmp_path, rng, make_wav):
        """Yirmi link yapistirildiginda on dokuzu calisiyorsa on dokuzu girsin."""
        good = make_wav(speech_like(2, rng), "iyi.wav")
        resolved, errors = resolver.resolve_many([str(good), str(tmp_path / "yok.mp4")])
        assert len(resolved) == 1
        assert len(errors) == 1
        assert "yok.mp4" in errors[0].raw

    def test_deduplicates_within_one_batch(self, tmp_path, rng, make_wav):
        path = make_wav(speech_like(2, rng), "ayni.wav")
        resolved, _ = resolver.resolve_many([str(path), str(path)])
        assert len(resolved) == 1

    def test_skips_ids_already_in_the_queue(self, tmp_path, rng, make_wav):
        path = make_wav(speech_like(2, rng), "kuyrukta.wav")
        known = {file_source.source_id_for(path)}
        resolved, errors = resolver.resolve_many([str(path)], known_ids=known)
        assert resolved == []
        assert errors == []

    def test_empty_batch(self):
        assert resolver.resolve_many([]) == ([], [])


class TestMediaSuffixes:
    def test_accepts_common_video_and_audio(self):
        from pathlib import Path

        for name in ("a.mp4", "a.mkv", "a.webm", "a.mp3", "a.m4a", "a.opus"):
            assert file_source.is_media_file(Path(name))

    def test_rejects_documents(self):
        from pathlib import Path

        for name in ("a.txt", "a.pdf", "a.docx"):
            assert not file_source.is_media_file(Path(name))

    def test_is_case_insensitive(self):
        from pathlib import Path

        assert file_source.is_media_file(Path("VIDEO.MP4"))


def test_numpy_is_available_for_helpers():
    # helpers.speech_like numpy'a bagli; import zinciri kirilirsa erken yakala.
    assert isinstance(speech_like(0.1, np.random.default_rng(0)), np.ndarray)
