"""Uygulama ikonunu uret.

Bir kez calistirilip assets/icon.ico dosyasini olusturuyor. Ikon depoya
islendigi icin kurulum sirasinda tekrar uretilmesi gerekmiyor; bu betik sadece
tasarim degisirse lazim.

Tasarim: koyu zemin uzerinde ses dalgasi cubuklari. 16 pikselde de okunabilmesi
icin detay yok, sadece kontrast ve birkac kalin cubuk.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZES = [16, 24, 32, 48, 64, 128, 256]

BACKGROUND = (26, 32, 54)
BAR = (233, 236, 245)
ACCENT = (108, 160, 255)

# Dalga cubuklarinin goreli yukseklikleri (0-1). Ortadakiler uzun: konusma.
HEIGHTS = [0.34, 0.62, 0.94, 0.70, 0.44]


def render(size: int) -> Image.Image:
    # 4 kat buyuk cizip kucultuyoruz: kenarlar yumusak ciksin.
    scale = 4
    canvas = size * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    radius = int(canvas * 0.22)
    draw.rounded_rectangle([0, 0, canvas - 1, canvas - 1], radius=radius, fill=BACKGROUND)

    count = len(HEIGHTS)
    bar_width = canvas * 0.11
    gap = (canvas - bar_width * count) / (count + 1)
    centre = canvas / 2

    for index, height in enumerate(HEIGHTS):
        x0 = gap + index * (bar_width + gap)
        x1 = x0 + bar_width
        half = canvas * 0.36 * height
        colour = ACCENT if index == count // 2 else BAR
        draw.rounded_rectangle(
            [x0, centre - half, x1, centre + half],
            radius=bar_width / 2,
            fill=colour,
        )

    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    target = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
    target.parent.mkdir(parents=True, exist_ok=True)

    frames = [render(size) for size in SIZES]
    frames[-1].save(target, format="ICO", sizes=[(s, s) for s in SIZES])

    png = target.with_suffix(".png")
    frames[-1].save(png, format="PNG")
    print(f"Yazildi: {target}")
    print(f"Yazildi: {png}")


if __name__ == "__main__":
    main()
