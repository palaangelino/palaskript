from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from transkript.audio import SAMPLE_RATE


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(1234)


@pytest.fixture
def make_wav(tmp_path: Path):
    """float32 mono diziyi 16 kHz WAV dosyasina yazan yardimci."""

    def _make(samples: np.ndarray, name: str = "test.wav") -> Path:
        path = tmp_path / name
        pcm16 = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(pcm16.tobytes())
        return path

    return _make
