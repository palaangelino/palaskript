"""Motor arayuzu.

Su an tek bir uygulama var (yerel faster-whisper) ve kullanici offline calismayi
sectigi icin bulut motoru yazilmadi. Arayuz yine de ayri tutuluyor: ileride
fikir degisirse bulut motoru bu protokolu uygulayan tek bir dosya olarak gelir,
boru hattinin geri kalani degismez.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from ..datatypes import Segment


class EngineError(RuntimeError):
    pass


@runtime_checkable
class TranscriptionEngine(Protocol):
    """Ses penceresi alip segment ureten her sey."""

    @property
    def name(self) -> str: ...

    def transcribe_window(
        self,
        samples: np.ndarray,
        *,
        offset: float,
        batch_size: int,
    ) -> list[Segment]:
        """Tek pencereyi yaz.

        offset, pencerenin videodaki mutlak baslangic saniyesi. Doner segmentlerin
        zaman damgalari MUTLAK olmali, pencereye gore degil.
        """
        ...

    @property
    def detected_languages(self) -> list[str]:
        """Simdiye kadar gorulen diller, ilk gorulme sirasiyla."""
        ...

    def close(self) -> None: ...
