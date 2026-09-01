"""Ham Whisper segmentlerini okunabilir paragraflara cevirme.

Uc is yapiyor, ucu de PDF kalitesi icin belirleyici:

1. Dikis temizligi: pencere siniri sessizlige hizalanamadiginda bindirme
   uygulaniyor ve o bolge iki kez yaziliyor. Tekrari burada atiyoruz.
2. Halusinasyon filtresi: Whisper uzun kayitlarda takilip ayni cumleyi
   dakikalarca tekrarlayabiliyor.
3. Paragraflandirma: ham segmentler 5-10 saniyelik parcalar. 3.5 saatlik bir
   videoda 2000+ satir eder ve okunmaz bir PDF cikar.
"""

from __future__ import annotations

import re

from .datatypes import Paragraph, Segment

# Paragraf sonu sayilan noktalama.
_SENTENCE_END = (".", "!", "?", "...", "…", ":", ";")

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Karsilastirma icin sadelestir. Turkce buyuk/kucuk harf kurallari burada
    onemli degil, yeter ki tutarli olsun."""
    return _WS_RE.sub(" ", _PUNCT_RE.sub("", text.lower())).strip()


def ends_sentence(text: str) -> bool:
    return text.rstrip().endswith(_SENTENCE_END)


# ---------------------------------------------------------------- dikis


class TranscriptAssembler:
    """Pencere pencere gelen segmentleri tek bir akisa birlestirir.

    Akis halinde calisiyor cunku ara kayit her segmenti geldigi anda diske
    yaziyor: 6 saatlik bir isin cokmede sifirlanmamasi buna bagli.
    """

    # Dikiste karsilastirilan onceki segment sayisi.
    _LOOKBACK = 6
    # Zaman karsilastirmasinda tolerans.
    _EPS = 0.25

    def __init__(self) -> None:
        self.segments: list[Segment] = []

    def add_window(self, segments: list[Segment], *, overlapped: bool) -> list[Segment]:
        """Bir pencerenin segmentlerini ekle, KABUL EDILENLERI dondur.

        Doner deger ara kayda yazilacak olan; reddedilenler diske hic gitmiyor.
        """
        if not segments:
            return []
        if not overlapped or not self.segments:
            self.segments.extend(segments)
            return list(segments)

        last_end = self.segments[-1].end
        recent = {normalize(s.text) for s in self.segments[-self._LOOKBACK :] if s.text.strip()}

        accepted: list[Segment] = []
        for seg in segments:
            # Bindirme bolgesinde mi?
            if seg.start < last_end - self._EPS:
                # Tamamen onceki pencerenin icinde kalıyorsa kesin tekrar.
                if seg.end <= last_end + self._EPS:
                    continue
                # Kismen tasiyorsa metne bak.
                if normalize(seg.text) in recent:
                    continue
            accepted.append(seg)

        self.segments.extend(accepted)
        return accepted

    def result(self) -> list[Segment]:
        return self.segments


# -------------------------------------------------- halusinasyon filtresi


def _collapse_internal_repeats(text: str, min_repeats: int = 3) -> str:
    """Tek bir segmentin icinde tekrarlanan kalibi teke indir.

    Whisper sessizlikte "Altyazi M.K. Altyazi M.K. Altyazi M.K." gibi ciktilar
    uretebiliyor.
    """
    words = text.split()
    if len(words) < min_repeats * 2:
        return text

    for size in range(1, len(words) // min_repeats + 1):
        pattern = words[:size]
        repeats = 1
        idx = size
        while idx + size <= len(words) and words[idx : idx + size] == pattern:
            repeats += 1
            idx += size
        if repeats >= min_repeats and idx == len(words):
            return " ".join(pattern)
    return text


def filter_hallucinations(
    segments: list[Segment],
    *,
    max_consecutive: int = 2,
) -> list[Segment]:
    """Arka arkaya tekrar eden segmentleri kirp.

    Ilk birkac tekrar korunuyor: bazen konusmaci gercekten tekrar ediyor.
    Kesilen sadece sapmis dongu.
    """
    out: list[Segment] = []
    run_key: str | None = None
    run_count = 0

    for seg in segments:
        text = _collapse_internal_repeats(seg.text.strip())
        if not text:
            continue

        key = normalize(text)
        if key and key == run_key:
            run_count += 1
            if run_count > max_consecutive:
                # Dongude: son kabul edilenin bitisini uzat ki zaman ekseni
                # kopmasin, ama metni tekrarlama.
                if out:
                    out[-1].end = seg.end
                continue
        else:
            run_key = key
            run_count = 1

        out.append(Segment(start=seg.start, end=seg.end, text=text, language=seg.language))

    return out


# ------------------------------------------------------- paragraflandirma


def merge_paragraphs(
    segments: list[Segment],
    *,
    pause_break: float = 1.5,
    long_pause_break: float = 3.0,
    soft_max_seconds: float = 40.0,
    hard_max_seconds: float = 90.0,
) -> list[Paragraph]:
    """Segmentleri okunabilir paragraflara topla.

    Kural sirasi onemli: once cumle sonuna denk gelen dogal kesimleri tercih
    ediyoruz, sadece paragraf asiri uzadiginda cumle ortasinda kesiyoruz.
    """
    paragraphs: list[Paragraph] = []
    buf: list[str] = []
    start = 0.0
    end = 0.0

    def flush() -> None:
        nonlocal buf, start, end
        if not buf:
            return
        text = " ".join(buf).strip()
        text = _WS_RE.sub(" ", text)
        if text:
            paragraphs.append(Paragraph(start=start, end=end, text=text))
        buf = []

    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue

        if not buf:
            buf.append(text)
            start = seg.start
            end = seg.end
            continue

        gap = seg.start - end
        duration = end - start
        current = " ".join(buf)

        # Paragraf asiri uzadi: cumle ortasi bile olsa kes.
        too_long = duration >= hard_max_seconds
        # Uzun sessizlik yeni bir dusunce demek, noktalama beklemiyoruz.
        big_pause = gap >= long_pause_break
        # Tercih edilen kesim: cumle bitmis ve ya duraklama var ya da yeterince uzamis.
        natural = ends_sentence(current) and (
            gap >= pause_break or duration >= soft_max_seconds
        )

        if too_long or big_pause or natural:
            flush()
            start = seg.start

        buf.append(text)
        end = seg.end

    flush()
    return paragraphs


def build_paragraphs(segments: list[Segment]) -> list[Paragraph]:
    """Halusinasyon filtresi + paragraflandirma, tek cagri."""
    return merge_paragraphs(filter_hallucinations(segments))


def total_words(paragraphs: list[Paragraph]) -> int:
    return sum(len(p.text.split()) for p in paragraphs)
