"""Uygulama giris noktasi."""

from __future__ import annotations

import logging
import multiprocessing
import sys
from logging.handlers import RotatingFileHandler

from . import APP_NAME, __version__, paths, ytdlp_update


def _setup_logging() -> None:
    paths.ensure_dirs()
    handler = RotatingFileHandler(
        paths.logs_dir() / "transkript.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr:
        root.addHandler(logging.StreamHandler(sys.stderr))


def _excepthook(exc_type, exc_value, exc_tb) -> None:  # noqa: ANN001 - sys imzasi
    """Yakalanmamis hatayi hem kaydet hem kullaniciya goster.

    Sessizce kapanan bir uygulama, hata mesaji veren uygulamadan cok daha kotu.
    """
    logging.getLogger("transkript").critical(
        "Yakalanmamis hata", exc_info=(exc_type, exc_value, exc_tb)
    )
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is not None:
            QMessageBox.critical(
                None,
                "Beklenmeyen hata",
                f"{exc_value}\n\nAyrıntı kayıt dosyasında:\n{paths.logs_dir()}",
            )
    except Exception:  # noqa: BLE001 - hata gostericisi de patlarsa sessiz kal
        pass


def main() -> int:
    multiprocessing.freeze_support()
    _setup_logging()

    # yt_dlp import edilmeden ONCE: kullanicinin guncelledigi surum varsa o
    # kullanilsin. YouTube degistikce paketlenmis surum eskiyor.
    if ytdlp_update.activate():
        logging.getLogger("transkript").info("Kullanici dizinindeki yt-dlp kullaniliyor")

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .ui import theme
    from .ui.first_run import maybe_run
    from .ui.window import MainWindow

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, False)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(True)

    # Sistem temasi takip edilmiyor: kendi paletimiz ve fontlarimiz
    # kullaniliyor (gerekcesi ui/theme.py icinde).
    theme.apply(app)

    icon_path = paths.assets_dir() / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    sys.excepthook = _excepthook

    # Ilk acilis: donanimi gosterip modeli sectiriyoruz. Bu is kurulum
    # sirasinda yapilamazdi, model indirmek gerekiyor ve kurulumu on
    # dakikaya cikarirdi.
    maybe_run()

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
