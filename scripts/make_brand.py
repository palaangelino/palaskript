"""Ikon ve kurulum sihirbazi gorsellerini uret.

Hepsi ayni paletten cikiyor (palaskript/ui/theme.py): krem zeminler, sicak gri
kenarliklar, siyah yazi, tek turuncu vurgu. Kurulum ekrani ile uygulama ayni
dili konussun diye tek bir betikten uretiliyorlar.

Ikon zemini koyu: krem bir ikon acik renkli gorev cubugunda kayboluyor. Koyu
zemin uzerinde krem cubuklar ve turuncu vurgu her iki gorev cubugunda da
okunuyor.

Kurulum sihirbazi BMP istiyor (Inno Setup PNG kabul etmiyor).

    python scripts/make_brand.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
INSTALLER = ASSETS / "installer"
FONT_DIR = ASSETS / "fonts"

# Palet (theme.py ile ayni)
CREAM = (250, 246, 239)
CREAM_SUNKEN = (242, 235, 222)
BORDER = (220, 212, 196)
ACCENT = (200, 106, 40)
INK = (27, 23, 19)
INK_SOFT = (102, 92, 80)
MARK_BG = (26, 22, 18)
MARK_BAR = (245, 238, 227)

ICON_SIZES = [16, 24, 32, 48, 64, 128, 256]

# Dalga cubuklarinin goreli yukseklikleri. Ortadaki turuncu.
HEIGHTS = [0.34, 0.62, 0.94, 0.70, 0.44]

# Ikon icindeki kalbin cubuklari. 16 pikselde okunabilmesi icin bes degil uc:
# kalbin ic alani kareden dar, bes cubuk lapa gibi cikiyor.
HEART_BAR_HEIGHTS = [0.60, 1.0, 0.72]


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONT_DIR / name
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def draw_mark(size: int, *, background=MARK_BG, bar=MARK_BAR, accent=ACCENT, radius_ratio=0.22):
    """Uygulama isareti: koyu kare uzerinde ses dalgasi."""
    scale = 4
    canvas = size * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    if background is not None:
        draw.rounded_rectangle(
            [0, 0, canvas - 1, canvas - 1], radius=int(canvas * radius_ratio), fill=background
        )

    count = len(HEIGHTS)
    bar_width = canvas * 0.11
    gap = (canvas - bar_width * count) / (count + 1)
    centre = canvas / 2

    for index, height in enumerate(HEIGHTS):
        x0 = gap + index * (bar_width + gap)
        half = canvas * 0.36 * height
        colour = accent if index == count // 2 else bar
        draw.rounded_rectangle(
            [x0, centre - half, x0 + bar_width, centre + half],
            radius=bar_width / 2,
            fill=colour,
        )

    return image.resize((size, size), Image.LANCZOS)


def _heart_polygon(canvas: int, *, inset: float = 0.0) -> list[tuple[float, float]]:
    """Klasik kalp egrisi.

    Iki daire + ucgen yerine parametrik egri kullaniliyor: omuzlari yumusak,
    ucu sivri cikiyor ve kucuk boyutlarda daha okunakli oluyor.
    """
    import math

    points: list[tuple[float, float]] = []
    steps = 400
    scale = (canvas / 34.0) * (1.0 - inset)
    for i in range(steps):
        t = 2 * math.pi * i / steps
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        points.append((canvas / 2 + x * scale, canvas / 2 - y * scale))
    return points


def draw_heart_mark(size: int) -> Image.Image:
    """Uygulama isareti: kalp seklinde, icinde ses cubuklari.

    Kalp DOLU cizilip cubuklar uzerine krem renkte konuyor; cubuklar kalbin
    disina tasmasin diye kalp maskesiyle kirpiliyor.
    """
    scale = 8
    canvas = size * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.polygon(_heart_polygon(canvas), fill=ACCENT)

    # Cubuklar ayri katmanda; kalp maskesiyle kirpilacak.
    bars = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    bars_draw = ImageDraw.Draw(bars)
    count = len(HEART_BAR_HEIGHTS)
    bar_width = canvas * 0.088
    gap = canvas * 0.062
    total = count * bar_width + (count - 1) * gap
    x = (canvas - total) / 2
    # Cubuklar kalbin GOVDESINE oturmali. Merkeze koyunca en uzun cubuk ustteki
    # centige giriyor ve kirik gorunuyor; biraz asagi aliniyor.
    centre_y = canvas * 0.52
    for height in HEART_BAR_HEIGHTS:
        half = canvas * 0.135 * height
        bars_draw.rounded_rectangle(
            [x, centre_y - half, x + bar_width, centre_y + half],
            radius=bar_width / 2,
            fill=MARK_BAR,
        )
        x += bar_width + gap

    mask = Image.new("L", (canvas, canvas), 0)
    ImageDraw.Draw(mask).polygon(_heart_polygon(canvas, inset=0.16), fill=255)
    image.paste(bars, (0, 0), Image.composite(bars.split()[3], Image.new("L", (canvas, canvas), 0), mask))

    return image.resize((size, size), Image.LANCZOS)


def build_heart_glyph() -> None:
    """Altbilgideki kalp.

    Metne gomulu bir karakter olarak yazamiyoruz: paketlenmis font U+2665
    tasimiyor ve Qt o karakter icin sistem emoji fontuna dusuyor, yani araya
    renkli bir emoji giriyor. Kucuk bir gorsel olarak cizmek hem garanti hem
    palete uygun.
    """
    for name, colour, size in (("heart-accent.png", ACCENT, 13), ("heart-ink.png", INK, 13)):
        scale = 16
        canvas = size * scale
        image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
        ImageDraw.Draw(image).polygon(_heart_polygon(canvas), fill=colour)
        target = ASSETS / name
        image.resize((size, size), Image.LANCZOS).save(target, format="PNG")
        print(f"yazildi: {target.name}")


def build_check_marks() -> None:
    """Onay kutusu tikleri.

    Qt stil sayfasi tik isaretini kendisi cizemiyor; indicator'e resim vermek
    gerekiyor. Turuncu dolgunun uzerine beyaz tik, devre disi durumda gri.
    """
    for name, colour in (("check-light.png", (255, 255, 255)), ("check-muted.png", INK_SOFT)):
        scale = 8
        size = 16
        canvas = size * scale
        image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        width = int(canvas * 0.13)
        draw.line(
            [
                (canvas * 0.24, canvas * 0.52),
                (canvas * 0.43, canvas * 0.71),
                (canvas * 0.77, canvas * 0.31),
            ],
            fill=colour,
            width=width,
            joint="curve",
        )
        # Uc noktalari yuvarlat
        radius = width / 2
        for x, y in ((canvas * 0.24, canvas * 0.52), (canvas * 0.77, canvas * 0.31)):
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=colour)
        target = ASSETS / name
        image.resize((size, size), Image.LANCZOS).save(target, format="PNG")
        print(f"yazildi: {target.name}")


def build_icon() -> None:
    frames = [draw_heart_mark(size) for size in ICON_SIZES]
    target = ASSETS / "icon.ico"
    frames[-1].save(target, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    frames[-1].save(target.with_suffix(".png"), format="PNG")
    print(f"yazildi: {target}")


def build_wizard_large(width: int, height: int) -> Image.Image:
    """Sihirbazin karsilama ve bitis sayfasindaki dikey gorsel."""
    image = Image.new("RGB", (width, height), CREAM)
    draw = ImageDraw.Draw(image)

    # Alt bolumde hafif koyu bir zemin: isaret uzerinde dursun.
    band_top = int(height * 0.52)
    draw.rectangle([0, band_top, width, height], fill=CREAM_SUNKEN)
    draw.line([(0, band_top), (width, band_top)], fill=BORDER, width=1)

    mark_size = int(width * 0.42)
    mark = draw_heart_mark(mark_size)
    image.paste(mark, ((width - mark_size) // 2, int(height * 0.16)), mark)

    title_font = _font("IBMPlexSans-SemiBold.ttf", max(16, int(width * 0.115)))
    body_font = _font("IBMPlexSans-Regular.ttf", max(10, int(width * 0.062)))

    title = "Transkript"
    box = draw.textbbox((0, 0), title, font=title_font)
    draw.text(
        ((width - (box[2] - box[0])) // 2, int(height * 0.40)),
        title,
        font=title_font,
        fill=INK,
    )

    lines = ["Videodan", "PDF transkript"]
    y = band_top + int(height * 0.06)
    for line in lines:
        box = draw.textbbox((0, 0), line, font=body_font)
        draw.text(((width - (box[2] - box[0])) // 2, y), line, font=body_font, fill=INK_SOFT)
        y += int((box[3] - box[1]) * 2.0)

    # Turuncu vurgu cizgisi
    accent_width = int(width * 0.22)
    accent_y = y + int(height * 0.03)
    draw.rounded_rectangle(
        [(width - accent_width) // 2, accent_y, (width + accent_width) // 2, accent_y + 3],
        radius=2,
        fill=ACCENT,
    )
    return image


def build_wizard_small(size_w: int, size_h: int) -> Image.Image:
    """Diger sayfalarda sag ustte duran kucuk gorsel."""
    image = Image.new("RGB", (size_w, size_h), CREAM)
    mark_size = int(min(size_w, size_h) * 0.82)
    mark = draw_heart_mark(mark_size)
    image.paste(mark, ((size_w - mark_size) // 2, (size_h - mark_size) // 2), mark)
    return image


def build_installer_images() -> None:
    INSTALLER.mkdir(parents=True, exist_ok=True)

    # Inno Setup 6 birden fazla boyut kabul ediyor ve ekran olceklemesine gore
    # uygun olani seciyor.
    large_sizes = [(164, 314), (192, 386), (246, 459), (273, 556), (328, 604)]
    for width, height in large_sizes:
        path = INSTALLER / f"wizard-large-{width}x{height}.bmp"
        build_wizard_large(width, height).save(path, format="BMP")
        print(f"yazildi: {path.name}")

    small_sizes = [(55, 58), (64, 68), (83, 80), (92, 97), (110, 106), (119, 123), (138, 140)]
    for width, height in small_sizes:
        path = INSTALLER / f"wizard-small-{width}x{height}.bmp"
        build_wizard_small(width, height).save(path, format="BMP")
        print(f"yazildi: {path.name}")


def main() -> int:
    if not (FONT_DIR / "IBMPlexSans-Regular.ttf").exists():
        print(
            "Uyari: paketlenmis font bulunamadi, sihirbaz gorselleri varsayilan "
            "fontla uretilecek.",
            file=sys.stderr,
        )
    build_icon()
    build_heart_glyph()
    build_check_marks()
    build_installer_images()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
