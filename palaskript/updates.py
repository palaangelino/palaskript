"""GitHub Releases uzerinden guncelleme.

Sunucu tutmuyoruz. Depo zaten GitHub'da halka acik oldugu icin surum bilgisi
ve kurulum dosyasi orada duruyor; uygulama yalnizca "en son surum ne" diye
soruyor. Bu, kendi guncelleme sunucusunu isletmeye gore hem bedava hem de
bakim gerektirmiyor.

Akis:
    1. Uygulama acilinca arka planda GitHub API'sine soruyor
    2. Surum daha yeniyse kullaniciya bir cubuk gosteriyor (zorla kurmuyor)
    3. Kullanici onaylarsa kurulum dosyasi iniyor, SHA-256'si dogrulaniyor
    4. Uygulama kapaniyor ve kurulum baslatiliyor

Kurulum dosyasi ayni AppId ile uretildigi icin Inno Setup uzerine yaziyor,
yan yana ikinci bir kurulum olusmuyor. Ayarlar, kuyruk ve inmis modeller
kullanici dizininde durdugu icin guncellemeden etkilenmiyor.

Dogrulama neden onemli: yarim inmis bir kurulum dosyasini calistirmak bozuk
kuruluma yol acar. Yayin sirasinda uretilen .sha256 dosyasi bunu engelliyor.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import __version__

# Yayin deposu: "kullanici/depo" bicimi, ornegin "ornek/palaskript".
#
# BURAYI DOLDURUN. Bos birakilirsa guncelleme denetimi hic calismiyor; bu
# bilincli: yanlis bir depo adiyla sessizce baska birinin yayinlarini
# indirmeye calismak, hic denetlememekten kotu.
#
# Kullanici ayarlardan da degistirebiliyor, boylece catallayan kendi deposunu
# uygulamayi yeniden derlemeden verebiliyor.
DEFAULT_REPO = ""

_API = "https://api.github.com/repos/{repo}/releases/latest"
_TIMEOUT = 20
_USER_AGENT = f"Palaskript/{__version__}"

# "v1.2.3" ve "1.2.3" kabul, ardindaki on-surum eki yok sayiliyor.
_VERSION_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")

ProgressCallback = Callable[[float, str], None]


class UpdateError(RuntimeError):
    pass


@dataclass(slots=True)
class Release:
    version: str
    tag: str
    notes: str
    installer_url: str | None
    installer_name: str | None
    installer_size: int
    checksum_url: str | None

    @property
    def can_install(self) -> bool:
        return bool(self.installer_url)


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.search(text or "")
    if not match:
        return None
    return tuple(int(g) for g in match.groups())  # type: ignore[return-value]


def is_newer(candidate: str, current: str = __version__) -> bool:
    """candidate, current'tan yeni mi.

    Ayristirilamayan surum "yeni degil" sayiliyor: bilinmeyen bir etiket
    yuzunden kullaniciyi guncellemeye cagirmak yanlis olur.
    """
    new = parse_version(candidate)
    old = parse_version(current)
    if new is None or old is None:
        return False
    return new > old


def _get_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("Depoda henüz yayınlanmış bir sürüm yok.") from exc
        if exc.code == 403:
            raise UpdateError("GitHub istek sınırına takıldı, biraz sonra tekrar deneyin.") from exc
        raise UpdateError(f"Sürüm bilgisi alınamadı (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise UpdateError(f"Sürüm bilgisi alınamadı: {exc}") from exc


def fetch_latest(repo: str = DEFAULT_REPO) -> Release:
    """Depodaki en son yayini getir."""
    if not repo or "/" not in repo:
        raise UpdateError("Güncelleme deposu ayarlanmamış.")

    data = _get_json(_API.format(repo=repo))
    tag = str(data.get("tag_name") or "")
    version = tag.lstrip("vV")

    installer_url = installer_name = checksum_url = None
    installer_size = 0
    for asset in data.get("assets") or []:
        name = str(asset.get("name") or "")
        if name.endswith(".sha256"):
            checksum_url = asset.get("browser_download_url")
        elif name.lower().endswith(".exe") and "setup" in name.lower():
            installer_url = asset.get("browser_download_url")
            installer_name = name
            installer_size = int(asset.get("size") or 0)

    return Release(
        version=version,
        tag=tag,
        notes=str(data.get("body") or "").strip(),
        installer_url=installer_url,
        installer_name=installer_name,
        installer_size=installer_size,
        checksum_url=checksum_url,
    )


def check(repo: str = DEFAULT_REPO) -> Release | None:
    """Yeni surum varsa dondur, yoksa None."""
    release = fetch_latest(repo)
    return release if is_newer(release.version) else None


def _download(url: str, target: Path, expected_size: int, progress: ProgressCallback | None) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            total = int(response.headers.get("Content-Length") or expected_size or 0)
            read = 0
            with target.open("wb") as handle:
                while True:
                    block = response.read(256 * 1024)
                    if not block:
                        break
                    handle.write(block)
                    read += len(block)
                    if progress and total:
                        progress(
                            read / total,
                            f"İndiriliyor: {read / 1024**2:.0f} / {total / 1024**2:.0f} MB",
                        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        target.unlink(missing_ok=True)
        raise UpdateError(f"İndirme başarısız: {exc}") from exc


def _expected_checksum(url: str) -> str | None:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            text = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    # "<sha256>  <dosya adi>" bicimi ya da yalin ozet
    first = text.strip().split()
    return first[0].lower() if first else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_installer(
    release: Release,
    *,
    progress: ProgressCallback | None = None,
) -> Path:
    """Kurulum dosyasini indir ve dogrula. Dosya yolunu dondurur."""
    if not release.installer_url or not release.installer_name:
        raise UpdateError("Bu yayında kurulum dosyası yok.")

    target = Path(tempfile.gettempdir()) / release.installer_name
    target.unlink(missing_ok=True)

    if progress:
        progress(0.0, f"Palaskript {release.version} indiriliyor")
    _download(release.installer_url, target, release.installer_size, progress)

    if release.checksum_url:
        if progress:
            progress(1.0, "Dosya doğrulanıyor")
        expected = _expected_checksum(release.checksum_url)
        if expected and _sha256(target) != expected:
            target.unlink(missing_ok=True)
            raise UpdateError(
                "İndirilen dosya doğrulanamadı. İndirme yarım kalmış olabilir, "
                "tekrar deneyin."
            )
    elif release.installer_size and target.stat().st_size != release.installer_size:
        # Ozet yoksa en azindan boyut tutmali.
        target.unlink(missing_ok=True)
        raise UpdateError("İndirilen dosya eksik. Tekrar deneyin.")

    return target


def launch_installer(path: Path) -> None:
    """Kurulumu baslat.

    Uygulama bunun hemen ardindan kapanmali: Inno Setup calisan dosyalarin
    uzerine yazamiyor.
    """
    if not path.exists():
        raise UpdateError("Kurulum dosyası bulunamadı.")
    try:
        subprocess.Popen(
            [str(path)],
            close_fds=True,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except OSError as exc:
        raise UpdateError(f"Kurulum başlatılamadı: {exc}") from exc


def is_frozen() -> bool:
    """Paketlenmis uygulama mi.

    Kaynaktan calisirken guncelleme onerilmiyor: gelistirici kendi kopyasini
    git ile guncelliyor ve kurulum dosyasi calistirmak calisma kopyasini bozar.
    """
    return bool(getattr(sys, "frozen", False))
