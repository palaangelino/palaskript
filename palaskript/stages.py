"""Is asamalari ve genel ilerlemedeki paylari.

Ayri bir modulde duruyor cunku hem boru hatti (ilerleme bildirirken) hem de
arayuz (iki bildirim arasini doldururken) ayni sayilara ihtiyac duyuyor.
Arayuzun boru hattini import etmesi gerekmemeli: o zincir faster-whisper'i ve
yanindaki her seyi de getiriyor.
"""

from __future__ import annotations

Stage = str

# (baslangic, bitis) olarak genel ilerlemedeki pay.
WEIGHTS: dict[Stage, tuple[float, float]] = {
    "probe": (0.00, 0.02),
    "subtitles": (0.02, 0.90),
    "download": (0.02, 0.15),
    "model": (0.15, 0.22),
    "transcribe": (0.22, 0.95),
    "export": (0.95, 1.00),
}

# Is bitmeden once cubuk buraya kadar cikabiliyor. Tahmin gercekten hizli
# olsa bile %100 gostermek yanlis: bitmeyen bir isi bitmis gibi gostermek,
# gec kalmis bir cubuktan daha kotu.
CEILING = 0.99


def overall(stage: Stage, local: float) -> float:
    """Asama ici oraniki genel orana cevir."""
    lo, hi = WEIGHTS.get(stage, (0.0, 1.0))
    return lo + (hi - lo) * max(0.0, min(1.0, local))


def stage_ceiling(stage: Stage | None) -> float:
    """Bir asamanin ulasabilecegi en yuksek genel oran.

    Iki gercek bildirim arasinda cubugu ilerletirken bu sinir kullaniliyor:
    tahmin, icinde bulunulan asamanin sonunu asamaz.
    """
    if stage is None:
        return CEILING
    return min(WEIGHTS.get(stage, (0.0, CEILING))[1], CEILING)
