"""Yerel faster-whisper motoru (CTranslate2, CPU, int8).

Parametreler konusma videolarina ve uzun kayitlara gore secildi:

- vad_filter: sessizlikleri atliyor. Konusma videolarinda duraklamalar uzun
  oldugu icin buradaki kazanc tipik kayittan yuksek.
- condition_on_previous_text=False: uzun dosyalarda Whisper onceki metne
  baglanip ayni cumleyi dakikalarca tekrarlayan bir donguye girebiliyor.
  Baglami kesmek bu donguyu de kesiyor.
- multilingual: TR + EN kod gecisli icerikte dil algilamasi segment bazinda
  yapiliyor. Tek dilli videolarda dili elle zorlamak hem daha hizli hem daha
  dogru, o yuzden ayarlardan zorlanabiliyor.

faster-whisper'in transcribe imzasi surumler arasinda degisiyor. Desteklenmeyen
bir parametre yuzunden calismanin komple patlamamasi icin kwargs, cagrilan
fonksiyonun gercek imzasina gore suzuluyor.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from ..datatypes import Segment
from ..resources import Profile
from .base import EngineError


def _filter_kwargs(func: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """kwargs'i func'in kabul ettiklerine indir.

    func **kwargs aliyorsa hepsi gecer.
    """
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return dict(kwargs)

    params = sig.parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(kwargs)
    return {k: v for k, v in kwargs.items() if k in params}


class LocalWhisperEngine:
    """CPU uzerinde calisan yerel Whisper motoru."""

    def __init__(
        self,
        model_path: Path | str,
        profile: Profile,
        *,
        language: str | None = None,
        beam_size: int = 5,
    ) -> None:
        try:
            from faster_whisper import BatchedInferencePipeline, WhisperModel
        except ImportError as exc:  # pragma: no cover
            raise EngineError("faster-whisper kurulu degil.") from exc

        self._profile = profile
        self._language = language
        self._beam_size = beam_size
        self._languages: list[str] = []

        try:
            self._model = WhisperModel(
                str(model_path),
                device="cpu",
                compute_type=profile.compute_type,
                cpu_threads=profile.cpu_threads,
                num_workers=1,
            )
        except Exception as exc:  # noqa: BLE001
            raise EngineError(
                f"Model yuklenemedi ({model_path}). Model dosyasi bozuk olabilir, "
                f"ayarlardan silip tekrar indirin. Ayrinti: {exc}"
            ) from exc

        try:
            self._batched = BatchedInferencePipeline(model=self._model)
        except Exception:  # noqa: BLE001 - toplu hat yoksa tekli hatta duseriz
            self._batched = None

    @property
    def name(self) -> str:
        return f"faster-whisper {self._profile.model} ({self._profile.compute_type}, CPU)"

    @property
    def detected_languages(self) -> list[str]:
        return list(self._languages)

    def _note_language(self, lang: str | None) -> None:
        if lang and lang not in self._languages:
            self._languages.append(lang)

    def _common_kwargs(self, batch_size: int) -> dict[str, Any]:
        forced = self._language
        return {
            "language": forced,
            # Dil zorlanmadiysa segment bazinda algila (TR + EN kod gecisi icin).
            "multilingual": forced is None,
            "task": "transcribe",
            "beam_size": self._beam_size,
            "vad_filter": True,
            "condition_on_previous_text": False,
            "no_speech_threshold": 0.6,
            "compression_ratio_threshold": 2.4,
            "word_timestamps": False,
            "batch_size": batch_size,
        }

    def transcribe_window(
        self,
        samples: np.ndarray,
        *,
        offset: float,
        batch_size: int,
    ) -> list[Segment]:
        if samples.size == 0:
            return []

        audio = np.ascontiguousarray(samples, dtype=np.float32)
        kwargs = self._common_kwargs(batch_size)

        # batch_size 1 ise toplu hattin ek yuku bosa gidiyor, ustelik tekli hat
        # daha az bellek kullaniyor. Bellek korumasi yigini 1'e dusurdugunde
        # tam da bunu istiyoruz.
        use_batched = self._batched is not None and batch_size > 1
        target = self._batched.transcribe if use_batched else self._model.transcribe
        if not use_batched:
            kwargs.pop("batch_size", None)

        try:
            segments_iter, info = target(audio, **_filter_kwargs(target, kwargs))
        except Exception as exc:  # noqa: BLE001
            raise EngineError(f"Transkripsiyon basarisiz: {exc}") from exc

        detected = getattr(info, "language", None)
        self._note_language(detected)

        out: list[Segment] = []
        for seg in segments_iter:
            text = (seg.text or "").strip()
            if not text:
                continue
            lang = getattr(seg, "language", None) or detected
            self._note_language(lang)
            out.append(
                Segment(
                    start=float(seg.start) + offset,
                    end=float(seg.end) + offset,
                    text=text,
                    language=lang,
                )
            )
        return out

    def close(self) -> None:
        self._batched = None
        model = getattr(self, "_model", None)
        if model is not None:
            # ctranslate2 modeli GC ile birakiliyor; referansi dusurmek yeterli.
            self._model = None  # type: ignore[assignment]
            del model
