"""Girdi cozumleme: yapistirilan metni kuyruga eklenebilir kaynaklara cevirir.

Kullanici tek bir kutuya link ve dosya yolu karisik yapistirabiliyor. Burasi
hangisinin ne oldugunu ayirip, playlist'leri acip, tekrarlari eleyen yer.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..datatypes import SourceInfo
from . import file_source, ytdlp_source


class ResolveError(RuntimeError):
    """Tek bir girdi cozumlenemedi. Digerleri islenmeye devam eder."""

    def __init__(self, raw: str, message: str) -> None:
        super().__init__(message)
        self.raw = raw
        self.message = message


def parse_input_lines(text: str) -> list[str]:
    """Cok satirli yapistirmayi tek tek girdilere ayir.

    Bosluk yerine satir sonu ile ayiriyoruz: dosya yollarinda bosluk olabiliyor.
    """
    items: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        candidate = line.strip().strip('"')
        if candidate:
            items.append(candidate)
    return items


def is_url(text: str) -> bool:
    return ytdlp_source.is_url(text)


def resolve_one(raw: str, *, cookie_browser: str = "none") -> list[SourceInfo]:
    """Tek girdiyi coz. Playlist ise birden fazla kayit doner."""
    candidate = raw.strip().strip('"')
    if not candidate:
        return []

    if is_url(candidate):
        return ytdlp_source.probe_flat(candidate, cookie_browser=cookie_browser)

    path = Path(candidate)
    if not path.exists():
        raise ResolveError(
            raw,
            f"Ne geçerli bir adres ne de var olan bir dosya: {candidate}",
        )
    if path.is_dir():
        found = [p for p in sorted(path.iterdir()) if p.is_file() and file_source.is_media_file(p)]
        if not found:
            raise ResolveError(raw, f"Klasörde medya dosyası yok: {candidate}")
        return [file_source.probe(p) for p in found]

    return [file_source.probe(path)]


def resolve_many(
    items: Iterable[str],
    *,
    cookie_browser: str = "none",
    known_ids: set[str] | None = None,
) -> tuple[list[SourceInfo], list[ResolveError]]:
    """Girdileri coz, tekrarlari ele, hatalari toplayip devam et.

    Bir linkin bozuk olmasi digerlerinin eklenmesini engellememeli: kullanici
    yirmi link yapistirdiginda on dokuzu calisiyorsa on dokuzu kuyruga girsin.
    """
    seen: set[str] = set(known_ids or set())
    resolved: list[SourceInfo] = []
    errors: list[ResolveError] = []

    for raw in items:
        try:
            for info in resolve_one(raw, cookie_browser=cookie_browser):
                if info.source_id in seen:
                    continue
                seen.add(info.source_id)
                resolved.append(info)
        except ResolveError as exc:
            errors.append(exc)
        except Exception as exc:  # noqa: BLE001 - yt-dlp cesitli hatalar firlatiyor
            errors.append(ResolveError(raw, str(exc)))

    return resolved, errors
