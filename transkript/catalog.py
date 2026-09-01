"""Model indirme ve onbellek yonetimi.

Modeller kurulum paketine girmiyor (large-v3 tek basina 3 GB). Ilk calistirmada
%LOCALAPPDATA%\\Transkript\\models altina iniyor ve orada kaliyor.

Ilerleme, huggingface_hub'in ic yapisina baglanmak yerine hedef dizinin boyutunu
ornekleyerek raporlaniyor. Biraz daha kaba ama HF surum degisikliklerinde kirilmiyor.
"""

from __future__ import annotations

import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import paths
from .resources import MODEL_CATALOG

ProgressCallback = Callable[[float, str], None]

# Bir CT2 Whisper modelinin calismasi icin gereken dosyalar. Yarim inen bir
# indirmeyi "hazir" saymamak icin hepsi kontrol ediliyor.
REQUIRED_FILES = ("model.bin", "config.json", "tokenizer.json")


class ModelDownloadError(RuntimeError):
    pass


def model_dir(name: str) -> Path:
    return paths.models_dir() / name


def is_downloaded(name: str) -> bool:
    d = model_dir(name)
    if not d.is_dir():
        return False
    return all((d / f).exists() for f in REQUIRED_FILES)


def downloaded_models() -> list[str]:
    return [name for name in MODEL_CATALOG if is_downloaded(name)]


def dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def delete_model(name: str) -> None:
    d = model_dir(name)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def ensure_model(name: str, progress: ProgressCallback | None = None) -> Path:
    """Modeli hazir hale getir ve dizinini dondur.

    Zaten inmisse hemen doner. Inmemisse indirir ve ilerlemeyi raporlar.
    """
    if name not in MODEL_CATALOG:
        raise ModelDownloadError(f"Bilinmeyen model: {name}")

    target = model_dir(name)
    if is_downloaded(name):
        return target

    # Yarim kalmis onceki indirmeyi temizle, yoksa boyut olcumu yaniltir.
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)

    spec = MODEL_CATALOG[name]
    expected_bytes = int(spec.download_gb * 1024**3)

    error: list[BaseException] = []
    done = threading.Event()

    def _download() -> None:
        try:
            from faster_whisper import download_model

            download_model(name, output_dir=str(target))
        except BaseException as exc:  # noqa: BLE001 - is parcacigina tasiniyor
            error.append(exc)
        finally:
            done.set()

    worker = threading.Thread(target=_download, name=f"model-download-{name}", daemon=True)
    worker.start()

    if progress:
        progress(0.0, f"{name} modeli indiriliyor ({spec.download_gb:.1f} GB)")

    while not done.wait(timeout=1.0):
        if progress:
            got = dir_size_bytes(target)
            frac = min(0.99, got / expected_bytes) if expected_bytes else 0.0
            progress(
                frac,
                f"{name} indiriliyor: {got / 1024**3:.2f} / {spec.download_gb:.1f} GB",
            )

    worker.join(timeout=5.0)

    if error:
        shutil.rmtree(target, ignore_errors=True)
        raise ModelDownloadError(
            f"{name} modeli indirilemedi: {error[0]}. Internet baglantisini kontrol edin."
        ) from error[0]

    if not is_downloaded(name):
        shutil.rmtree(target, ignore_errors=True)
        raise ModelDownloadError(
            f"{name} modeli eksik indi. Diskte yer olduguna emin olup tekrar deneyin."
        )

    if progress:
        progress(1.0, f"{name} modeli hazir")
    return target


def wait_for_model(name: str, timeout: float = 0.0) -> bool:
    """Baska bir surec ayni modeli indiriyorsa hazir olmasini bekle."""
    deadline = time.monotonic() + timeout
    while True:
        if is_downloaded(name):
            return True
        if timeout <= 0 or time.monotonic() >= deadline:
            return False
        time.sleep(1.0)
