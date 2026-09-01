"""Arayuz duman testi.

Arayuz kodunun buyuk kismi ancak calistirilinca patlayan turden: yanlis Qt
numaralandirmasi, tasinmis sinif adi, eksik sinyal. Bu testler pencereyi ve
diyaloglari gercekten kurup yikiyor, boylece o hatalar kurulum dosyasini
acan kullanici yerine burada cikiyor.

Ekran gerekmiyor: Qt "offscreen" platformunda calisiyor.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

# QApplication olusturulmadan ONCE ayarlanmali.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from palaskript.config import Settings  # noqa: E402
from palaskript.datatypes import SourceInfo  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Ayarlari, kuyrugu ve onbellegi gercek kullanici dizininden ayir."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    return tmp_path


class TestMainWindow:
    def test_constructs_and_closes(self, app, isolated_paths):
        from palaskript.ui.window import MainWindow

        window = MainWindow()
        try:
            assert window.windowTitle().startswith("Palaskript")
            # Bos kuyrukta tablo bos ama sutunlar kurulu olmali.
            assert window.table.columnCount() == 5
            assert window.table.rowCount() == 0
            # Bekleyen karar yokken uyari cubuklari gizli.
            assert not window.decision_bar.isVisible()
        finally:
            window.orchestrator.stop(wait=True, timeout=5.0)
            window.db.close()
            window.close()
            window.deleteLater()

    def test_refresh_renders_queued_jobs(self, app, isolated_paths):
        from palaskript.ui.window import MainWindow

        window = MainWindow()
        try:
            window.orchestrator.pause()
            window.db.add(
                SourceInfo(
                    kind="youtube",
                    source_id="youtube:abc",
                    title="Bir konusma",
                    duration=3600.0,
                    url="https://www.youtube.com/watch?v=abc",
                ),
                "https://www.youtube.com/watch?v=abc",
            )
            window.refresh()

            assert window.table.rowCount() == 1
            assert window.table.item(0, 0).text() == "Bir konusma"
            assert window.table.item(0, 1).text() == "01:00:00"
            assert window.table.item(0, 2).text() == "Bekliyor"
        finally:
            window.orchestrator.stop(wait=True, timeout=5.0)
            window.db.close()
            window.close()
            window.deleteLater()

    def test_decision_banner_appears_for_awaiting_jobs(self, app, isolated_paths):
        from palaskript.ui.window import MainWindow

        window = MainWindow()
        try:
            window.orchestrator.pause()
            job = window.db.add(
                SourceInfo(
                    kind="youtube",
                    source_id="youtube:xyz",
                    title="Altyazili video",
                    duration=1800.0,
                    url="https://www.youtube.com/watch?v=xyz",
                ),
                "raw",
            )
            window.db.mark_awaiting_decision(job.id, ["tr"])
            window.refresh()

            assert window.decision_bar.isVisibleTo(window)
            assert "Altyazili video" in window.decision_label.text()

            # Banner dugmesi kararı kaydedip isi tekrar siraya almali.
            window._decide_all(True)
            assert window.db.get(job.id).use_subtitles is True
            assert window.db.get(job.id).status == "pending"
        finally:
            window.orchestrator.stop(wait=True, timeout=5.0)
            window.db.close()
            window.close()
            window.deleteLater()


class TestDialogs:
    def test_add_dialog_parses_mixed_input(self, app, isolated_paths):
        from palaskript.source import resolver
        from palaskript.ui.add_dialog import AddDialog

        dialog = AddDialog(initial="https://a.com/1\nC:\\videolar\\a.mp4")
        try:
            lines = resolver.parse_input_lines(dialog.raw_text())
            assert lines == ["https://a.com/1", "C:\\videolar\\a.mp4"]
        finally:
            dialog.deleteLater()

    def test_settings_dialog_round_trips_values(self, app, isolated_paths):
        from palaskript.ui.settings_dialog import SettingsDialog

        settings = Settings()
        settings.language = "tr"
        settings.timestamp_mode = "paragraph"
        settings.low_memory_mode = True

        dialog = SettingsDialog(settings)
        try:
            result = dialog.result_settings()
            assert result.language == "tr"
            assert result.timestamp_mode == "paragraph"
            assert result.low_memory_mode is True
        finally:
            dialog.deleteLater()

    def test_settings_dialog_disables_models_that_do_not_fit(self, app, isolated_paths, monkeypatch):
        """8 GB'lik makinede large-v3 secilemez olmali."""
        from palaskript.resources import HardwareInfo
        from palaskript.ui import settings_dialog as module

        monkeypatch.setattr(
            module,
            "detect",
            lambda *a, **k: HardwareInfo(
                total_ram_gb=7.8,
                available_ram_gb=4.5,
                physical_cores=4,
                logical_cores=8,
                free_disk_gb=120.0,
            ),
        )
        dialog = module.SettingsDialog(Settings())
        try:
            index = dialog.model_combo.findData("large-v3")
            assert index >= 0
            item = dialog.model_combo.model().item(index)
            assert item is not None
            assert not item.isEnabled()
            assert "16 GB" in item.toolTip()
        finally:
            dialog.deleteLater()
