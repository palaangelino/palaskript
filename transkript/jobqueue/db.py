"""Kuyrugun SQLite deposu.

Neden JSON degil: isci ilerlemeyi saniyede birkac kez yazarken arayuz ayni anda
okuyor. JSON dosyasini bastan yazmak bu erisim deseninde hem yaristiriyor hem de
cokme aninda dosyayi bos birakabiliyor. SQLite atomik yaziyor, WAL modunda
okuyucu yazariyi engellemiyor ve stdlib'de geliyor.

Baglanti IS PARCACIGI BASINA aciliyor: sqlite3 baglantilarini paylasmak
guvenli degil.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from .. import paths
from ..datatypes import SourceInfo

JobStatus = Literal[
    "pending",
    "awaiting_decision",
    "running",
    "done",
    "failed",
    "cancelled",
]

STATUS_LABELS: dict[str, str] = {
    "pending": "Bekliyor",
    "awaiting_decision": "Karar bekliyor",
    "running": "Isleniyor",
    "done": "Bitti",
    "failed": "Hata",
    "cancelled": "Iptal",
}

STAGE_LABELS: dict[str, str] = {
    "probe": "Inceleniyor",
    "subtitles": "Altyazi aliniyor",
    "download": "Ses indiriliyor",
    "model": "Model hazirlaniyor",
    "transcribe": "Yaziliyor",
    "export": "Belge yaziliyor",
}

# Yeniden baslatildiginda devam edebilecek durumlar.
RESUMABLE = ("pending", "running")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id                TEXT PRIMARY KEY,
    source_id         TEXT NOT NULL,
    kind              TEXT NOT NULL,
    raw_input         TEXT NOT NULL,
    url               TEXT,
    title             TEXT NOT NULL,
    channel           TEXT,
    duration          REAL NOT NULL DEFAULT 0,
    thumbnail_url     TEXT,
    status            TEXT NOT NULL DEFAULT 'pending',
    stage             TEXT,
    progress          REAL NOT NULL DEFAULT 0,
    message           TEXT,
    eta_seconds       REAL,
    error             TEXT,
    use_subtitles     INTEGER,
    manual_sub_langs  TEXT,
    pdf_path          TEXT,
    txt_path          TEXT,
    audio_path        TEXT,
    position          INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    started_at        TEXT,
    finished_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status   ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_position ON jobs(position);
CREATE INDEX IF NOT EXISTS idx_jobs_source   ON jobs(source_id);
"""


@dataclass(slots=True)
class Job:
    id: str
    source_id: str
    kind: str
    raw_input: str
    title: str
    duration: float
    status: str = "pending"
    url: str | None = None
    channel: str | None = None
    thumbnail_url: str | None = None
    stage: str | None = None
    progress: float = 0.0
    message: str | None = None
    eta_seconds: float | None = None
    error: str | None = None
    use_subtitles: bool | None = None
    manual_sub_langs: str | None = None
    pdf_path: str | None = None
    txt_path: str | None = None
    audio_path: str | None = None
    position: int = 0
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None

    @property
    def status_label(self) -> str:
        if self.status == "running" and self.stage:
            return STAGE_LABELS.get(self.stage, STATUS_LABELS["running"])
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def is_active(self) -> bool:
        return self.status in ("pending", "awaiting_decision", "running")

    def to_source_info(self) -> SourceInfo:
        return SourceInfo(
            kind="youtube" if self.kind == "youtube" else "file",
            source_id=self.source_id,
            title=self.title,
            duration=self.duration,
            url=self.url,
            channel=self.channel,
            thumbnail_url=self.thumbnail_url,
            audio_path=Path(self.raw_input) if self.kind == "file" else None,
        )


def _row_to_job(row: sqlite3.Row) -> Job:
    data = dict(row)
    subs = data.get("use_subtitles")
    data["use_subtitles"] = None if subs is None else bool(subs)
    return Job(**data)


