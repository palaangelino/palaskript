"""WebVTT ve SRT ayristirici.

Video insan eliyle yazilmis altyazi tasiyorsa onu kullanmak 3 saatlik
transkripsiyonu 2 saniyeye indiriyor. Bu modul o altyaziyi bizim Segment
tipimize ceviriyor, boylece geri kalan boru hatti (paragraflandirma, bolumleme,
PDF) hicbir sey degismeden calisiyor.

Otomatik uretilmis altyazilar bilerek tercih edilmiyor: Turkcede noktalama ve
buyuk harf tasimadiklari icin okunabilir bir belge cikmiyor.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..datatypes import Segment

_TIME = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
_CUE_RE = re.compile(rf"({_TIME})\s*-->\s*({_TIME})")

# VTT satir ici bicimlendirme etiketleri ve konumlandirma ipuclari.
_TAG_RE = re.compile(r"<[^>]+>")
_CUE_SETTINGS_RE = re.compile(r"\s+(align|position|size|line|vertical):\S+")

# Altyazi dosyalarinin basindaki ceviri/redaksiyon kunyesi. TED konusmalarinda
# neredeyse her zaman var ve konusmanin bir parcasi degil; birakilirsa belgenin
# ilk paragrafi "Transcriber: ... Reviewer: ..." olarak aciliyor.
_CREDIT_RE = re.compile(
    r"^\s*(transcriber|reviewer|translator|translated by|reviewed by|subtitles? by|"
    r"captions? by|çeviri|çeviren|gözden geçirme|gözden geçiren|altyazı)\s*[:：]",
    re.IGNORECASE,
)

# Kunye sadece bastaki bu kadar cue icinde araniyor. Konusmanin ortasinda
# "Çeviri:" diye baslayan gercek bir cumle olabilir, onu silmek istemiyoruz.
_CREDIT_SCAN_CUES = 2


def _to_seconds(hours: str | None, minutes: str, seconds: str, millis: str) -> float:
    h = int(hours) if hours else 0
    ms = int(millis.ljust(3, "0"))
    return h * 3600 + int(minutes) * 60 + int(seconds) + ms / 1000.0


def parse(text: str) -> list[Segment]:
    """VTT veya SRT metnini segmentlere cevir."""
    segments: list[Segment] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    i = 0
    while i < len(lines):
        match = _CUE_RE.search(lines[i])
        if not match:
            i += 1
            continue

        start = _to_seconds(match.group(2), match.group(3), match.group(4), match.group(5))
        end = _to_seconds(match.group(7), match.group(8), match.group(9), match.group(10))

        i += 1
        body: list[str] = []
        while i < len(lines) and lines[i].strip():
            if _CUE_RE.search(lines[i]):
                break
            body.append(lines[i])
            i += 1

        cleaned = _clean(" ".join(body))
        if cleaned and end > start:
            segments.append(Segment(start=start, end=end, text=cleaned))
        i += 1

    return _dedupe(_drop_credits(segments))


def _drop_credits(segments: list[Segment]) -> list[Segment]:
    """Bastaki ceviri kunyesini at."""
    kept: list[Segment] = []
    for index, seg in enumerate(segments):
        if index < _CREDIT_SCAN_CUES and _CREDIT_RE.match(seg.text):
            continue
        kept.append(seg)
    return kept


def _clean(raw: str) -> str:
    text = _TAG_RE.sub("", raw)
    text = _CUE_SETTINGS_RE.sub("", text)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'")
    return " ".join(text.split()).strip()


def _dedupe(segments: list[Segment]) -> list[Segment]:
    """Ust uste binen tekrarli satirlari at.

    YouTube altyazilarinda ayni cumle kayan pencere seklinde birkac cue boyunca
    tekrarlanabiliyor. Aynen birakilirsa PDF'te her cumle iki kez cikiyor.
    """
    out: list[Segment] = []
    for seg in segments:
        if out and seg.text == out[-1].text:
            out[-1].end = max(out[-1].end, seg.end)
            continue
        if out and seg.text.startswith(out[-1].text) and len(out[-1].text) > 10:
            out[-1].text = seg.text
            out[-1].end = max(out[-1].end, seg.end)
            continue
        out.append(seg)
    return out


def parse_file(path: Path) -> list[Segment]:
    return parse(path.read_text(encoding="utf-8", errors="replace"))
