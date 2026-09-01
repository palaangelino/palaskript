"""Uygulama dizinleri.

Kurulu uygulama Program Files altinda calisir ve oraya yazamaz, bu yuzden
degisken veri %APPDATA% ve %LOCALAPPDATA% altinda tutuluyor. Model onbellegi
LOCALAPPDATA'da cunku buyuk ve makineye ozel, gezici profille tasinmamali.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def _env_dir(var: str, fallback: Path) -> Path:
    raw = os.environ.get(var)
    return Path(raw) if raw else fallback


def app_data_dir() -> Path:
    """Ayarlar, kuyruk veritabani, ara kayitlar."""
    base = _env_dir("APPDATA", Path.home() / "AppData" / "Roaming")
    return base / APP_NAME


def local_data_dir() -> Path:
    """Model onbellegi, gecici ses dosyalari, guncellenen yt-dlp."""
    base = _env_dir("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    return base / APP_NAME


def models_dir() -> Path:
    return local_data_dir() / "models"


def cache_dir() -> Path:
    return local_data_dir() / "cache"


def checkpoints_dir() -> Path:
    return app_data_dir() / "checkpoints"


def logs_dir() -> Path:
    return app_data_dir() / "logs"


def settings_file() -> Path:
    return app_data_dir() / "settings.json"


def queue_db_file() -> Path:
    return app_data_dir() / "queue.db"


def default_output_dir() -> Path:
    r"""Belgeler\Transkript. Kullanici ayarlardan degistirebiliyor."""
    docs = Path.home() / "Documents"
    if not docs.exists():
        docs = Path.home() / "Belgeler"
    if not docs.exists():
        docs = Path.home()
    return docs / APP_NAME


def bundle_dir() -> Path:
    """Paketlenmis kaynaklarin (font, ikon) kok dizini.

    PyInstaller onedir modunda sys._MEIPASS'e acilir, gelistirme sirasinda repo koku.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    return bundle_dir() / "assets"


def font_file(name: str) -> Path:
    return assets_dir() / "fonts" / name


def ensure_dirs() -> None:
    """Yazilabilir dizinleri olustur. Uygulama acilisinda bir kez cagriliyor."""
    for d in (
        app_data_dir(),
        local_data_dir(),
        models_dir(),
        cache_dir(),
        checkpoints_dir(),
        logs_dir(),
    ):
        d.mkdir(parents=True, exist_ok=True)
