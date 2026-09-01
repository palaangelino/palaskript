"""Yerel video/ses dosyasi kaynagi.

Yerel dosyalarda indirme adimi yok: PyAV dogrudan dosyadan pencereli okuyor,
gecici WAV yazilmiyor.
"""

from __future__ import annotations

from pathlib import Path

from ..audio import AudioDecodeError, probe_duration
from ..datatypes import SourceInfo

# PyAV'in cozebildigi yaygin konteynerler. Liste kapili degil, sadece dosya
# secme diyalogunun filtresi ve erken uyari icin.
MEDIA_SUFFIXES = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".mpg", ".mpeg",
    ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".wma",
}


def is_media_file(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_SUFFIXES


def source_id_for(path: Path) -> str:
    """Kuyrukta tekillestirme anahtari.

    Mutlak yolu kucuk harfe cevirip kullaniyoruz: Windows'ta yollar buyuk/kucuk
    harf duyarsiz, ayni dosya iki farkli yazimla iki kez kuyruga girmesin.
    """
    return "file:" + str(path.resolve()).lower()


def probe(path: Path) -> SourceInfo:
    """Yerel dosyayi okuyup SourceInfo uret."""
    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Dosya bulunamadi: {resolved}")
    if not resolved.is_file():
        raise ValueError(f"Bu bir dosya degil: {resolved}")

    try:
        duration = probe_duration(resolved)
    except AudioDecodeError as exc:
        raise ValueError(
            f"{resolved.name} icinde okunabilir ses bulunamadi. "
            "Dosya bozuk olabilir veya ses akisi tasimayabilir."
        ) from exc

    return SourceInfo(
        kind="file",
        source_id=source_id_for(resolved),
        title=resolved.stem,
        duration=duration,
        url=None,
        channel=None,
        upload_date=None,
        audio_path=resolved,
    )
