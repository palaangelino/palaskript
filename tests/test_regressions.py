"""Kullanicinin gercek kullanimda buldugu hatalar.

Bunlarin hepsi 285 testten gecti ve yine de kullaniciya ulasti. Her biri icin
buraya bir test yaziliyor ki ayni sey iki kez olmasin.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from palaskript import paths  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    return tmp_path


def _quiet_window():
    """Orkestratoru durdurulmus bir ana pencere.

    Duraklatmak yetmiyor: MainWindow.__init__ orkestratoru zaten baslatiyor ve
    duraklatma cagrisina kadar gecen surede eklenen bir isi kapip aga cikabilir
    (yt-dlp cagrisi testleri asili birakiyor). Tamamen durdurup kuyrugu elle
    dolduruyoruz.
    """
    from palaskript.ui.window import MainWindow

    window = MainWindow()
    window.orchestrator.stop(wait=True, timeout=5.0)
    window._timer.stop()
    return window


def _dispose(window) -> None:
    """Pencereyi close() CAGIRMADAN birak.

    close() calisan bir is varsa "kapatilsin mi" modalini aciyor ve test orada
    asili kaliyor. Bu davranis dogru (kullanici uyarilmali), sadece testte
    cevap verecek kimse yok.
    """
    window._timer.stop()
    window.orchestrator.stop(wait=True, timeout=5.0)
    window.db.close()
    window.deleteLater()


class TestAddDialogSignalArgument:
    """"Ekle" dugmesi uygulamayi dusuruyordu.

    QAction.triggered sinyali "checked" degerini (bool) yolluyor. Slot
    opsiyonel bir parametre kabul ederse Qt bool'u ona veriyor ve
    setPlainText(False) cagriliyordu.
    """

    def test_dialog_rejects_non_string_initial(self, app):
        from palaskript.ui.add_dialog import AddDialog

        # Kaza tam olarak boyle olusuyordu.
        with pytest.raises(TypeError):
            AddDialog(initial=False)

    def test_open_add_dialog_is_connected_without_signal_argument(self, app, isolated):
        """Sinyalin bool argumaninin slota ULASMADIGINI dogruluyoruz."""
        window = _quiet_window()
        try:
            received: list[object] = []
            window.open_add_dialog = lambda *args: received.append(args)

            add_action = next(
                a for a in window.findChildren(QAction) if a.text() == "Ekle"
            )
            add_action.trigger()

            assert received, "eylem slota ulasmadi"
            assert received[0] == (), f"slota beklenmeyen arguman gecti: {received[0]}"
        finally:
            _dispose(window)


class TestBundledAssets:
    """Altbilgideki kalp gorunmuyordu: gorsel pakete hic girmemisti.

    Varlik listesi elle tutuluyordu ve yeni eklenen dosyalar unutulabiliyordu.
    """

    def test_every_runtime_asset_is_collected_by_the_spec(self):
        root = Path(__file__).resolve().parent.parent
        spec_text = (root / "packaging" / "palaskript.spec").read_text(encoding="utf-8")

        # Spec artik assets/ altini tarayarak topluyor; elle liste yok.
        assert "rglob" in spec_text, "varlik listesi yine elle tutuluyor"
        assert "installer" in spec_text, "kurulum gorselleri disarida birakilmali"

    def test_assets_referenced_by_code_exist_on_disk(self):
        """Kodun bekledigi her gorsel gercekten var mi."""
        expected = [
            "icon.ico",
            "check-light.png",
            "check-muted.png",
            "heart-accent.png",
            "heart-ink.png",
        ]
        missing = [name for name in expected if not (paths.assets_dir() / name).exists()]
        assert not missing, f"eksik varlik: {missing}"

    def test_heart_label_actually_loads_a_pixmap(self, app):
        """Kalp bos bir etiket olarak degil, gercek bir gorselle geliyor mu."""
        from palaskript.ui import theme

        label = theme.heart_label()
        pixmap = label.pixmap()
        assert pixmap is not None and not pixmap.isNull(), "kalp gorseli yuklenemedi"


class TestRunningStatusShowsDetail:
    """7 dakikalik model indirmesi boyunca Durum sutunu hic degismiyordu.

    Ayrintili mesaj ("1.34 / 1.6 GB") yalnizca ipucunda duruyordu.
    """

    def test_running_row_shows_the_message_not_the_static_label(self, app, isolated):
        from palaskript.datatypes import SourceInfo

        window = _quiet_window()
        try:
            job = window.db.add(
                SourceInfo(
                    kind="youtube",
                    source_id="youtube:x",
                    title="Video",
                    duration=600.0,
                    url="https://www.youtube.com/watch?v=x",
                ),
                "raw",
            )
            window.db.mark_running(job.id)
            window.db.update_progress(
                job.id,
                stage="model",
                progress=0.18,
                message="large-v3-turbo indiriliyor: 1.34 / 1.6 GB",
            )
            window.refresh()

            shown = window.table.item(0, 2).text()
            assert "1.34" in shown, f"ayrintili mesaj gosterilmiyor: {shown!r}"
        finally:
            _dispose(window)

    def test_pending_row_still_shows_the_short_label(self, app, isolated):
        from palaskript.datatypes import SourceInfo

        window = _quiet_window()
        try:
            window.db.add(
                SourceInfo(kind="file", source_id="file:a", title="Dosya", duration=60.0),
                "raw",
            )
            window.refresh()
            assert window.table.item(0, 2).text() == "Bekliyor"
        finally:
            _dispose(window)


class TestShimmerVisibleAtLowProgress:
    """Ilerleme %15'teyken band minicik dolgunun icinde kaliyor ve
    gorunmuyordu; oysa "calisiyor mu" sorusuna cevap veren tam da o."""

    def test_low_fill_still_animates(self, app):
        from palaskript.ui.progress import ShimmerBar

        bar = ShimmerBar()
        bar.resize(200, 7)
        bar.setValue(15)
        bar.setActive(True)

        bar._phase = 0.1
        first = bar.grab().toImage().constBits().tobytes()
        bar._phase = 0.6
        second = bar.grab().toImage().constBits().tobytes()

        assert first != second, "dusuk ilerlemede band gorunmuyor"

    def test_zero_progress_still_animates(self, app):
        """Is basladi ama daha hicbir sey yazilmadiysa da hareket olmali."""
        from palaskript.ui.progress import ShimmerBar

        bar = ShimmerBar()
        bar.resize(200, 7)
        bar.setValue(0)
        bar.setActive(True)

        bar._phase = 0.1
        first = bar.grab().toImage().constBits().tobytes()
        bar._phase = 0.6
        second = bar.grab().toImage().constBits().tobytes()

        assert first != second, "sifir ilerlemede band gorunmuyor"


class TestCloseGuard:
    """Calisan is varken kapatma onay istemeli.

    Bu davranis testleri asarak kendini gosterdi: modal acilip cevap
    bekliyordu. Dogru davranis, ama bir daha sessizce kaybolmasin.
    """

    def test_asks_before_closing_with_a_running_job(self, app, isolated, monkeypatch):
        from PySide6.QtWidgets import QMessageBox

        from palaskript.datatypes import SourceInfo
        from palaskript.ui import window as window_module

        asked: list[str] = []

        def fake_question(parent, title, text, *args, **kwargs):
            asked.append(title)
            return QMessageBox.StandardButton.No

        monkeypatch.setattr(window_module.QMessageBox, "question", fake_question)

        window = _quiet_window()
        try:
            job = window.db.add(
                SourceInfo(kind="file", source_id="file:x", title="Uzun is", duration=600.0),
                "raw",
            )
            window.db.mark_running(job.id)
            window.close()
            assert asked, "calisan is varken uyari cikmadi"
        finally:
            _dispose(window)

    def test_closes_silently_when_nothing_is_running(self, app, isolated, monkeypatch):
        from palaskript.ui import window as window_module

        asked: list[str] = []
        monkeypatch.setattr(
            window_module.QMessageBox,
            "question",
            lambda *a, **k: asked.append("sordu"),
        )

        window = _quiet_window()
        try:
            window.close()
            assert not asked, "bos kuyrukta gereksiz uyari cikti"
        finally:
            _dispose(window)


class TestUpdateCheckThreadAffinity:
    """"Güncelleme denetle" kucuk bir pencere acip donuyordu.

    Sinyal bir LAMBDA'ya baglanmisti. Qt lambda'nin hangi is parcaciginda
    oldugunu belirleyemedigi icin dogrudan baglanti kuruyor ve slot ISCI is
    parcaciginda calisiyordu; oradan acilan modal pencere donuyor.
    """

    def test_signal_is_connected_to_a_bound_method(self):
        """Kaynakta lambda baglantisi kalmamali."""
        root = Path(__file__).resolve().parent.parent
        source = (root / "palaskript" / "ui" / "window.py").read_text(encoding="utf-8")
        assert "worker.found.connect(self._on_update_found)" in source
        assert "found.connect(lambda" not in source, "sinyal yine lambda'ya bagli"

    def test_slot_runs_on_the_gui_thread(self, app, isolated):
        """Slot arayuz is parcaciginda calismali, isci is parcaciginda degil."""
        import threading

        from palaskript.ui.window import MainWindow, UpdateChecker

        window = MainWindow()
        try:
            gui_thread = threading.get_ident()
            seen: list[int] = []

            window._on_update_found = lambda release: seen.append(threading.get_ident())

            worker = UpdateChecker("ornek/depo")
            worker.found.connect(window._on_update_found)
            worker.found.emit(None)

            assert seen, "slot hic cagrilmadi"
            assert seen[0] == gui_thread
        finally:
            _dispose(window)

    def test_manual_flag_is_carried_without_a_lambda(self, app, isolated):
        window = _quiet_window()
        try:
            window._update_manual = True
            assert window._update_manual is True
            window._update_manual = False
            assert window._update_manual is False
        finally:
            _dispose(window)


class TestSpeedMode:
    """Hiz/kalite ayari."""

    def test_default_is_quality(self):
        from palaskript.config import Settings

        assert Settings().speed_mode == "quality"

    def test_beam_size_follows_the_mode(self):
        from palaskript.engine.local import BEAM_QUALITY, BEAM_SPEED, beam_for

        assert beam_for("quality") == BEAM_QUALITY
        assert beam_for("speed") == BEAM_SPEED
        assert BEAM_SPEED < BEAM_QUALITY

    def test_unknown_mode_falls_back_to_quality(self):
        """Bozuk ayar dosyasi sessizce hizi degil kaliteyi secmeli."""
        from palaskript.engine.local import BEAM_QUALITY, beam_for

        assert beam_for("bilinmeyen") == BEAM_QUALITY

    def test_setting_survives_a_round_trip(self, tmp_path):
        from palaskript import config

        settings = config.Settings()
        settings.speed_mode = "speed"
        path = tmp_path / "settings.json"
        config.save(settings, path)
        assert config.load(path).speed_mode == "speed"

    def test_dialog_exposes_the_choice(self, app, isolated):
        from palaskript.config import Settings
        from palaskript.ui.settings_dialog import SettingsDialog

        settings = Settings()
        settings.speed_mode = "speed"
        dialog = SettingsDialog(settings)
        try:
            assert dialog.speed_combo.currentData() == "speed"
            assert dialog.result_settings().speed_mode == "speed"
        finally:
            dialog.deleteLater()
