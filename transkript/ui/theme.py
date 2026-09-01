"""Uygulamanin kendi gorsel dili.

Sistem temasi TAKIP EDILMIYOR. Bunun iki gerekcesi var:

1. Tutarlilik. Windows'un acik ve koyu temasi ayni arayuzu iki farkli sekilde
   gosteriyor ve ozel renkler (uyari cubuklari, ilerleme, secim) her ikisinde
   birden dogru gorunecek sekilde ayarlanamiyor. Nitekim ilk surumde koyu
   temada uyari cubugunun yazisi tamamen kaybolmustu.
2. Karakter. Krem zemin, sicak gri kenarliklar ve tek bir turuncu vurgu, sistem
   temasinin nototu yerine belgeye bakan bir arac hissi veriyor.

Palet tek: acik krem zeminler, sicak gri kenarliklar, siyah yazi, tek turuncu
vurgu. Turuncu SADECE su dort yerde kullaniliyor: birincil eylem, ilerleme
dolgusu, secili satir ve odak halkasi. Her yere serpistirilirse vurgu olmaktan
cikiyor.

Fontlar paketle geliyor (IBM Plex Sans, OFL). Sistem fontuna guvenmiyoruz:
makineden makineye degisiyor ve tasarim onunla birlikte degisiyor.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from .. import paths

# --------------------------------------------------------------------- palet

BACKGROUND = "#FAF6EF"        # ana zemin
SURFACE = "#FFFDF9"           # yukseltilmis yuzey: tablo, girdi, kart
SURFACE_SUNKEN = "#F2EBDE"    # basliklar, gruplar
SURFACE_HOVER = "#F6EFE3"

BORDER = "#DCD4C4"            # sicak gri kenarlik
BORDER_STRONG = "#C3B9A4"

ACCENT = "#C86A28"            # acik turuncu
ACCENT_HOVER = "#B25A1C"
ACCENT_PRESSED = "#9C4D14"
ACCENT_SOFT = "#F6E7D6"       # secim ve uyari zemini
ACCENT_SOFT_BORDER = "#E4C6A4"

TEXT = "#1B1713"              # siyah yazi
TEXT_SECONDARY = "#665C50"
TEXT_MUTED = "#8C8173"
TEXT_ON_ACCENT = "#FFFFFF"

DANGER = "#A8382B"
DANGER_SOFT = "#F7E4E0"
SUCCESS = "#4A6E3A"

# Yazi tipi aileleri; yuklenemezse sistem fontuna duseluyor.
FAMILY = "IBM Plex Sans"
FALLBACK_FAMILY = "Segoe UI"

BASE_POINT_SIZE = 10

_FONT_FILES = (
    "IBMPlexSans-Regular.ttf",
    "IBMPlexSans-Medium.ttf",
    "IBMPlexSans-SemiBold.ttf",
)

_loaded_family: str | None = None


def load_fonts() -> str:
    """Paketlenmis fontlari kaydet ve kullanilacak aile adini dondur."""
    global _loaded_family
    if _loaded_family is not None:
        return _loaded_family

    families: set[str] = set()
    for name in _FONT_FILES:
        path = paths.font_file(name)
        if not path.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0:
            families.update(QFontDatabase.applicationFontFamilies(font_id))

    _loaded_family = FAMILY if FAMILY in families else FALLBACK_FAMILY
    return _loaded_family


def base_font(point_size: int = BASE_POINT_SIZE, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(load_fonts(), point_size)
    font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def _palette() -> QPalette:
    """Qt paleti.

    Stil sayfasi cogu seyi kapsiyor ama palet yine de dogru olmali: bazi
    yerlesik widget'lar (menu golgeleri, secim rengi, devre disi metin)
    dogrudan paletten okuyor.
    """
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(BACKGROUND))
    p.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE_SUNKEN))
    p.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Button, QColor(SURFACE))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT_SOFT))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(TEXT))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(BACKGROUND))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_MUTED))
    p.setColor(QPalette.ColorRole.Link, QColor(ACCENT))

    for group in (QPalette.ColorGroup.Disabled,):
        p.setColor(group, QPalette.ColorRole.WindowText, QColor(TEXT_MUTED))
        p.setColor(group, QPalette.ColorRole.Text, QColor(TEXT_MUTED))
        p.setColor(group, QPalette.ColorRole.ButtonText, QColor(TEXT_MUTED))
    return p


def _asset_url(name: str) -> str:
    """Stil sayfasi icin dosya yolu.

    Qt stil sayfalarinda ters bolu kacis karakteri sayiliyor, Windows
    yollarinda duz bolu kullanmak gerekiyor.
    """
    return str(paths.assets_dir() / name).replace("\\", "/")


def stylesheet() -> str:
    family = load_fonts()
    check_light = _asset_url("check-light.png")
    check_muted = _asset_url("check-muted.png")
    return f"""
