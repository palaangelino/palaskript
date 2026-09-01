"""Kuyruk yurutucusu.

Arka planda tek bir is parcacigi donuyor, isleri sirayla aliyor ve her birini
ayri bir SUREC icinde calistiriyor (gerekcesi worker.py'de).

Isler sirayla isleniyor: hepsi CPU'ya bagli, paralel calistirmak toplam sureyi
kisaltmaz, sadece bellegi ikiye katlar. Buna karsilik SIRADAKI isin sesi,
mevcut is yazilirken indiriliyor: ag ve CPU farkli kaynaklar, bu kazanc bedava.
Kuyruk uzun birakildiginda indirme beklemesi tamamen ortadan kalkiyor.
"""

from __future__ import annotations

import contextlib
import logging
import multiprocessing as mp
import queue as queue_mod
import threading
from collections.abc import Callable
from pathlib import Path

from .. import paths
from ..config import Settings
from ..power import keep_awake
from ..source import ytdlp_source
from .db import Database, Job
from .worker import run_in_process

log = logging.getLogger(__name__)

ChangeCallback = Callable[[], None]
NotifyCallback = Callable[[str, str], None]

_POLL_INTERVAL = 0.2
_IDLE_INTERVAL = 1.0


class Orchestrator:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        *,
        on_change: ChangeCallback | None = None,
        on_notify: NotifyCallback | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.on_change = on_change
        self.on_notify = on_notify

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._paused = threading.Event()

        self._current_job_id: str | None = None
        self._cancel_event: object | None = None
        self._process: mp.process.BaseProcess | None = None
        self._lock = threading.Lock()

        self._prefetch_thread: threading.Thread | None = None
        self._prefetching: str | None = None

        self._ctx = mp.get_context("spawn")

    # ------------------------------------------------------------- yasam

    @property
    def current_job_id(self) -> str | None:
        return self._current_job_id

    @property
    def is_busy(self) -> bool:
        return self._current_job_id is not None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="orchestrator", daemon=True)
        self._thread.start()

    def stop(self, *, wait: bool = True, timeout: float = 10.0) -> None:
        self._stop.set()
        self.cancel_current()
        if wait and self._thread:
            self._thread.join(timeout=timeout)
        keep_awake.reset()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def update_settings(self, settings: Settings) -> None:
        self.settings = settings

    def cancel_current(self) -> None:
        with self._lock:
            event = self._cancel_event
            process = self._process
        if event is not None:
            event.set()
        if process is not None and process.is_alive():
            # Nazik iptal pencere sinirinda isliyor. Uzun bir cikarim
            # cagrisinin ortasindaysa surec kendiliginden durmaz, kesiyoruz.
            process.join(timeout=8.0)
            if process.is_alive():
                process.terminate()

    def cancel_job(self, job_id: str) -> None:
        if self._current_job_id == job_id:
            self.cancel_current()
        else:
            self.db.mark_cancelled(job_id)
            self._changed()

    # -------------------------------------------------------------- dongu

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001 - arayuz hatasi kuyrugu durdurmasin
                log.exception("on_change geri cagrisi hata verdi")

    def _notify(self, title: str, body: str) -> None:
        if self.on_notify:
            try:
                self.on_notify(title, body)
            except Exception:  # noqa: BLE001
                log.exception("on_notify geri cagrisi hata verdi")

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._paused.is_set():
                # Duraklatilmisken bilgisayarin uyumasini engellemeye gerek yok.
                if keep_awake.active:
                    keep_awake.reset()
                self._stop.wait(_IDLE_INTERVAL)
                continue

            job = self.db.next_pending()
            if job is None:
                if keep_awake.active:
                    keep_awake.reset()
                self._stop.wait(_IDLE_INTERVAL)
                continue

            if not keep_awake.active:
                keep_awake.acquire()

            try:
                self._process_job(job)
            except Exception as exc:  # noqa: BLE001 - tek is dongumuzu oldurmesin
                log.exception("Is islenirken beklenmeyen hata")
                self.db.mark_failed(job.id, str(exc))
                self._changed()

        keep_awake.reset()

    # ---------------------------------------------------------- tek is

    def _resolve_subtitle_decision(self, job: Job) -> bool | None:
        """Karar gerekiyorsa isi beklemeye alip None doner."""
        policy = self.settings.manual_subtitle_policy
        if job.use_subtitles is not None:
            return job.use_subtitles
        if job.kind != "youtube":
            return False
        if policy == "never":
            return False
        if policy == "always":
            return True

        # "ask": once videoda gercekten hazir altyazi var mi bakalim. Yoksa
        # kullaniciyi bosuna rahatsiz etmeyelim.
        try:
            info = ytdlp_source.probe_full(
                job.url or "", cookie_browser=self.settings.cookie_browser
            )
        except Exception as exc:  # noqa: BLE001
            self.db.mark_failed(job.id, str(exc))
            self._changed()
            return None

        if info.manual_sub_langs:
            self.db.mark_awaiting_decision(job.id, info.manual_sub_langs)
            self._changed()
            return None

        self.db.decide_subtitles(job.id, False)
        return False

    def _process_job(self, job: Job) -> None:
        use_subtitles = self._resolve_subtitle_decision(job)
        if use_subtitles is None:
            return

        self.db.mark_running(job.id)
        self._current_job_id = job.id
        self._changed()

        cancel_event = self._ctx.Event()
        progress_queue: mp.Queue = self._ctx.Queue()

        payload = {
            "job_id": job.id,
            "source": job.to_source_info().to_dict(),
            "settings": self.settings.to_dict(),
            "use_subtitles": use_subtitles,
        }

        process = self._ctx.Process(
            target=run_in_process,
            args=(payload, progress_queue, cancel_event),
            name=f"transkript-job-{job.id}",
            daemon=False,
        )

        with self._lock:
            self._cancel_event = cancel_event
            self._process = process

        process.start()
        self._start_prefetch(job.id)

        outcome: tuple[str, object] | None = None
        try:
            while True:
                try:
                    message = progress_queue.get(timeout=_POLL_INTERVAL)
                except queue_mod.Empty:
                    if not process.is_alive():
                        break
                    continue

                kind, data = message
                if kind == "progress":
                    assert isinstance(data, dict)
                    self.db.update_progress(
                        job.id,
                        stage=data.get("stage"),
                        progress=data.get("fraction"),
                        message=data.get("message"),
                        eta_seconds=data.get("eta"),
                    )
                    self._changed()
                else:
                    outcome = (kind, data)
                    break
        finally:
            process.join(timeout=15.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5.0)
            # Kuyrugu kapatmazsak besleyici is parcacigi is basina birikiyor.
            progress_queue.close()
            with contextlib.suppress(Exception):
                progress_queue.join_thread()
            with self._lock:
                self._cancel_event = None
                self._process = None
            self._current_job_id = None

        self._finish(job, outcome, cancelled=cancel_event.is_set())
        self._changed()

    def _finish(
        self,
        job: Job,
        outcome: tuple[str, object] | None,
        *,
        cancelled: bool,
    ) -> None:
        if outcome is None:
            if cancelled:
                self.db.mark_cancelled(job.id)
            else:
                # Surec mesaj birakmadan oldu: neredeyse her zaman bellek
                # yetersizligi veya yerel kutuphane cokmesi.
                self.db.mark_failed(
                    job.id,
                    "Islem beklenmedik sekilde sonlandi. Bellek yetersiz olabilir; "
                    "ayarlardan dusuk bellek modunu acip tekrar deneyin.",
                )
            return

        kind, data = outcome
        if kind == "cancelled":
            self.db.mark_cancelled(job.id)
        elif kind == "error":
            self.db.mark_failed(job.id, str(data))
        elif kind == "done":
            assert isinstance(data, dict)
            warnings = data.get("warnings") or []
            self.db.mark_done(
                job.id,
                pdf_path=data.get("pdf_path"),
                txt_path=data.get("txt_path"),
                audio_path=data.get("audio_path"),
                message="; ".join(warnings) if warnings else None,
            )
            self._notify("Transkript hazir", job.title)

    # ----------------------------------------------------------- on indirme

    def _start_prefetch(self, current_job_id: str) -> None:
        """Siradaki isin sesini simdiden indir.

        Indirilen dosya, o isin normalde kullanacagi calisma dizinine gidiyor.
        Is sirasi geldiginde yt-dlp dosyanin tam oldugunu gorup tekrar
        indirmiyor, yani ayrica bir haberlesmeye gerek kalmiyor.
        """
        if self._prefetch_thread and self._prefetch_thread.is_alive():
            return

        nxt = self.db.pending_after(current_job_id)
        if nxt is None or nxt.kind != "youtube" or not nxt.url:
            return
        # Altyazi kullanilacaksa ses indirmek bosa is olurdu.
        if nxt.use_subtitles or self.settings.manual_subtitle_policy == "always":
            return

        self._prefetching = nxt.id
        self._prefetch_thread = threading.Thread(
            target=self._prefetch, args=(nxt,), name="prefetch", daemon=True
        )
        self._prefetch_thread.start()

    def _prefetch(self, job: Job) -> None:
        try:
            work_dir = paths.cache_dir() / job.id
            work_dir.mkdir(parents=True, exist_ok=True)
            source = ytdlp_source.probe_full(
                job.url or "", cookie_browser=self.settings.cookie_browser
            )
            ytdlp_source.download_audio(
                source, work_dir, cookie_browser=self.settings.cookie_browser
            )
        except Exception:  # noqa: BLE001 - on indirme en iyi caba, hata yutulur
            log.info("On indirme basarisiz oldu: %s", job.title, exc_info=True)
        finally:
            self._prefetching = None


def cleanup_orphan_cache(db: Database) -> int:
    """Kuyrukta karsiligi kalmamis calisma dizinlerini sil.

    Iptal edilen veya silinen islerin indirdigi ses dosyalari yoksa diskte
    birikip gigabaytlari yiyor.
    """
    cache = paths.cache_dir()
    if not cache.exists():
        return 0
    known = {job.id for job in db.list_jobs()}
    removed = 0
    for child in cache.iterdir():
        if child.is_dir() and child.name not in known:
            _rmtree(child)
            removed += 1
    return removed


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)