class Database:
    """Kuyruk veritabani. Her is parcacigina kendi baglantisini verir."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.queue_db_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._init_schema()

    # ------------------------------------------------------------ baglanti

    @property
    def conn(self) -> sqlite3.Connection:
        existing = getattr(self._local, "conn", None)
        if existing is None:
            existing = sqlite3.connect(str(self.path), timeout=30.0)
            existing.row_factory = sqlite3.Row
            existing.execute("PRAGMA journal_mode=WAL")
            existing.execute("PRAGMA synchronous=NORMAL")
            existing.execute("PRAGMA foreign_keys=ON")
            self._local.conn = existing
        return existing

    def close(self) -> None:
        existing = getattr(self._local, "conn", None)
        if existing is not None:
            existing.close()
            self._local.conn = None

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            conn = self.conn
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _init_schema(self) -> None:
        with self._write() as conn:
            conn.executescript(_SCHEMA)

    # ------------------------------------------------------------- ekleme

    def active_source_ids(self) -> set[str]:
        rows = self.conn.execute(
            "SELECT source_id FROM jobs WHERE status IN ('pending','awaiting_decision','running')"
        ).fetchall()
        return {r["source_id"] for r in rows}

    def _next_position(self) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(position), -1) AS p FROM jobs").fetchone()
        return int(row["p"]) + 1

    def add(
        self,
        source: SourceInfo,
        raw_input: str,
        *,
        use_subtitles: bool | None = None,
    ) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:16],
            source_id=source.source_id,
            kind=source.kind,
            raw_input=raw_input,
            title=source.title,
            duration=source.duration,
            url=source.url,
            channel=source.channel,
            thumbnail_url=source.thumbnail_url,
            use_subtitles=use_subtitles,
            manual_sub_langs=",".join(source.manual_sub_langs) or None,
            position=self._next_position(),
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, source_id, kind, raw_input, url, title, channel, duration,
                    thumbnail_url, status, use_subtitles, manual_sub_langs,
                    position, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job.id,
                    job.source_id,
                    job.kind,
                    job.raw_input,
                    job.url,
                    job.title,
                    job.channel,
                    job.duration,
                    job.thumbnail_url,
                    job.status,
                    None if job.use_subtitles is None else int(job.use_subtitles),
                    job.manual_sub_langs,
                    job.position,
                    job.created_at,
                ),
            )
        return job

    def add_many(
        self,
        sources: Iterable[SourceInfo],
        raw_inputs: dict[str, str] | None = None,
    ) -> tuple[list[Job], list[str]]:
        """Toplu ekleme. (eklenenler, atlanan_basliklar) dondurur."""
        existing = self.active_source_ids()
        added: list[Job] = []
        skipped: list[str] = []
        for source in sources:
            if source.source_id in existing:
                skipped.append(source.title)
                continue
            raw = (raw_inputs or {}).get(source.source_id) or source.url or str(source.audio_path)
            added.append(self.add(source, raw or source.title))
            existing.add(source.source_id)
        return added, skipped

    # ------------------------------------------------------------- okuma

    def list_jobs(self) -> list[Job]:
        rows = self.conn.execute(
            "SELECT * FROM jobs ORDER BY position ASC, created_at ASC"
        ).fetchall()
        return [_row_to_job(r) for r in rows]

    def get(self, job_id: str) -> Job | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def next_pending(self) -> Job | None:
        row = self.conn.execute(
            "SELECT * FROM jobs WHERE status = 'pending' ORDER BY position ASC LIMIT 1"
        ).fetchone()
        return _row_to_job(row) if row else None

    def pending_after(self, job_id: str) -> Job | None:
        """Sirada bekleyen bir SONRAKI is. On indirme bunu kullaniyor."""
        current = self.get(job_id)
        if current is None:
            return self.next_pending()
        row = self.conn.execute(
            "SELECT * FROM jobs WHERE status = 'pending' AND position > ? "
            "ORDER BY position ASC LIMIT 1",
            (current.position,),
        ).fetchone()
        return _row_to_job(row) if row else None

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    # ---------------------------------------------------------- guncelleme

    def _set(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._write() as conn:
            conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))

    def update_progress(
        self,
        job_id: str,
        *,
        stage: str | None = None,
        progress: float | None = None,
        message: str | None = None,
        eta_seconds: float | None = None,
    ) -> None:
        fields: dict[str, Any] = {}
        if stage is not None:
            fields["stage"] = stage
        if progress is not None:
            fields["progress"] = max(0.0, min(1.0, progress))
        if message is not None:
            fields["message"] = message
        fields["eta_seconds"] = eta_seconds
        self._set(job_id, **fields)

    def mark_running(self, job_id: str) -> None:
        self._set(
            job_id,
            status="running",
            error=None,
            started_at=datetime.now().isoformat(timespec="seconds"),
        )

    def mark_awaiting_decision(self, job_id: str, langs: list[str]) -> None:
        self._set(
            job_id,
            status="awaiting_decision",
            manual_sub_langs=",".join(langs) or None,
            message="Videoda hazir altyazi var, nasil devam edilsin?",
        )

    def decide_subtitles(self, job_id: str, use: bool) -> None:
        self._set(job_id, use_subtitles=int(use), status="pending", message=None)

    def mark_done(
        self,
        job_id: str,
        *,
        pdf_path: str | None,
        txt_path: str | None,
        audio_path: str | None,
        message: str | None = None,
    ) -> None:
        self._set(
            job_id,
            status="done",
            stage=None,
            progress=1.0,
            eta_seconds=None,
            pdf_path=pdf_path,
            txt_path=txt_path,
            audio_path=audio_path,
            message=message,
            error=None,
            finished_at=datetime.now().isoformat(timespec="seconds"),
        )

    def mark_failed(self, job_id: str, error: str) -> None:
        self._set(
            job_id,
            status="failed",
            stage=None,
            eta_seconds=None,
            error=error[:2000],
            finished_at=datetime.now().isoformat(timespec="seconds"),
        )

    def mark_cancelled(self, job_id: str) -> None:
        self._set(
            job_id,
            status="cancelled",
            stage=None,
            eta_seconds=None,
            finished_at=datetime.now().isoformat(timespec="seconds"),
        )

    def retry(self, job_id: str) -> None:
        self._set(
            job_id,
            status="pending",
            stage=None,
            progress=0.0,
            error=None,
            message=None,
            eta_seconds=None,
            finished_at=None,
        )

    def delete(self, job_id: str) -> None:
        with self._write() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def clear_finished(self) -> int:
        with self._write() as conn:
            cur = conn.execute("DELETE FROM jobs WHERE status IN ('done','cancelled')")
            return cur.rowcount

    def move(self, job_id: str, delta: int) -> None:
        """Isi kuyrukta yukari (-1) veya asagi (+1) tasi."""
        jobs = self.list_jobs()
        index = next((i for i, j in enumerate(jobs) if j.id == job_id), None)
        if index is None:
            return
        target = index + delta
        if not (0 <= target < len(jobs)):
            return
        jobs[index], jobs[target] = jobs[target], jobs[index]
        with self._write() as conn:
            for position, job in enumerate(jobs):
                conn.execute("UPDATE jobs SET position = ? WHERE id = ?", (position, job.id))

    def reset_stale(self) -> int:
        """Acilista yarim kalmis isleri tekrar sıraya al.

        'running' durumundaki bir is, uygulamanin duzgun kapanmadigi anlamina
        geliyor. Ara kayit dosyasi durdugu icin is kaldigi yerden devam edecek.
        """
        with self._write() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status = 'pending', stage = NULL, eta_seconds = NULL "
                "WHERE status = 'running'"
            )
            return cur.rowcount
