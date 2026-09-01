"""Kurulum dosyasini bastan sona uret.

    python scripts/build.py            # paketle + kurulum dosyasi
    python scripts/build.py --no-installer   # sadece paketle

Sira: kalite kapisi -> PyInstaller -> Inno Setup.

Kalite kapisi once calisiyor: bozuk bir kodu paketlemenin anlami yok ve
PyInstaller birkac dakika suruyor.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"

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
    parser = argparse.ArgumentParser(description="Transkript kurulum dosyasini uret")
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
        run([python, "-m", "ruff", "check", "transkript", "tests", "scripts"])
        run([python, "-m", "pytest", "tests", "-q"])

    icon = ROOT / "assets" / "icon.ico"
    if not icon.exists():
        print("Ikon yok, uretiliyor...")
        run([python, str(ROOT / "scripts" / "make_icon.py")])

    started = time.monotonic()
    run(
        [
            python,
            "-m",
            "PyInstaller",
            str(ROOT / "packaging" / "transkript.spec"),
            "--noconfirm",
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD),
        ]
    )

    app_dir = DIST / "Transkript"
    exe = app_dir / "Transkript.exe"
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

    run([str(iscc), str(ROOT / "packaging" / "installer.iss")])

    installers = sorted(DIST.glob("Transkript-Setup-*.exe"))
    if installers:
        installer = installers[-1]
        size = installer.stat().st_size / 1024**2
        print(f"\nKurulum dosyasi: {installer}  ({size:.0f} MB)")
        print(
            "\nNot: imzasiz oldugu icin ilk calistirmada SmartScreen uyarisi cikar.\n"
            "'Daha fazla bilgi' > 'Yine de calistir' ile gecilir."
        )
    return 0


if __name__ == "__main__":
    os.chdir(ROOT)
    raise SystemExit(main())
