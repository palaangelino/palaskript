"""Bu makinede olculen bellek ve hiz degerleri.

Fikir: kurulum sirasinda ayri bir olcum kosturmak yerine, ZATEN YAPILAN isten
olcumu almak. Ilk is bittiginde gercek tepe bellek elde oluyor ve sonraki
isler tahmin yerine bu degerle boyutlaniyor.
"""

from __future__ import annotations

import pytest

from transkript import calibration
from transkript.resources import MODEL_CATALOG, HardwareInfo, choose_profile, effective_ram_gb


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    yield


def hw(total: float) -> HardwareInfo:
    return HardwareInfo(
        total_ram_gb=total,
        available_ram_gb=total * 0.6,
        physical_cores=4,
        logical_cores=8,
        free_disk_gb=100.0,
    )


class TestRecording:
    def test_records_and_reads_back(self):
        result = calibration.record(
            model="large-v3-turbo",
            batch_size=8,
            peak_rss_gb=3.4,
            audio_seconds=849.0,
            elapsed_seconds=678.0,
        )
        assert result is not None
        found = calibration.lookup("large-v3-turbo", 8)
        assert found is not None
        assert found.peak_rss_gb == 3.4
        assert found.realtime_factor == pytest.approx(849 / 678, rel=1e-3)

    def test_ignores_jobs_that_are_too_short(self):
        """Kisa iste model yukleme maliyeti hiza karisiyor, olcum yaniltici olur."""
        assert (
            calibration.record(
                model="small",
                batch_size=4,
                peak_rss_gb=1.0,
                audio_seconds=30.0,
                elapsed_seconds=20.0,
            )
            is None
        )
        assert calibration.lookup("small", 4) is None

    def test_ignores_unmeasured_memory(self):
        assert (
            calibration.record(
                model="small",
                batch_size=4,
                peak_rss_gb=0.0,
                audio_seconds=600.0,
                elapsed_seconds=300.0,
            )
            is None
        )

    def test_keeps_the_worst_case_memory(self):
        """Bellekte en kotu durum tutulmali: guvenli taraf bu."""
        calibration.record(
            model="medium", batch_size=4, peak_rss_gb=2.0,
            audio_seconds=600.0, elapsed_seconds=300.0,
        )
        calibration.record(
            model="medium", batch_size=4, peak_rss_gb=3.1,
            audio_seconds=600.0, elapsed_seconds=280.0,
        )
        calibration.record(
            model="medium", batch_size=4, peak_rss_gb=1.4,
            audio_seconds=600.0, elapsed_seconds=290.0,
        )
        assert calibration.lookup("medium", 4).peak_rss_gb == 3.1

    def test_speed_uses_the_latest_measurement(self):
        calibration.record(
            model="medium", batch_size=4, peak_rss_gb=2.0,
            audio_seconds=600.0, elapsed_seconds=600.0,
        )
        calibration.record(
            model="medium", batch_size=4, peak_rss_gb=2.0,
            audio_seconds=600.0, elapsed_seconds=300.0,
        )
        assert calibration.lookup("medium", 4).realtime_factor == pytest.approx(2.0)

    def test_measurements_are_per_batch_size(self):
        calibration.record(
            model="medium", batch_size=1, peak_rss_gb=1.2,
            audio_seconds=600.0, elapsed_seconds=600.0,
        )
        calibration.record(
            model="medium", batch_size=8, peak_rss_gb=3.6,
            audio_seconds=600.0, elapsed_seconds=300.0,
        )
        assert calibration.lookup("medium", 1).peak_rss_gb == 1.2
        assert calibration.lookup("medium", 8).peak_rss_gb == 3.6


class TestEffectiveRam:
    def test_falls_back_to_the_catalog_estimate(self):
        assert effective_ram_gb("large-v3-turbo", 4) == pytest.approx(
            MODEL_CATALOG["large-v3-turbo"].ram_estimate_gb(4)
        )

    def test_measurement_wins_over_the_estimate(self):
        calibration.record(
            model="large-v3-turbo", batch_size=4, peak_rss_gb=3.9,
            audio_seconds=600.0, elapsed_seconds=400.0,
        )
        assert effective_ram_gb("large-v3-turbo", 4) == 3.9


class TestProfileUsesMeasurements:
    def test_batch_shrinks_when_the_model_turns_out_heavier(self):
        """Kalibrasyonun asil isi bu.

        Katalog turbo icin yigin 8'de ~2.4 GB tahmin ediyor. Gercekte 5 GB
        cikarsa 16 GB'lik bir makinede bile yigin kucultulmeli.
        """
        machine = hw(15.8)
        before = choose_profile(machine)
        assert before.batch_size == 8

        calibration.record(
            model="large-v3-turbo", batch_size=8, peak_rss_gb=9.0,
            audio_seconds=600.0, elapsed_seconds=400.0,
        )
        after = choose_profile(machine)
        assert after.batch_size < 8

    def test_profile_is_unchanged_when_measurement_matches_estimate(self):
        machine = hw(15.8)
        calibration.record(
            model="large-v3-turbo", batch_size=8, peak_rss_gb=2.4,
            audio_seconds=600.0, elapsed_seconds=400.0,
        )
        assert choose_profile(machine).batch_size == 8


class TestDescribe:
    def test_says_estimate_when_unmeasured(self):
        assert calibration.describe("small", 4) == "tahmin"

    def test_reports_the_measurement(self):
        calibration.record(
            model="small", batch_size=4, peak_rss_gb=1.1,
            audio_seconds=600.0, elapsed_seconds=200.0,
        )
        text = calibration.describe("small", 4)
        assert "ölçüldü" in text
        assert "1.1 GB" in text
        assert "3.00x" in text


class TestStorage:
    def test_corrupt_file_is_ignored(self):
        calibration.calibration_file().parent.mkdir(parents=True, exist_ok=True)
        calibration.calibration_file().write_text("bu json degil", encoding="utf-8")
        assert calibration.load() == {}

    def test_old_schema_is_ignored(self):
        calibration.calibration_file().parent.mkdir(parents=True, exist_ok=True)
        calibration.calibration_file().write_text(
            '{"version": 0, "measurements": {"x": {}}}', encoding="utf-8"
        )
        assert calibration.load() == {}

    def test_clear_removes_everything(self):
        calibration.record(
            model="small", batch_size=4, peak_rss_gb=1.0,
            audio_seconds=600.0, elapsed_seconds=300.0,
        )
        calibration.clear()
        assert calibration.load() == {}

    def test_clear_is_safe_when_missing(self):
        calibration.clear()
