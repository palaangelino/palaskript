"""Testler arasi paylasilan yardimcilar."""

from __future__ import annotations

import numpy as np

from palaskript.audio import SAMPLE_RATE
from palaskript.datatypes import Segment


def seg(start: float, end: float, text: str, language: str | None = None) -> Segment:
    return Segment(start=start, end=end, text=text, language=language)


def speech_like(seconds: float, rng: np.random.Generator, amplitude: float = 0.25) -> np.ndarray:
    """Konusma yerine gecen gurultu. Sessizlik tespiti testleri icin yeterli."""
    n = int(seconds * SAMPLE_RATE)
    return (rng.standard_normal(n) * amplitude).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)
