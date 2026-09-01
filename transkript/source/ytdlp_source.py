"""yt-dlp sarmalayicisi: meta veri, bolumler, ses indirme, hazir altyazi.

Kutuphane olarak kullaniliyor (subprocess degil), boylece ilerleme kancalari ve
hata tipleri dogrudan elimize geliyor.

Sadece SES akisi iniyor. 3.5 saatlik bir video icin bu ~100-200 MB; tam videoyu
indirmek birkac GB olurdu ve isimize yaramayan piksellere harcanirdi.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..datatypes import Chapter, Segment, SourceInfo
from . import subtitles as subs_parser

ProgressCallback = Callable[[float, str], None]

_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Insan eliyle yazilmis altyazi ararken bu dillere bakiyoruz, bu sirayla.
PREFERRED_SUB_LANGS = ("tr", "en")


class YtDlpError(RuntimeError):
    pass


def _import_ytdlp():
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - kurulum hatasi
        raise YtDlpError("yt-dlp kurulu degil.") from exc
    return yt_dlp


def is_url(text: str) -> bool:
    return text.strip().lower().startswith(("http://", "https://", "www."))


def normalize_url(text: str) -> str:
    t = text.strip()
    if t.lower().startswith("www."):
        return "https://" + t
    return t


def _base_opts(cookie_browser: str = "none") -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": False,
        # Windows'ta uzun/gecersiz karakterli basliklar dosya adini bozuyor.
        "windowsfilenames": True,
    }
    if cookie_browser and cookie_browser != "none":
        opts["cookiesfrombrowser"] = (cookie_browser,)
    return opts


def _wrap_error(exc: Exception, url: str) -> YtDlpError:
    text = str(exc)
    lowered = text.lower()
    if "sign in" in lowered or "age" in lowered or "private" in lowered:
        return YtDlpError(
            "Bu video giris gerektiriyor (yas kisitli veya ozel olabilir). "
            "Ayarlardan tarayici cerezi secip tekrar deneyin."
        )
    if "unavailable" in lowered or "removed" in lowered:
        return YtDlpError("Video kaldirilmis veya bu bolgede erisilebilir degil.")
    if "unsupported url" in lowered:
        return YtDlpError(f"Bu adres desteklenmiyor: {url}")
    return YtDlpError(f"Video bilgisi alinamadi: {text}")


def _webpage_url(entry: dict[str, Any]) -> str:
    for key in ("webpage_url", "original_url", "url"):
        value = entry.get(key)
        if value and str(value).startswith("http"):
            return str(value)
    vid = entry.get("id")
    if vid and _YOUTUBE_ID_RE.match(str(vid)):
        return f"https://www.youtube.com/watch?v={vid}"
    return str(entry.get("url") or "")


def _source_id(entry: dict[str, Any]) -> str:
    extractor = (entry.get("extractor_key") or entry.get("ie_key") or "url").lower()
    vid = entry.get("id") or _webpage_url(entry)
    return f"{extractor}:{vid}"


def _chapters_from(info: dict[str, Any], duration: float) -> list[Chapter]:
    raw = info.get("chapters") or []
    chapters: list[Chapter] = []
    for item in raw:
        start = item.get("start_time")
        if start is None:
            continue
        end = item.get("end_time")
        title = (item.get("title") or "").strip()
        chapters.append(
            Chapter(
                start=float(start),
                end=float(end) if end is not None else duration,
                title=title or f"Bolum {len(chapters) + 1}",
                origin="youtube",
            )
        )
    return chapters


def probe_flat(url: str, cookie_browser: str = "none") -> list[SourceInfo]:
    """Kuyruga hizli ekleme icin yuzeysel bilgi.

    Playlist ise N ayri kayit doner. Bolum ve altyazi bilgisi burada CEKILMIYOR:
    her video icin ayri bir ag istegi gerektirir ve kuyruga eklemeyi yavaslatir.
    Bu detaylar is basladiginda probe_full ile aliniyor.
    """
    yt_dlp = _import_ytdlp()
    url = normalize_url(url)
    opts = _base_opts(cookie_browser) | {"extract_flat": "in_playlist", "skip_download": True}

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001 - yt-dlp genis hata yelpazesi firlatiyor
        raise _wrap_error(exc, url) from exc

    if info is None:
        raise YtDlpError(f"Video bilgisi alinamadi: {url}")

    entries = info.get("entries") if info.get("_type") == "playlist" else None
    items = list(entries) if entries else [info]

    results: list[SourceInfo] = []
    for entry in items:
        if not entry:
            continue
        duration = float(entry.get("duration") or 0.0)
        results.append(
            SourceInfo(
                kind="youtube",
                source_id=_source_id(entry),
                title=(entry.get("title") or "Basliksiz").strip(),
                duration=duration,
                url=_webpage_url(entry),
                channel=entry.get("uploader") or entry.get("channel"),
                upload_date=entry.get("upload_date"),
                thumbnail_url=entry.get("thumbnail"),
            )
        )
    if not results:
        raise YtDlpError(f"Bu adreste video bulunamadi: {url}")
    return results


def probe_full(url: str, cookie_browser: str = "none") -> SourceInfo:
    """Bolumler ve altyazi durumu dahil tam meta veri. Is baslarken cagriliyor."""
    yt_dlp = _import_ytdlp()
    url = normalize_url(url)
    opts = _base_opts(cookie_browser) | {"skip_download": True, "noplaylist": True}

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001
        raise _wrap_error(exc, url) from exc

    if info is None:
        raise YtDlpError(f"Video bilgisi alinamadi: {url}")
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise YtDlpError(f"Bu adreste video bulunamadi: {url}")
        info = entries[0]

    duration = float(info.get("duration") or 0.0)
    manual = sorted((info.get("subtitles") or {}).keys())
    auto = sorted((info.get("automatic_captions") or {}).keys())

    return SourceInfo(
        kind="youtube",
        source_id=_source_id(info),
        title=(info.get("title") or "Basliksiz").strip(),
        duration=duration,
        url=_webpage_url(info),
        channel=info.get("uploader") or info.get("channel"),
        upload_date=info.get("upload_date"),
        chapters=_chapters_from(info, duration),
        manual_sub_langs=manual,
        auto_sub_langs=auto,
        thumbnail_url=info.get("thumbnail"),
    )


def download_audio(
    source: SourceInfo,
    dest_dir: Path,
    *,
    progress: ProgressCallback | None = None,
    cookie_browser: str = "none",
) -> Path:
    """Sadece ses akisini indir ve dosya yolunu dondur."""
    if not source.url:
        raise YtDlpError("Kaynak adresi yok.")

    yt_dlp = _import_ytdlp()
    dest_dir.mkdir(parents=True, exist_ok=True)

    def hook(status: dict[str, Any]) -> None:
        if not progress:
            return
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            got = status.get("downloaded_bytes") or 0
            frac = (got / total) if total else 0.0
            mb = got / 1024**2
            total_mb = total / 1024**2 if total else 0
            label = f"Ses indiriliyor: {mb:.0f} MB"
            if total_mb:
                label += f" / {total_mb:.0f} MB"
            progress(min(frac, 0.99), label)
        elif status.get("status") == "finished":
            progress(1.0, "Ses indirildi")

    opts = _base_opts(cookie_browser) | {
        "format": "bestaudio/best",
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "progress_hooks": [hook],
        "retries": 10,
        "fragment_retries": 10,
        "continuedl": True,
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(source.url, download=True)
    except Exception as exc:  # noqa: BLE001
        raise _wrap_error(exc, source.url) from exc

    if info is None:
        raise YtDlpError("Ses indirilemedi.")

    requested = info.get("requested_downloads") or []
    if requested and requested[0].get("filepath"):
        return Path(requested[0]["filepath"])

    # Yedek: id ile eslesen dosyayi bul.
    vid = info.get("id")
    if vid:
        matches = sorted(dest_dir.glob(f"{vid}.*"))
        if matches:
            return matches[0]

    raise YtDlpError("Indirilen ses dosyasi bulunamadi.")


def fetch_manual_subtitles(
    source: SourceInfo,
    dest_dir: Path,
    *,
    cookie_browser: str = "none",
    preferred: tuple[str, ...] = PREFERRED_SUB_LANGS,
) -> tuple[list[Segment], str] | None:
    """Insan eliyle yazilmis altyaziyi indirip segmentlere cevir.

    Bulunamazsa None doner. Otomatik altyazilar bilerek atlanıyor: Turkcede
    noktalama tasimadiklari icin okunabilir bir belge cikmiyor.
    """
    if not source.url or not source.manual_sub_langs:
        return None

    langs = [lang for lang in preferred if lang in source.manual_sub_langs]
    # Bolgesel varyantlar (tr-TR, en-US) da kabul.
    for lang in source.manual_sub_langs:
        base = lang.split("-")[0]
        if base in preferred and lang not in langs:
            langs.append(lang)
    if not langs:
        langs = [source.manual_sub_langs[0]]

    yt_dlp = _import_ytdlp()
    dest_dir.mkdir(parents=True, exist_ok=True)

    opts = _base_opts(cookie_browser) | {
        "skip_download": True,
        "noplaylist": True,
        "writesubtitles": True,
        "writeautomaticsub": False,
        "subtitleslangs": langs,
        "subtitlesformat": "vtt/srt/best",
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(source.url, download=True)
    except Exception as exc:  # noqa: BLE001
        raise _wrap_error(exc, source.url) from exc

    vid = (info or {}).get("id") or ""
    for lang in langs:
        for suffix in (".vtt", ".srt"):
            candidate = dest_dir / f"{vid}.{lang}{suffix}"
            if candidate.exists():
                segments = subs_parser.parse_file(candidate)
                if segments:
                    return segments, lang

    # Dil eki tahmin edilemediyse dizinde ara.
    for candidate in sorted(dest_dir.glob(f"{vid}*.vtt")) + sorted(dest_dir.glob(f"{vid}*.srt")):
        segments = subs_parser.parse_file(candidate)
        if segments:
            parts = candidate.name.split(".")
            lang = parts[-2] if len(parts) >= 3 else "?"
            return segments, lang

    return None
