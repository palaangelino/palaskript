"""Duz metin disa aktarimi.

PDF'in yanina her zaman bir TXT yaziyoruz: arama, kopyalama ve baska bir araca
beslemek icin en pratik format.
"""

from __future__ import annotations

from pathlib import Path

from ..chapters import assign_paragraphs, format_timestamp
from ..config import Settings
from ..datatypes import TranscriptDoc

_RULE = "-" * 72


def _header(doc: TranscriptDoc) -> list[str]:
    src = doc.source
    lines = [_RULE, src.title, _RULE]
    if src.channel:
        lines.append(f"Kanal      : {src.channel}")
    if src.url:
        lines.append(f"Kaynak     : {src.url}")
    if src.upload_date and len(src.upload_date) == 8:
        d = src.upload_date
        lines.append(f"Yayin      : {d[6:8]}.{d[4:6]}.{d[0:4]}")
    lines.append(f"Sure       : {format_timestamp(src.duration, always_hours=True)}")
    lines.append(f"Uretim     : {doc.created_at.strftime('%d.%m.%Y %H:%M')}")
    lines.append(f"Kaynak tur : {doc.model_name}")
    if doc.languages:
        lines.append(f"Dil        : {', '.join(doc.languages)}")
    lines.append(f"Kelime     : {doc.word_count}")
    lines.append(_RULE)
    lines.append("")
    return lines


def render(doc: TranscriptDoc, settings: Settings) -> str:
    lines = _header(doc)
    groups = assign_paragraphs(doc.paragraphs, doc.chapters)

    interval = max(1, settings.timestamp_interval_minutes) * 60
    next_stamp = 0.0

    for chapter, paragraphs in groups:
        if chapter is not None:
            lines.append("")
            lines.append(f"[{format_timestamp(chapter.start, always_hours=True)}] {chapter.title}")
            lines.append("")
            next_stamp = chapter.start + interval

        for para in paragraphs:
            prefix = ""
            if settings.timestamp_mode == "paragraph":
                prefix = f"[{format_timestamp(para.start, always_hours=True)}] "
            elif settings.timestamp_mode == "interval" and para.start >= next_stamp:
                prefix = f"[{format_timestamp(para.start, always_hours=True)}] "
                next_stamp = para.start + interval
            lines.append(prefix + para.text)
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write(doc: TranscriptDoc, path: Path, settings: Settings) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(doc, settings), encoding="utf-8")
    return path
