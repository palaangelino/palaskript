"""Tek bir isin ucdan uca boru hatti.

Sira: kaynak coz -> (hazir altyazi varsa onu kullan) -> sesi indir -> modeli
hazirla -> pencere pencere yaz -> paragraflandir -> bolumle -> PDF/TXT yaz.

Bu modul arayuz bilmiyor. Ilerlemeyi geri cagri ile bildiriyor, iptali disaridan
verilen bir kontrol fonksiyonuyla sorguluyor. Boylece hem komut satirindan hem
de arayuzun isci surecinden ayni sekilde calisiyor.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import catalog, paths, stages
from . import chapters as chapters_mod
from . import segments as seg_mod
from .audio import AudioDecodeError, export_archive_audio, iter_windows, probe_duration
from .checkpoint import Checkpoint
from .config import Settings
from .datatypes import SourceInfo, TranscriptDoc
from .engine.base import EngineError
from .export import pdf as pdf_export
from .export import txt as txt_export
from .resources import (
    HardwareInfo,
    MemoryGuard,
    Profile,
    check_disk_for_model,
    choose_profile,
    detect,
)
from .source import file_source, ytdlp_source

Stage = str


@dataclass(slots=True)
class Progress:
    stage: Stage
    fraction: float
    message: str
    eta_seconds: float | None = None


ProgressCallback = Callable[[Progress], None]
CancelCheck = Callable[[], bool]


class JobCancelled(RuntimeError):
    pass


@dataclass(slots=True)
class JobResult:
    doc: TranscriptDoc
    pdf_path: Path | None = None
    txt_path: Path | None = None
    audio_path: Path | None = None
    from_subtitles: bool = False
    elapsed_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)
    # Kalibrasyon icin: bu isin transkripsiyon asamasinin olcumleri.
    # Indirme ve disa aktarim haric, yalnizca yazma suresi.
    stats: dict = field(default_factory=dict)


# Pencere ici canli ilerleme bildirimleri arasindaki en kisa sure.
_LIVE_PROGRESS_SECONDS = 2.0

# Kalan sure tahmini icin gereken en az olcum: bu kadar sure gecmeden ve
# bu kadar ses yazilmadan tahmin gosterilmiyor.
_ETA_MIN_SECONDS = 25.0
_ETA_MIN_AUDIO_SECONDS = 45.0

# Asama agirliklari palaskript/stages.py icinde: arayuz de ayni sayilari
# kullaniyor (iki bildirim arasini doldururken).


def _safe_filename(name: str, fallback: str = "transkript") -> str:
    """Windows dosya adi icin temizle."""
    bad = '<>:"/\\|?*'
    cleaned = "".join("-" if c in bad else c for c in name)
    cleaned = " ".join(cleaned.split()).strip(" .")
    cleaned = cleaned[:120].strip()
    return cleaned or fallback


def run_job(
    source: SourceInfo,
    settings: Settings,
    *,
    job_id: str,
    progress: ProgressCallback | None = None,
    cancel: CancelCheck | None = None,
    use_subtitles: bool = False,
    hardware: HardwareInfo | None = None,
    resume: bool = True,
) -> JobResult:
    """Bir isi bastan sona calistir."""
    started = time.monotonic()
    warnings: list[str] = []

    def report(stage: Stage, local: float, message: str, eta: float | None = None) -> None:
        if progress:
            progress(Progress(stage, stages.overall(stage, local), message, eta))

    def check_cancel() -> None:
        if cancel and cancel():
            raise JobCancelled("İş iptal edildi.")

    paths.ensure_dirs()
    hw = hardware or detect()
    check_cancel()

    # ------------------------------------------------------------ 1. kaynak
    report("probe", 0.0, "Kaynak inceleniyor")
    if source.kind == "youtube":
        source = ytdlp_source.probe_full(source.url or "", cookie_browser=settings.cookie_browser)
    report("probe", 1.0, source.title)
    check_cancel()

    work_dir = paths.cache_dir() / job_id
    work_dir.mkdir(parents=True, exist_ok=True)

    doc_segments = []
    from_subtitles = False
    model_label = ""
    languages: list[str] = []
    duration = source.duration
    measured_stats: dict = {}

    # -------------------------------------------- 2. hazir altyazi kisayolu
    if use_subtitles and source.kind == "youtube":
        report("subtitles", 0.1, "Hazır altyazı indiriliyor")
        fetched = ytdlp_source.fetch_manual_subtitles(
            source, work_dir, cookie_browser=settings.cookie_browser
        )
        if fetched:
            doc_segments, lang = fetched
            languages = [lang]
            from_subtitles = True
            model_label = f"YouTube altyazısı ({lang})"
            report("subtitles", 1.0, f"Altyazı alındı ({len(doc_segments)} satır)")
        else:
            warnings.append("Hazır altyazı bulunamadı, ses yeniden yazıldı.")

    # --------------------------------------------------- 3. transkripsiyon
    if not from_subtitles:
        audio_path = source.audio_path

        if source.kind == "youtube":
            report("download", 0.0, "Ses indiriliyor")
            audio_path = ytdlp_source.download_audio(
                source,
                work_dir,
                progress=lambda f, m: report("download", f, m),
                cookie_browser=settings.cookie_browser,
            )
            source.audio_path = audio_path
        check_cancel()

        if audio_path is None or not Path(audio_path).exists():
            raise FileNotFoundError("İşlenecek ses dosyası bulunamadı.")

        try:
            duration = probe_duration(audio_path)
        except Exception:  # noqa: BLE001 - meta veriden gelen sure yeterli
            duration = source.duration

        # Model
        profile = choose_profile(
            hw,
            model_override=None if settings.model == "auto" else settings.model,
            threads_override=settings.cpu_threads,
            low_memory_mode=settings.low_memory_mode,
        )
        report("model", 0.0, f"Profil: {profile.describe()}")
        check_disk_for_model(profile.model, hw)
        model_dir = catalog.ensure_model(
            profile.model, progress=lambda f, m: report("model", f, m)
        )
        check_cancel()

        stats: dict = {"model": profile.model, "batch_size": profile.batch_size}
        report("model", 0.85, "Model belleğe yükleniyor")
        doc_segments, languages = _transcribe(
            stats=stats,
            audio_path=Path(audio_path),
            model_dir=model_dir,
            profile=profile,
            settings=settings,
            duration=duration,
            job_id=job_id,
            report=report,
            check_cancel=check_cancel,
            resume=resume,
            warnings=warnings,
        )
        model_label = f"faster-whisper {profile.model} (int8, CPU)"
        measured_stats = stats

    # ------------------------------------------------------- 4. belgelestir
    report("export", 0.0, "Belge hazırlanıyor")
    paragraphs = seg_mod.build_paragraphs(doc_segments)
    doc_chapters = chapters_mod.build_chapters(
        source,
        duration=duration or source.duration,
        auto_interval_minutes=settings.auto_chapter_minutes,
        enabled=settings.use_chapters,
    )

    doc = TranscriptDoc(
        source=source,
        paragraphs=paragraphs,
        chapters=doc_chapters,
        languages=languages,
        model_name=model_label,
        created_at=datetime.now(),
        from_subtitles=from_subtitles,
    )

    # ------------------------------------------------------- 5. disa aktar
    out_dir = settings.output_path
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_filename(source.title)

    result = JobResult(
        doc=doc,
        from_subtitles=from_subtitles,
        elapsed_seconds=time.monotonic() - started,
        warnings=warnings,
        stats=measured_stats,
    )

    if settings.export_pdf:
        report("export", 0.3, "PDF yazılıyor")
        result.pdf_path = pdf_export.write(doc, out_dir / f"{stem}.pdf", settings)
    if settings.export_txt:
        report("export", 0.7, "Metin dosyası yazılıyor")
        result.txt_path = txt_export.write(doc, out_dir / f"{stem}.txt", settings)

    # ------------------------------------------------------- 6. temizlik
    # Ses saklanacaksa arsivlik formata cevrilip cikti klasorune yaziliyor.
    # Indirilen ham dosya 3.5 saatlik video icin ~150 MB; Opus 24 kbps mono
    # ayni konusmayi ~38 MB'a indiriyor ve konusma icin tasarlanmis bir codec.
    if settings.keep_audio and source.kind == "youtube" and source.audio_path:
        report("export", 0.85, "Ses arşivleniyor")
        try:
            result.audio_path = export_archive_audio(
                Path(source.audio_path), out_dir / f"{stem}.opus"
            )
        except AudioDecodeError as exc:
            # Arsivleme basarisiz olursa ham dosyayi tasi: kaybetmekten iyi.
            warnings.append(f"Ses arşivlenemedi, ham dosya saklandı: {exc}")
            fallback = out_dir / f"{stem}{Path(source.audio_path).suffix}"
            try:
                shutil.move(str(source.audio_path), fallback)
                result.audio_path = fallback
            except OSError:
                result.audio_path = Path(source.audio_path)

    # Calisma dizini her durumda gidiyor: indirilen ses, altyazi dosyalari ve
    # yarim kalmis parcalar burada birikirse gigabaytlari yiyor.
    if result.audio_path is None or result.audio_path.parent != work_dir:
        shutil.rmtree(work_dir, ignore_errors=True)

    Checkpoint(job_id).clear()
    result.elapsed_seconds = time.monotonic() - started
    report("export", 1.0, "Tamamlandı")
    return result


def _transcribe(
    *,
    stats: dict,
    audio_path: Path,
    model_dir: Path,
    profile: Profile,
    settings: Settings,
    duration: float,
    job_id: str,
    report: Callable[..., None],
    check_cancel: Callable[[], None],
    resume: bool,
    warnings: list[str],
) -> tuple[list, list[str]]:
    """Pencereli transkripsiyon dongusu.

    Her pencere sonunda ara kayit isaretleniyor; cokme sonrasi is o noktadan
    devam ediyor.
    """
    from .engine.local import LocalWhisperEngine

    language = None if settings.language == "auto" else settings.language
    checkpoint = Checkpoint(job_id)

    prior_segments = []
    start_at = 0.0
    if resume and checkpoint.exists():
        prior_segments, start_at, _ = checkpoint.load()
        if start_at > 0:
            report(
                "transcribe",
                start_at / duration if duration else 0.0,
                f"Kaldığı yerden devam ediliyor ({chapters_mod.format_timestamp(start_at)})",
            )

    assembler = seg_mod.TranscriptAssembler()
    assembler.segments.extend(prior_segments)

    guard = MemoryGuard(profile)
    engine = LocalWhisperEngine(model_dir, profile, language=language)

    processed = start_at
    wall_start = time.monotonic()

    try:
        with checkpoint as ck:
            ck.write_meta(
                job_id=job_id,
                model=profile.model,
                audio=str(audio_path),
                duration=duration,
            )

            # ETA olcumunun baslangic noktasi. Dongunun basi DEGIL, ILK
            # segmentin geldigi an: motor ilk segmenti vermeden once tum
            # pencereye VAD uyguluyor ve ilk yigini kodluyor. Bu tek seferlik
            # is ortalamaya karistirilirsa hiz olduğundan cok dusuk gorunuyor
            # ve 8 dakikalik bir video icin "31 dakika kaldi" yaziyor.
            anchor: dict[str, float] = {}

            def announce(position: float) -> None:
                """Ilerlemeyi ve kalan sureyi bildir."""
                live = min(position, duration) if duration else position
                now = time.monotonic()

                if not anchor and live > start_at:
                    anchor["time"] = now
                    anchor["position"] = live

                eta = None
                if anchor:
                    span = now - anchor["time"]
                    covered = live - anchor["position"]
                    # Yeterli ornek toplanana kadar tahmin gostermiyoruz.
                    # Yanlis bir sure, sure gostermemekten kotu.
                    if span >= _ETA_MIN_SECONDS and covered >= _ETA_MIN_AUDIO_SECONDS:
                        rate = covered / span
                        if rate > 0 and duration:
                            eta = (duration - live) / rate

                report(
                    "transcribe",
                    live / duration if duration else 0.0,
                    f"Yazılıyor {chapters_mod.format_timestamp(live)} / "
                    f"{chapters_mod.format_timestamp(duration)}",
                    eta,
                )

            # Pencere ici canli ilerleme. Bir pencere 10 dakikalik ses tasiyor;
            # sadece pencere sonunda bildirseydik 3.5 saatlik bir iste ilerleme
            # cubugu 9 dakikada bir hareket ederdi. Iki saniyede birden sik
            # bildirmiyoruz, aksi halde surecler arasi kuyruk gereksiz doluyor.
            last_live = 0.0

            def on_segment(seg) -> None:  # noqa: ANN001 - Segment
                nonlocal last_live
                now = time.monotonic()
                if now - last_live < _LIVE_PROGRESS_SECONDS:
                    return
                last_live = now
                announce(seg.end)

            for window in iter_windows(
                audio_path,
                profile.window_seconds,
                start_at=start_at,
            ):
                check_cancel()

                batch_size, note = guard.check()
                if note:
                    warnings.append(note)
                    report("transcribe", processed / duration if duration else 0.0, note)

                try:
                    produced = engine.transcribe_window(
                        window.samples,
                        offset=window.start,
                        batch_size=batch_size,
                        on_segment=on_segment,
                    )
                except EngineError as exc:
                    # Tek pencerenin patlamasi 3 saatlik isi cope atmasin.
                    warnings.append(
                        f"{chapters_mod.format_timestamp(window.start)} civarı atlandı: {exc}"
                    )
                    produced = []

                accepted = assembler.add_window(produced, overlapped=window.overlapped)
                ck.write_segments(accepted)
                ck.commit_window(window.index, window.end)

                processed = window.end
                announce(processed)
    finally:
        engine.close()

    # Kalibrasyon icin: yalnizca YAZILAN ses ve o ise harcanan sure. Devam
    # ettirilen bir iste bastaki kisim tekrar yazilmadigi icin start_at
    # dusuluyor, aksi halde hiz oldugundan yuksek gorunurdu.
    stats["audio_seconds"] = max(0.0, processed - start_at)
    stats["elapsed_seconds"] = time.monotonic() - wall_start

    return assembler.result(), engine.detected_languages


def probe_source(raw: str, settings: Settings) -> SourceInfo:
    """Tek girdiyi cozup SourceInfo dondur (komut satiri icin kisayol)."""
    if ytdlp_source.is_url(raw):
        return ytdlp_source.probe_full(raw, cookie_browser=settings.cookie_browser)
    return file_source.probe(Path(raw))
