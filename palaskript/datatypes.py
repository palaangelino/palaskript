"""Moduller arasi paylasilan veri tipleri.

Tek yerde tutuluyor cunku bu tipler kaynak cozumleme, transkripsiyon, ara kayit ve
disa aktarim katmanlarinin hepsinden geciyor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

SourceKind = Literal["youtube", "file"]


@dataclass(slots=True)
class Segment:
    """Whisper'dan gelen ham segment. Tipik olarak 5-10 saniyelik parcalar."""

    start: float
    end: float
    text: str
    language: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Segment:
        return cls(
            start=float(d["start"]),
            end=float(d["end"]),
            text=str(d["text"]),
            language=d.get("language"),
        )


@dataclass(slots=True)
class Paragraph:
    """Birlestirilmis okunabilir paragraf. PDF govdesinin yapi tasi."""

    start: float
    end: float
    text: str


@dataclass(slots=True)
class Chapter:
    """YouTube bolum isareti veya zamana gore uretilmis yedek baslik."""

    start: float
    end: float
    title: str
    #ChapterSource: video kendi bolumlerini tasiyorsa "youtube", yoksa "auto"
    origin: Literal["youtube", "auto"] = "youtube"


@dataclass(slots=True)
class SourceInfo:
    """Bir isin kaynagi hakkinda bilinen her sey.

    PDF kapagi ve icindekiler bu nesneden uretiliyor, bu yuzden meta veri
    transkriptin yaninda tasiniyor.
    """

    kind: SourceKind
    source_id: str
    title: str
    duration: float
    url: str | None = None
    channel: str | None = None
    upload_date: str | None = None
    chapters: list[Chapter] = field(default_factory=list)
    manual_sub_langs: list[str] = field(default_factory=list)
    auto_sub_langs: list[str] = field(default_factory=list)
    thumbnail_url: str | None = None
    audio_path: Path | None = None

    @property
    def has_manual_subs(self) -> bool:
        return bool(self.manual_sub_langs)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["audio_path"] = str(self.audio_path) if self.audio_path else None
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SourceInfo:
        chapters = [Chapter(**c) for c in d.get("chapters", [])]
        audio = d.get("audio_path")
        return cls(
            kind=d["kind"],
            source_id=d["source_id"],
            title=d["title"],
            duration=float(d["duration"]),
            url=d.get("url"),
            channel=d.get("channel"),
            upload_date=d.get("upload_date"),
            chapters=chapters,
            manual_sub_langs=list(d.get("manual_sub_langs", [])),
            auto_sub_langs=list(d.get("auto_sub_langs", [])),
            thumbnail_url=d.get("thumbnail_url"),
            audio_path=Path(audio) if audio else None,
        )


@dataclass(slots=True)
class TranscriptDoc:
    """Disa aktarima hazir tamamlanmis transkript."""

    source: SourceInfo
    paragraphs: list[Paragraph]
    chapters: list[Chapter]
    languages: list[str]
    model_name: str
    created_at: datetime
    from_subtitles: bool = False

    @property
    def word_count(self) -> int:
        return sum(len(p.text.split()) for p in self.paragraphs)
