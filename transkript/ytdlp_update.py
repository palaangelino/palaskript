"""yt-dlp'yi uygulamadan bagimsiz guncelleme.

YouTube sik degisiyor ve paketlenmis yt-dlp birkac ay icinde bozuluyor. Kurulum
dosyasini yeniden yayinlamak zorunda kalmadan guncelleyebilmek icin, en son
surum kullanici veri dizinine indiriliyor ve sys.path'in basina konuyor.

pip kullanmiyoruz: paketlenmis uygulamada pip yok. yt-dlp saf Python oldugu
icin PyPI'daki tekerlegi (wheel) indirip acmak yeterli, sadece urllib ve
zipfile gerekiyor.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from . import paths

PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"
_TIMEOUT = 30
_USER_AGENT = "Transkript/1.0 (+yt-dlp updater)"

ProgressCallback = Callable[[float, str], None]


class UpdateError(RuntimeError):
    pass


def user_package_dir() -> Path:
    return paths.local_data_dir() / "ytdlp"


def activate() -> bool:
    """Kullanici dizinindeki yt-dlp varsa sys.path'in basina koy.

    Uygulama acilisinda, yt_dlp import edilmeden ONCE cagrilmali.
    """
    target = user_package_dir()
    if not (target / "yt_dlp" / "__init__.py").exists():
        return False
    path = str(target)
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)
    return True


def installed_version() -> str | None:
    try:
        import yt_dlp

        return getattr(yt_dlp, "__version__", None)
    except ImportError:
        return None


def is_user_managed() -> bool:
    """Su an kullanilan yt-dlp kullanici dizininden mi geliyor."""
    try:
        import yt_dlp

        return str(user_package_dir()) in str(Path(yt_dlp.__file__).resolve())
    except (ImportError, AttributeError, OSError):
        return False


def _fetch_metadata() -> dict:
    request = urllib.request.Request(PYPI_URL, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise UpdateError(f"Sürüm bilgisi alınamadı: {exc}") from exc


def latest_version() -> str:
    data = _fetch_metadata()
    version = (data.get("info") or {}).get("version")
    if not version:
        raise UpdateError("PyPI yanıtında sürüm bulunamadı.")
    return str(version)


def _wheel_url(data: dict) -> str:
    for entry in data.get("urls") or []:
        if entry.get("packagetype") == "bdist_wheel" and str(
            entry.get("filename", "")
        ).endswith("-py3-none-any.whl"):
            return str(entry["url"])
    raise UpdateError("Uygun yt-dlp paketi bulunamadı.")


def update(progress: ProgressCallback | None = None) -> str:
    """En son yt-dlp'yi indir ve kur. Kurulan surumu dondurur."""

    def report(fraction: float, message: str) -> None:
        if progress:
            progress(fraction, message)

    report(0.0, "Sürüm bilgisi alınıyor")
    data = _fetch_metadata()
    version = str((data.get("info") or {}).get("version") or "?")
    url = _wheel_url(data)

    target = user_package_dir()
    staging = target.parent / "ytdlp.new"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    report(0.1, f"yt-dlp {version} indiriliyor")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            total = int(response.headers.get("Content-Length") or 0)
            with tempfile.NamedTemporaryFile(suffix=".whl", delete=False) as tmp:
                wheel_path = Path(tmp.name)
                read = 0
                while True:
                    block = response.read(64 * 1024)
                    if not block:
                        break
                    tmp.write(block)
                    read += len(block)
                    if total:
                        report(0.1 + 0.7 * (read / total), f"Indiriliyor {read // 1024} KB")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"İndirme başarısız: {exc}") from exc

    report(0.85, "Paket açılıyor")
    try:
        with zipfile.ZipFile(wheel_path) as archive:
            archive.extractall(staging)
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"Paket açılamadı: {exc}") from exc
    finally:
        wheel_path.unlink(missing_ok=True)

    if not (staging / "yt_dlp" / "__init__.py").exists():
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError("İndirilen paket beklenen içerikte değil.")

    # Eskisini son anda degistir: yarim kalan bir guncelleme calisan kurulumu
    # bozmasin.
    backup = target.parent / "ytdlp.old"
    shutil.rmtree(backup, ignore_errors=True)
    if target.exists():
        try:
            target.rename(backup)
        except OSError:
            shutil.rmtree(target, ignore_errors=True)
    try:
        staging.rename(target)
    except OSError as exc:
        if backup.exists():
            backup.rename(target)
        raise UpdateError(f"Güncelleme yerine konamadı: {exc}") from exc
    shutil.rmtree(backup, ignore_errors=True)

    report(1.0, f"yt-dlp {version} kuruldu")
    return version