* {{
    font-family: "{family}", "{FALLBACK_FAMILY}", sans-serif;
    outline: none;
}}

QWidget {{
    background-color: {BACKGROUND};
    color: {TEXT};
    font-size: {BASE_POINT_SIZE}pt;
}}

QMainWindow, QDialog {{
    background-color: {BACKGROUND};
}}

/* ------------------------------------------------------------- arac cubugu */

QToolBar {{
    background-color: {BACKGROUND};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 8px;
    spacing: 2px;
}}

QToolBar::separator {{
    background-color: {BORDER};
    width: 1px;
    margin: 4px 8px;
}}

QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 6px 12px;
    color: {TEXT};
}}

QToolButton:hover {{
    background-color: {SURFACE_HOVER};
    border-color: {BORDER};
}}

QToolButton:pressed {{
    background-color: {SURFACE_SUNKEN};
    border-color: {BORDER_STRONG};
}}

/* ----------------------------------------------------------------- butonlar */

QPushButton {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 5px;
    padding: 7px 16px;
    color: {TEXT};
}}

QPushButton:hover {{
    background-color: {SURFACE_HOVER};
    border-color: {ACCENT_SOFT_BORDER};
}}

QPushButton:pressed {{
    background-color: {SURFACE_SUNKEN};
}}

QPushButton:disabled {{
    color: {TEXT_MUTED};
    background-color: {SURFACE_SUNKEN};
    border-color: {BORDER};
}}

/* Birincil eylem: turuncunun kullanildigi dort yerden biri. */
QPushButton[primary="true"] {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    color: {TEXT_ON_ACCENT};
}}

QPushButton[primary="true"]:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}

QPushButton[primary="true"]:pressed {{
    background-color: {ACCENT_PRESSED};
    border-color: {ACCENT_PRESSED};
}}

QPushButton:default {{
    border-color: {ACCENT_SOFT_BORDER};
}}

/* ------------------------------------------------------------------ girdiler */

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 5px;
    padding: 6px 10px;
    color: {TEXT};
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}

/* Acilir liste oku ve sayi kutusu dugmeleri Qt'nin kendi cizimine birakildi:
   CSS ile ucgen cizmek Qt'de duzgun sonuc vermiyor ve dugmeleri sifirlamak
   onlari tamamen gorunmez yapiyor. */
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

/* Ok cizimi Qt'ye ait; burada yalnizca yer aciyoruz, aksi halde dugmeler
   ince bir cizgiye sikisiyor. */
QSpinBox::up-button, QSpinBox::down-button {{
    width: 18px;
    margin-right: 3px;
}}

QComboBox QAbstractItemView {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 5px;
    padding: 4px;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}

/* --------------------------------------------------------------- onay kutusu */

QCheckBox {{
    spacing: 8px;
    background: transparent;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    background-color: {SURFACE};
}}

QCheckBox::indicator:hover {{
    border-color: {ACCENT_SOFT_BORDER};
}}

QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    image: url("{check_light}");
}}

QCheckBox::indicator:checked:disabled {{
    background-color: {SURFACE_SUNKEN};
    border-color: {BORDER};
    image: url("{check_muted}");
}}

QCheckBox::indicator:disabled {{
    background-color: {SURFACE_SUNKEN};
    border-color: {BORDER};
}}

/* -------------------------------------------------------------------- gruplar */

QGroupBox {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 14px;
    padding: 14px 14px 12px 14px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    background-color: {BACKGROUND};
    color: {TEXT_SECONDARY};
}}

/* -------------------------------------------------------------------- tablo */

QTableWidget, QTableView {{
    background-color: {SURFACE};
    alternate-background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: transparent;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}

QTableWidget::item, QTableView::item {{
    padding: 9px 10px;
    border: none;
    border-bottom: 1px solid {SURFACE_SUNKEN};
}}

QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {ACCENT_SOFT};
    color: {TEXT};
}}

QHeaderView::section {{
    background-color: {SURFACE_SUNKEN};
    text-align: left;
    color: {TEXT_SECONDARY};
    border: none;
    border-bottom: 1px solid {BORDER};
    border-right: 1px solid {BORDER};
    padding: 8px 10px;
}}

QHeaderView::section:last {{
    border-right: none;
}}

/* ------------------------------------------------------------------ ilerleme */

