"""Ara kayit ve devam ettirme.

Uzun isler bu dosyaya bagli: 6 saatlik bir transkripsiyon cokme, elektrik
kesintisi veya kullanicinin uygulamayi kapatmasi yuzunden sifirdan baslamamali.

Kayit birimi PENCERE. Segmentler geldikleri anda yaziliyor ama bir pencere
ancak kendi isareti yazildiginda "islenmis" sayiliyor. Yarim kalmis pencerenin
segmentleri devam ederken atiliyor, cunku o pencere bastan islenecek ve
tutulsalardi metin iki kez cikardi.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any, TextIO

from . import paths
from .datatypes import Segment


class Checkpoint:
    """Bir isin ara kayit dosyasi."""

    def __init__(self, job_id: str, directory: Path | None = None) -> None:
        self.job_id = job_id
        base = directory or paths.checkpoints_dir()
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / f"{job_id}.jsonl"
        self._handle: TextIO | None = None

    # ------------------------------------------------------------ yazma

    def open(self) -> None:
        if self._handle is None:
            self._handle = self.path.open("a", encoding="utf-8")

    def close(self) -> None:
        if self._handle is not None:
            try:
                self._handle.flush()
            finally:
                self._handle.close()
                self._handle = None

    def __enter__(self) -> Checkpoint:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _write(self, record: dict[str, Any]) -> None:
        if self._handle is None:
            self.open()
        assert self._handle is not None
        self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        # Her satirda flush: cokme aninda diskte olmayan satir kayiptir.
        self._handle.flush()

    def write_meta(self, **fields: Any) -> None:
        self._write({"t": "meta", **fields})

    def write_segments(self, segments: list[Segment]) -> None:
        for seg in segments:
            self._write({"t": "seg", **seg.to_dict()})

    def commit_window(self, index: int, end: float) -> None:
        """Pencereyi islenmis olarak isaretle. Devam noktasi budur."""
        self._write({"t": "win", "index": index, "end": float(end)})

    # ------------------------------------------------------------ okuma

    def exists(self) -> bool:
        return self.path.exists() and self.path.stat().st_size > 0

    def load(self) -> tuple[list[Segment], float, dict[str, Any]]:
        """(segmentler, devam_saniyesi, meta) dondurur.

        Son pencere isaretinden sonraki segmentler atiliyor: o pencere yarim
        kalmis demektir ve bastan islenecek.
        """
        if not self.exists():
            return [], 0.0, {}

        segments: list[Segment] = []
        meta: dict[str, Any] = {}
        resume_at = 0.0
        committed_count = 0

        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    # Cokme aninda yarim yazilmis son satir olabilir, atla.
                    continue

                kind = record.get("t")
                if kind == "seg":
                    try:
                        segments.append(Segment.from_dict(record))
                    except (KeyError, ValueError, TypeError):
                        continue
                elif kind == "win":
                    resume_at = float(record.get("end", resume_at))
                    committed_count = len(segments)
                elif kind == "meta":
                    meta = {k: v for k, v in record.items() if k != "t"}

        return segments[:committed_count], resume_at, meta

    def clear(self) -> None:
        self.close()
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


def discard(job_id: str, directory: Path | None = None) -> None:
    Checkpoint(job_id, directory).clear()


def has_checkpoint(job_id: str, directory: Path | None = None) -> bool:
    return Checkpoint(job_id, directory).exists()
