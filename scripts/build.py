"""Kurulum dosyasini bastan sona uret.

    python scripts/build.py            # paketle + kurulum dosyasi
    python scripts/build.py --no-installer   # sadece paketle

Sira: kalite kapisi -> PyInstaller -> Inno Setup.

Kalite kapisi once calisiyor: bozuk bir kodu paketlemenin anlami yok ve
PyInstaller birkac dakika suruyor.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def app_version() -> str:
    """Surumun tek kaynagi palaskript/__init__.py.

    Kurulum betigine /DAppVersion ile geciliyor, boylece surum iki yerde
    tutulup birbirinden ayrilmiyor.
    """
    text = (ROOT / "palaskript" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("palaskript/__init__.py icinde __version__ bulunamadi")
    return match.group(1)


def write_checksum(path: Path) -> Path:
    """Kurulum dosyasinin SHA-256'sini yaz.

    Uygulama guncellemeyi indirdikten sonra bunu dogruluyor; yarim inmis bir
    kurulum dosyasini calistirmak bozuk kuruluma yol acar.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    target = path.with_suffix(path.suffix + ".sha256")
    # Bicim: sha256sum ile ayni, "<ozet>  <dosya adi>".
    target.write_text(f"{digest.hexdigest()}  {path.name}\n", encoding="utf-8")
    return target

# Inno Setup derleyicisinin olasi konumlari. winget kullanici kapsamina
# kuruyor (LOCALAPPDATA), elle kurulum ise Program Files'a; ikisine de bakiyoruz.
ISCC_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
]


def run(command: list[str], *, cwd: Path | None = None) -> None:
    printable = " ".join(str(c) for c in command)
    print(f"\n>>> {printable}\n")
    result = subprocess.run(command, cwd=str(cwd or ROOT))
    if result.returncode != 0:
        raise SystemExit(f"Komut basarisiz (cikis {result.returncode}): {printable}")


def python_exe() -> str:
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    return str(venv) if venv.exists() else sys.executable


def find_iscc() -> Path | None:
    found = shutil.which("iscc")
    if found:
        return Path(found)
    return next((path for path in ISCC_CANDIDATES if path.exists()), None)


def directory_size_mb(path: Path) -> float:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total / 1024**2


def main() -> int:
    parser = argparse.ArgumentParser(description="Palaskript kurulum dosyasini uret")
    parser.add_argument("--no-installer", action="store_true", help="Sadece PyInstaller calistir")
    parser.add_argument("--skip-checks", action="store_true", help="ruff ve pytest'i atla")
    parser.add_argument("--clean", action="store_true", help="Once build/ ve dist/ sil")
    args = parser.parse_args()

    python = python_exe()

    if args.clean:
        for path in (BUILD, DIST):
            if path.exists():
                print(f"Siliniyor: {path}")
                shutil.rmtree(path, ignore_errors=True)

    if not args.skip_checks:
        run([python, "-m", "ruff", "check", "palaskript", "tests", "scripts"])
        run([python, "-m", "pytest", "tests", "-q"])

    icon = ROOT / "assets" / "icon.ico"
    if not icon.exists():
        print("Marka gorselleri yok, uretiliyor...")
        run([python, str(ROOT / "scripts" / "make_brand.py")])

    started = time.monotonic()
    run(
        [
            python,
            "-m",
            "PyInstaller",
            str(ROOT / "packaging" / "palaskript.spec"),
            "--noconfirm",
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD),
        ]
    )

    app_dir = DIST / "Palaskript"
    exe = app_dir / "Palaskript.exe"
    if not exe.exists():
        raise SystemExit(f"Beklenen cikti olusmadi: {exe}")

    print(f"\nPaketlendi: {app_dir}")
    print(f"Boyut: {directory_size_mb(app_dir):.0f} MB")
    print(f"Sure: {time.monotonic() - started:.0f} sn")

    if args.no_installer:
        return 0

    iscc = find_iscc()
    if iscc is None:
        print(
            "\nInno Setup bulunamadi, kurulum dosyasi uretilmedi.\n"
            "Kurmak icin: https://jrsoftware.org/isdl.php\n"
            f"Uygulama yine de calisir durumda: {exe}"
        )
        return 0

    version = app_version()
    run([str(iscc), f"/DAppVersion={version}", str(ROOT / "packaging" / "installer.iss")])

    installers = sorted(p for p in DIST.glob("Palaskript-Setup-*.exe") if p.suffix == ".exe")
    if installers:
        installer = installers[-1]
        size = installer.stat().st_size / 1024**2
        # Ozet dosyasi yayin icin ZORUNLU: uygulama indirdigi kurulumu bununla
        # dogruluyor ve yayin is akisi dosyayi bulamazsa duruyor.
        checksum = write_checksum(installer)
        print(f"\nKurulum dosyasi: {installer}  ({size:.0f} MB)")
        print(f"Sagalama toplami: {checksum.name}")
        print(
            "\nNot: imzasiz oldugu icin ilk calistirmada SmartScreen uyarisi cikar.\n"
            "'Daha fazla bilgi' > 'Yine de calistir' ile gecilir."
        )
    return 0


if __name__ == "__main__":
    os.chdir(ROOT)
    raise SystemExit(main())
