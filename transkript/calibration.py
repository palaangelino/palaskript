"""Bu makinede gercekten olculen bellek ve hiz degerleri.

MODEL_CATALOG icindeki RAM rakamlari hesapla uretilmis tahminler ve her
makinede tutmuyor: CPU'nun vektor birimi, ctranslate2'nin ayirdigi tampon
boyutu ve isletim sisteminin bellek muhasebesi makineden makineye degisiyor.
Yanlis tahmin 8 GB'lik bir makinede takas bellegi demek.

Kurulum sirasinda olcum yapmiyoruz: olcum icin modelin inmis olmasi gerekir
(1.6 GB) ve kurulumu on dakikaya cikarmak kotu bir takas olurdu. Bunun yerine
olcumu ZATEN YAPILAN ISTEN aliyoruz. Ilk gercek is bittiginde bu makinenin
gercek tepe bellegi ve hizi elimizde oluyor, hicbir ek bekleme olmadan.

Sonraki isler bu olculmus degerleri kullaniyor; henuz olculmemis bir model
icin tahmine duseluyor.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import paths

# Bu surumden eski kayitlar yok sayiliyor: olcum yontemi degistiginde eski
# sayilarla karar vermek yanlis olurdu.
SCHEMA_VERSION = 1

# Olcumun anlamli sayilmasi icin gereken en kisa ses. Cok kisa isler model
# yukleme maliyetini gercek zaman katsayisina yediriyor ve hizi oldugundan
# dusuk gosteriyor.
MIN_AUDIO_SECONDS = 120.0


@dataclass(slots=True)
class Measurement:
    model: str
    batch_size: int
    peak_rss_gb: float
    realtime_factor: float
    audio_seconds: float
    measured_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calibration_file() -> Path:
    return paths.app_data_dir() / "calibration.json"


def _key(model: str, batch_size: int) -> str:
    return f"{model}@{batch_size}"


def load() -> dict[str, Measurement]:
    path = calibration_file()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict) or raw.get("version") != SCHEMA_VERSION:
        return {}

    out: dict[str, Measurement] = {}
    for key, value in (raw.get("measurements") or {}).items():
        try:
            out[key] = Measurement(**value)
        except (TypeError, ValueError):
            continue
    return out


def save(measurements: dict[str, Measurement]) -> None:
    path = calibration_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": SCHEMA_VERSION,
        "measurements": {k: m.to_dict() for k, m in measurements.items()},
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def record(
    *,
    model: str,
    batch_size: int,
    peak_rss_gb: float,
    audio_seconds: float,
    elapsed_seconds: float,
) -> Measurement | None:
    """Bir isin olcumunu kaydet.

    Cok kisa isler ve olculemeyen bellek atlaniyor: yanlis bir olcum,
    olcumsuzlukten kotudur.
    """
    if audio_seconds < MIN_AUDIO_SECONDS or elapsed_seconds <= 0 or peak_rss_gb <= 0:
        return None

    measurement = Measurement(
        model=model,
        batch_size=batch_size,
        peak_rss_gb=round(peak_rss_gb, 2),
        realtime_factor=round(audio_seconds / elapsed_seconds, 3),
        audio_seconds=round(audio_seconds, 1),
        measured_at=datetime.now().isoformat(timespec="seconds"),
    )

    measurements = load()
    previous = measurements.get(_key(model, batch_size))
    if previous is not None:
        # Tepe bellekte en kotu durumu tutuyoruz: guvenli taraf bu. Hizda ise
        # en son olcum daha temsili, makinenin o anki yuku degisiyor.
        measurement.peak_rss_gb = round(max(measurement.peak_rss_gb, previous.peak_rss_gb), 2)

    measurements[_key(model, batch_size)] = measurement
    save(measurements)
    return measurement


def lookup(model: str, batch_size: int) -> Measurement | None:
    return load().get(_key(model, batch_size))


def measured_ram_gb(model: str, batch_size: int) -> float | None:
    """Olculmus tepe bellek, yoksa None."""
    found = lookup(model, batch_size)
    return found.peak_rss_gb if found else None


def measured_realtime_factor(model: str) -> float | None:
    """Model icin olculmus en son gercek zaman katsayisi (yigin farketmeksizin)."""
    candidates = [m for m in load().values() if m.model == model]
    if not candidates:
        return None
    latest = max(candidates, key=lambda m: m.measured_at)
    return latest.realtime_factor


def clear() -> None:
    with contextlib.suppress(FileNotFoundError):
        calibration_file().unlink()


def describe(model: str, batch_size: int) -> str:
    """Ayarlar ekraninda gosterilecek kisa aciklama."""
    found = lookup(model, batch_size)
    if found is None:
        return "tahmin"
    return f"ölçüldü: {found.peak_rss_gb:.1f} GB, {found.realtime_factor:.2f}x"
