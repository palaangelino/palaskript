"""Kullanici ayarlari.

%APPDATA%\\Transkript\\settings.json icinde saklaniyor. Bilinmeyen alanlar
yok sayiliyor ve eksik alanlar varsayilana dusuyor, boylece surum yukseltmede
eski ayar dosyasi uygulamayi kirmiyor.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

from . import paths

LanguageChoice = Literal["auto", "tr", "en"]
TimestampMode = Literal["paragraph", "interval", "none"]
SubtitlePolicy = Literal["ask", "always", "never"]
CookieBrowser = Literal["none", "chrome", "edge", "firefox", "brave"]


def _default_output_dir() -> str:
    return str(paths.default_output_dir())


@dataclass
class Settings:
    # Bos birakilirsa donanim profili secer. Kullanici elle secerse burada kalir.
    model: str = "auto"
    language: LanguageChoice = "auto"

    timestamp_mode: TimestampMode = "interval"
    timestamp_interval_minutes: int = 5

    output_dir: str = field(default_factory=_default_output_dir)
    export_pdf: bool = True
    export_txt: bool = True

    # None ise fiziksel cekirdek sayisi kullanilir.
    cpu_threads: int | None = None
    low_memory_mode: bool = False

    # Indirilen ses is bitince silinsin mi. Saklamak yeniden calistirmayi
    # hizlandirir ama disk yer.
    keep_audio: bool = False

    cookie_browser: CookieBrowser = "none"

    # Videoda insan eliyle yazilmis altyazi varsa ne yapilsin.
    manual_subtitle_policy: SubtitlePolicy = "ask"

    # Bolum basliklarini PDF'te kullan (YouTube bolumleri veya zamana gore yedek).
    use_chapters: bool = True
    auto_chapter_minutes: int = 15

    # Acilista GitHub'da yeni surum var mi diye bak. Kurulum ASLA kendiliginden
    # yapilmiyor, yalnizca bir cubuk gosteriliyor.
    check_updates: bool = True
    # Bos ise updates.DEFAULT_REPO kullaniliyor. Catallayanlar kendi deposunu
    # uygulamayi yeniden derlemeden buradan verebiliyor.
    update_repo: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir)


def load(path: Path | None = None) -> Settings:
    target = path or paths.settings_file()
    if not target.exists():
        return Settings()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Bozuk ayar dosyasi uygulamayi acilamaz hale getirmesin.
        return Settings()
    if not isinstance(raw, dict):
        return Settings()
    try:
        return Settings.from_dict(raw)
    except TypeError:
        return Settings()


def save(settings: Settings, path: Path | None = None) -> None:
    target = path or paths.settings_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(target)
