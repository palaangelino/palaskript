"""Bolumleme.

Konusma videolari icin en buyuk okunabilirlik kazanci burada: 3.5 saatlik bir
konusmanin 90 sayfalik duz metin duvari yerine, YouTube'un kendi bolum
isaretlerine gore ayrilmis, icindekiler tablosu ve PDF yer imleri olan
gezilebilir bir belge cikiyor.

Video bolum tasimiyorsa duzenli araliklarla zaman basligina dusuyoruz. Bu,
gercek bolumler kadar anlamli degil ama 90 sayfalik kesintisiz metinden iyi.
"""

from __future__ import annotations

from .datatypes import Chapter, Paragraph, SourceInfo


def format_timestamp(seconds: float, *, always_hours: bool = False) -> str:
    total = max(0, int(round(seconds)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h or always_hours:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def normalize_chapters(raw: list[Chapter], duration: float) -> list[Chapter]:
    """Bolumleri sirala, bosluklari kapat, sureye kirp.

    YouTube verisi her zaman duzgun gelmiyor: bitis zamanlari eksik olabiliyor
    veya bolumler ust uste binebiliyor.
    """
    if not raw:
        return []

    items = sorted((c for c in raw if c.start is not None), key=lambda c: c.start)
    cleaned: list[Chapter] = []
    for i, ch in enumerate(items):
        start = max(0.0, min(float(ch.start), duration if duration else float(ch.start)))
        if i + 1 < len(items):
            end = float(items[i + 1].start)
        else:
            end = duration if duration else float(ch.end or start)
        if end <= start:
            continue
        cleaned.append(
            Chapter(start=start, end=end, title=ch.title.strip() or "Bolum", origin=ch.origin)
        )
    return cleaned


def auto_chapters(duration: float, interval_minutes: int = 15) -> list[Chapter]:
    """Zamana gore yedek bolumler."""
    if duration <= 0 or interval_minutes <= 0:
        return []
    step = interval_minutes * 60
    if duration <= step:
        return []

    result: list[Chapter] = []
    start = 0.0
    while start < duration:
        end = min(start + step, duration)
        result.append(
            Chapter(
                start=start,
                end=end,
                title=f"{format_timestamp(start, always_hours=True)} - {format_timestamp(end, always_hours=True)}",
                origin="auto",
            )
        )
        start = end
    return result


def build_chapters(
    source: SourceInfo,
    *,
    duration: float | None = None,
    auto_interval_minutes: int = 15,
    enabled: bool = True,
) -> list[Chapter]:
    """Bir is icin kullanilacak bolum listesini uret."""
    if not enabled:
        return []
    total = duration if duration is not None else source.duration
    normalized = normalize_chapters(source.chapters, total)
    if normalized:
        return normalized
    return auto_chapters(total, auto_interval_minutes)


def assign_paragraphs(
    paragraphs: list[Paragraph],
    chapters: list[Chapter],
) -> list[tuple[Chapter | None, list[Paragraph]]]:
    """Paragraflari bolumlere dagit.

    Bolum yoksa tek bir (None, hepsi) grubu doner ve disa aktarim basliksiz
    duz akis uretir.
    """
    if not chapters:
        return [(None, list(paragraphs))]

    ordered = sorted(chapters, key=lambda c: c.start)
    groups: list[tuple[Chapter | None, list[Paragraph]]] = [(c, []) for c in ordered]

    # Ilk bolum 0'dan sonra basliyorsa onundeki metni kaybetmeyelim.
    lead: list[Paragraph] = []

    idx = 0
    for para in paragraphs:
        if para.start < ordered[0].start:
            lead.append(para)
            continue
        while idx + 1 < len(ordered) and para.start >= ordered[idx + 1].start:
            idx += 1
        groups[idx][1].append(para)

    result: list[tuple[Chapter | None, list[Paragraph]]] = []
    if lead:
        result.append((None, lead))
    result.extend((ch, paras) for ch, paras in groups if paras)
    return result
