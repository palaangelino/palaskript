"""PDF yazi tipi cozumleme.

ReportLab'in yerlesik fontlari (Helvetica, Times) Turkce karakterleri
tasimiyor: g-breve, i-dotless, s-cedilla PDF'te ya bos kutu ya da yanlis harf
cikiyor. Bu yuzden mutlaka bir TrueType font gomulmeli.

Once paketle gelen DejaVuSans araniyor, yoksa Windows sistem fontlarina
duseluyor. Sistem fontunu paketlemiyoruz, calisma aninda yolundan okuyoruz:
lisans acisindan temiz ve kurulum dosyasini sisirmiyor. Windows'ta bu fontlarin
hepsi her zaman var, dolayisiyla pratikte yedek zinciri hep tutuyor.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from .. import paths

REGULAR = "TranskriptBody"
BOLD = "TranskriptBodyBold"

# Yerlesik yedek. Turkce karakterleri bozar, sadece hicbir TTF bulunamazsa.
FALLBACK_REGULAR = "Helvetica"
FALLBACK_BOLD = "Helvetica-Bold"


@dataclass(frozen=True, slots=True)
class FontChoice:
    regular: str
    bold: str
    source: str
    supports_turkish: bool


def _windows_fonts_dir() -> Path:
    root = os.environ.get("WINDIR", r"C:\Windows")
    return Path(root) / "Fonts"


def _candidates() -> list[tuple[str, Path, Path]]:
    """(etiket, duz, kalin) adaylari, tercih sirasiyla."""
    bundled = paths.assets_dir() / "fonts"
    win = _windows_fonts_dir()
    return [
        ("DejaVu Sans", bundled / "DejaVuSans.ttf", bundled / "DejaVuSans-Bold.ttf"),
        # Calibri govde metni icin tasarlandi, 90 sayfalik okumada Segoe UI'dan rahat.
        ("Calibri", win / "calibri.ttf", win / "calibrib.ttf"),
        ("Segoe UI", win / "segoeui.ttf", win / "segoeuib.ttf"),
        ("Arial", win / "arial.ttf", win / "arialbd.ttf"),
        ("Tahoma", win / "tahoma.ttf", win / "tahomabd.ttf"),
        ("Times New Roman", win / "times.ttf", win / "timesbd.ttf"),
    ]


_choice: FontChoice | None = None


def register() -> FontChoice:
    """Fontlari ReportLab'a kaydet ve secimi dondur. Idempotent."""
    global _choice
    if _choice is not None:
        return _choice

    for label, regular_path, bold_path in _candidates():
        if not regular_path.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont(REGULAR, str(regular_path)))
            if bold_path.exists():
                pdfmetrics.registerFont(TTFont(BOLD, str(bold_path)))
                bold_name = BOLD
            else:
                # Kalin varyant yoksa duzu kalin olarak da kaydet: PDF yine
                # okunur, sadece basliklar daha az one cikar.
                bold_name = REGULAR
        except Exception:  # noqa: BLE001 - bozuk font dosyasi, siradakini dene
            continue

        addMapping(REGULAR, 0, 0, REGULAR)
        addMapping(REGULAR, 1, 0, bold_name)
        _choice = FontChoice(
            regular=REGULAR, bold=bold_name, source=label, supports_turkish=True
        )
        return _choice

    _choice = FontChoice(
        regular=FALLBACK_REGULAR,
        bold=FALLBACK_BOLD,
        source="Helvetica (yerlesik)",
        supports_turkish=False,
    )
    return _choice


def reset() -> None:
    """Testler icin onbellegi temizle."""
    global _choice
    _choice = None
