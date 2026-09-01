"""Ilerlemenin iki gercek bildirim arasini doldurmasi.

Motor segmentleri yigin yigin uretiyor: bes dakikalik bir videoda topu topu
bir iki gercek bildirim geliyor ve cubuk %15 -> %37 -> %100 diye sicriyordu.
Burada test edilen, aradaki bosluğun hesapla doldurulmasi ve bunu yaparken
uc kuralin hic bozulmamasi.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from palaskript import stages  # noqa: E402
from palaskript.ui.progress import ProgressCell  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def running(cell: ProgressCell, percent: float, *, stage: str = "transcribe", eta: float | None = None):
    cell.set_state(percent=percent, stage=stage, eta_seconds=eta, running=True, finished=False)


class TestStages:
    def test_overall_maps_stage_local_fraction(self):
        assert stages.overall("transcribe", 0.0) == pytest.approx(0.22)
        assert stages.overall("transcribe", 1.0) == pytest.approx(0.95)

    def test_ceiling_never_reaches_one(self):
        assert stages.CEILING < 1.0
        assert stages.stage_ceiling("export") <= stages.CEILING

    def test_stage_ceiling_is_the_stage_end(self):
        assert stages.stage_ceiling("model") == pytest.approx(0.22)
        assert stages.stage_ceiling("transcribe") == pytest.approx(0.95)

    def test_unknown_stage_falls_back_to_ceiling(self):
        assert stages.stage_ceiling(None) == stages.CEILING


class TestRealValuesApplyImmediately:
    def test_first_value_is_shown_at_once(self, app):
        """Uygulama acildiginda yarim kalmis is sifirdan animasyon yapmamali."""
        cell = ProgressCell()
        running(cell, 40.0)
        assert cell.percent.text() == "40%"

    def test_higher_real_value_is_adopted(self, app):
        cell = ProgressCell()
        running(cell, 20.0)
        running(cell, 55.0)
        assert cell.percent.text() == "55%"


class TestNeverGoesBackwards:
    def test_lower_real_value_does_not_rewind(self, app):
        """Tahmin gercegin onune gectiyse cubuk geri sarmamali."""
        cell = ProgressCell()
        running(cell, 60.0)
        running(cell, 45.0)
        assert cell._shown >= 60.0

    def test_projection_never_lowers_the_bar(self, app):
        cell = ProgressCell()
        running(cell, 50.0, eta=100.0)
        before = cell._shown
        cell._tick()
        assert cell._shown >= before


class TestFillsTheGap:
    def test_advances_between_reports_when_eta_is_known(self, app):
        """Asil mesele: iki bildirim arasinda cubuk ilerlemeli."""
        cell = ProgressCell()
        running(cell, 30.0, eta=60.0)
        start = cell._shown

        # 20 saniye gecmis gibi yap
        cell._real_at -= 20.0
        cell._last_tick -= 20.0
        cell._tick()

        assert cell._shown > start, "bildirimler arasinda cubuk durdu"

    def test_advances_even_without_an_eta(self, app):
        """Model bellege yuklenirken hiz bilinmiyor ama hareket olmali."""
        cell = ProgressCell()
        running(cell, 15.0, stage="model", eta=None)
        start = cell._shown

        cell._real_at -= 20.0
        cell._last_tick -= 20.0
        cell._tick()

        assert cell._shown > start, "hiz bilinmezken cubuk hic ilerlemedi"

    def test_unknown_rate_never_reaches_the_stage_end(self, app):
        """Ne zaman bitecegini bilmiyorsak asamanin sonunu iddia edemeyiz."""
        cell = ProgressCell()
        running(cell, 15.0, stage="model", eta=None)

        # Cok uzun sure gecse bile
        cell._real_at -= 3600.0
        cell._last_tick -= 3600.0
        cell._tick()

        assert cell._shown < stages.stage_ceiling("model") * 100


class TestStageCeiling:
    def test_projection_stops_at_the_stage_boundary(self, app):
        """Yazma asamasindaki tahmin, belge yazma payina tasamaz."""
        cell = ProgressCell()
        running(cell, 90.0, stage="transcribe", eta=1.0)

        cell._real_at -= 600.0
        cell._last_tick -= 600.0
        cell._tick()

        assert cell._shown <= stages.stage_ceiling("transcribe") * 100 + 1e-6


class TestNeverClaimsDoneEarly:
    def test_running_job_never_shows_100(self, app):
        cell = ProgressCell()
        running(cell, 99.9, stage="export", eta=0.1)

        cell._real_at -= 600.0
        cell._last_tick -= 600.0
        cell._tick()

        assert cell._shown <= stages.CEILING * 100
        assert cell.percent.text() != "100%"

    def test_finished_job_shows_100(self, app):
        cell = ProgressCell()
        running(cell, 80.0)
        cell.set_state(percent=100.0, stage=None, eta_seconds=None, running=False, finished=True)
        assert cell.percent.text() == "100%"

    def test_finished_job_stops_animating(self, app):
        cell = ProgressCell()
        running(cell, 80.0, eta=30.0)
        cell.set_state(percent=100.0, stage=None, eta_seconds=None, running=False, finished=True)
        assert not cell._tick_timer.isActive()
        assert not cell.bar._timer.isActive()


class TestIdleRows:
    def test_pending_row_does_not_animate(self, app):
        cell = ProgressCell()
        cell.set_state(percent=0.0, stage=None, eta_seconds=None, running=False, finished=False)
        assert not cell._tick_timer.isActive()

    def test_failed_row_keeps_its_value(self, app):
        cell = ProgressCell()
        running(cell, 42.0)
        cell.set_state(percent=42.0, stage=None, eta_seconds=None, running=False, finished=False)
        assert cell.percent.text() == "42%"
        assert not cell._tick_timer.isActive()


class TestEtaCountdown:
    """Kalan sure de bildirimler arasinda sabit duruyordu.

    Boru hatti tahmini dakikalar arayla gonderiyor; arada saymamasi "sayac
    donmus" izlenimi veriyordu.
    """

    def _window(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
        from palaskript.ui.window import MainWindow

        window = MainWindow()
        window.orchestrator.stop(wait=True, timeout=5.0)
        window._timer.stop()
        return window

    def _job(self, window, eta):
        from palaskript.datatypes import SourceInfo

        job = window.db.add(
            SourceInfo(kind="file", source_id="file:a", title="Video", duration=600.0), "raw"
        )
        window.db.mark_running(job.id)
        window.db.update_progress(job.id, stage="transcribe", progress=0.4, eta_seconds=eta)
        return window.db.get(job.id)

    def test_counts_down_between_reports(self, app, tmp_path, monkeypatch):
        window = self._window(tmp_path, monkeypatch)
        try:
            job = self._job(window, 300.0)
            first = window._live_eta(job)
            assert first == pytest.approx(300.0, abs=1)

            # 40 saniye gecmis gibi yap: yeni bildirim gelmese de saymali
            reported, at = window._eta_anchors[job.id]
            window._eta_anchors[job.id] = (reported, at - 40.0)

            second = window._live_eta(job)
            assert second == pytest.approx(260.0, abs=2), "sayac ilerlemedi"
        finally:
            window.db.close()
            window.deleteLater()

    def test_new_report_resets_the_anchor(self, app, tmp_path, monkeypatch):
        window = self._window(tmp_path, monkeypatch)
        try:
            job = self._job(window, 300.0)
            window._live_eta(job)

            window.db.update_progress(job.id, stage="transcribe", progress=0.5, eta_seconds=120.0)
            refreshed = window.db.get(job.id)
            assert window._live_eta(refreshed) == pytest.approx(120.0, abs=1)
        finally:
            window.db.close()
            window.deleteLater()

    def test_says_about_to_finish_instead_of_stalling_at_zero(self, app, tmp_path, monkeypatch):
        window = self._window(tmp_path, monkeypatch)
        try:
            job = self._job(window, 300.0)
            window._live_eta(job)
            reported, at = window._eta_anchors[job.id]
            window._eta_anchors[job.id] = (reported, at - 400.0)

            assert window._eta_text(job) == "bitmek üzere"
        finally:
            window.db.close()
            window.deleteLater()

    def test_says_calculating_before_an_estimate_exists(self, app, tmp_path, monkeypatch):
        window = self._window(tmp_path, monkeypatch)
        try:
            job = self._job(window, None)
            assert window._eta_text(job) == "hesaplanıyor"
        finally:
            window.db.close()
            window.deleteLater()

    def test_finished_job_says_ready(self, app, tmp_path, monkeypatch):
        window = self._window(tmp_path, monkeypatch)
        try:
            job = self._job(window, 300.0)
            window.db.mark_done(job.id, pdf_path=None, txt_path=None, audio_path=None)
            assert window._eta_text(window.db.get(job.id)) == "Hazır"
        finally:
            window.db.close()
            window.deleteLater()