QProgressBar {{
    background-color: {SURFACE_SUNKEN};
    border: 1px solid {BORDER};
    border-radius: 4px;
    min-height: 7px;
    max-height: 7px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 3px;
}}

/* ------------------------------------------------------------------ sekmeler */

QTabWidget::pane {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    top: -1px;
}}

QTabBar::tab {{
    background-color: transparent;
    color: {TEXT_SECONDARY};
    border: 1px solid transparent;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    padding: 8px 16px;
    margin-right: 2px;
}}

QTabBar::tab:hover {{
    color: {TEXT};
    background-color: {SURFACE_HOVER};
}}

QTabBar::tab:selected {{
    background-color: {SURFACE};
    color: {TEXT};
    border-color: {BORDER};
    border-bottom-color: {SURFACE};
}}

/* ------------------------------------------------------------- durum cubugu */

QStatusBar {{
    background-color: {SURFACE_SUNKEN};
    border-top: 1px solid {BORDER};
    color: {TEXT_SECONDARY};
    padding: 2px 6px;
}}

QStatusBar::item {{
    border: none;
}}

/* -------------------------------------------------------------------- menuler */

QMenu {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 5px;
}}

QMenu::item {{
    padding: 7px 22px 7px 14px;
    border-radius: 4px;
    color: {TEXT};
}}

QMenu::item:selected {{
    background-color: {ACCENT_SOFT};
}}

QMenu::item:disabled {{
    color: {TEXT_MUTED};
}}

QMenu::separator {{
    height: 1px;
    background-color: {BORDER};
    margin: 5px 8px;
}}

/* ----------------------------------------------------------------- kaydirma */

QScrollBar:vertical {{
    background-color: transparent;
    width: 12px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: {BORDER_STRONG};
    border-radius: 5px;
    min-height: 30px;
    margin: 2px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {TEXT_MUTED};
}}

QScrollBar:horizontal {{
    background-color: transparent;
    height: 12px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background-color: {BORDER_STRONG};
    border-radius: 5px;
    min-width: 30px;
    margin: 2px;
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}

QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* ------------------------------------------------------------------ ipuclari */

QToolTip {{
    background-color: {TEXT};
    color: {BACKGROUND};
    border: none;
    border-radius: 4px;
    padding: 6px 9px;
}}

/* ------------------------------------------------------------ ozel siniflar */

QLabel[muted="true"] {{
    color: {TEXT_MUTED};
    background: transparent;
}}

QLabel[warning="true"] {{
    color: {DANGER};
    background: transparent;
}}

QLabel {{
    background: transparent;
}}
"""


def banner_style(*, tone: str = "accent") -> str:
    """Bilgilendirme cubugu stili.

    Renkler paletten geliyor ve zemin/metin/buton birlikte belirleniyor;
    tek tek birakilirsa cubuk okunmaz hale geliyor.
    """
    background = ACCENT_SOFT if tone == "accent" else SURFACE_SUNKEN
    border = ACCENT_SOFT_BORDER if tone == "accent" else BORDER_STRONG
    return (
        f"QWidget {{ background-color: {background};"
        f" border: 1px solid {border}; border-radius: 6px; }}"
        f" QLabel {{ color: {TEXT}; border: none; background: transparent; }}"
        f" QPushButton {{ color: {TEXT}; background-color: {SURFACE};"
        f" border: 1px solid {border}; border-radius: 5px; padding: 6px 14px; }}"
        f" QPushButton:hover {{ background-color: {BACKGROUND}; }}"
        f" QPushButton:pressed {{ background-color: {SURFACE_SUNKEN}; }}"
        # Birincil eylem kurali burada da tanimlanmali: widget'a verilen stil
        # sayfasi uygulama genelindekini gecersiz kiliyor.
        f' QPushButton[primary="true"] {{ background-color: {ACCENT};'
        f" border-color: {ACCENT}; color: {TEXT_ON_ACCENT}; }}"
        f' QPushButton[primary="true"]:hover {{ background-color: {ACCENT_HOVER};'
        f" border-color: {ACCENT_HOVER}; }}"
        f' QPushButton[primary="true"]:pressed {{ background-color: {ACCENT_PRESSED};'
        f" border-color: {ACCENT_PRESSED}; }}"
    )


def apply(app: QApplication) -> None:
    """Temayi uygula. QApplication olusturulduktan hemen sonra cagriliyor."""
    # Fusion, stil sayfalarini tutarli uyguluyor. Yerel Windows stili bircok
    # kurali yok sayiyor ve tasarim yarim kaliyor.
    app.setStyle("Fusion")
    app.setPalette(_palette())
    app.setFont(base_font())
    app.setStyleSheet(stylesheet())
