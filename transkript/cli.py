"""Komut satiri arayuzu.

Arayuz olmadan ucdan uca calisan hat. Hata ayiklama ve toplu is icin pratik,
ayrica Faz 1'in teslim ediligi nokta: PDF akisinin dogrulugu buradan
kontrol edilebiliyor.

Ornek:
    transkript-cli "https://www.youtube.com/watch?v=..." --lang tr
    transkript-cli "C:\\videolar\\sunum.mp4" --model medium --out C:\\ciktilar
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, config, paths
from .chapters import format_timestamp
from .pipeline import JobCancelled, Progress, run_job
from .resources import MODEL_CATALOG, available_models, choose_profile, detect
from .source import resolver


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="transkript-cli",
        description="YouTube linkinden veya yerel videodan PDF transkript uretir.",
    )
    parser.add_argument("input", nargs="?", help="YouTube adresi veya dosya yolu")
    parser.add_argument("--model", choices=sorted(MODEL_CATALOG), help="Whisper modeli")
    parser.add_argument(
        "--lang",
        choices=["auto", "tr", "en"],
        help="Dil. auto, TR/EN karisik icerikte segment bazinda algilar.",
    )
    parser.add_argument("--out", type=Path, help="Cikti klasoru")
    parser.add_argument("--threads", type=int, help="CPU is parcacigi sayisi")
    parser.add_argument(
        "--subs",
        action="store_true",
        help="Videoda insan eliyle yazilmis altyazi varsa Whisper yerine onu kullan",
    )
    parser.add_argument("--no-pdf", action="store_true", help="PDF uretme")
    parser.add_argument("--no-txt", action="store_true", help="TXT uretme")
    parser.add_argument("--keep-audio", action="store_true", help="Indirilen sesi sakla")
    parser.add_argument(
        "--low-memory", action="store_true", help="Dusuk bellek modu (yigin 1, kucuk pencere)"
    )
    parser.add_argument(
        "--no-resume", action="store_true", help="Ara kayittan devam etme, bastan basla"
    )
    parser.add_argument(
        "--info", action="store_true", help="Donanim profilini yazdir ve cik"
    )
    parser.add_argument("--version", action="version", version=f"Transkript {__version__}")
    return parser


def _print_hardware() -> None:
    hw = detect()
    profile = choose_profile(hw)
    print("Donanim:", hw.describe())
    print("Bos disk:", f"{hw.free_disk_gb:.1f} GB")
    print("Secilen profil:", profile.describe())
    print()
    print("Modeller:")
    for name, reason in available_models(hw).items():
        spec = MODEL_CATALOG[name]
        ram = spec.ram_estimate_gb(profile.batch_size)
        mark = "  " if reason else "* "
        note = f"  [{reason}]" if reason else ""
        print(f"{mark}{name:<16} indirme {spec.download_gb:>4.1f} GB   RAM ~{ram:.1f} GB{note}")


class _ProgressPrinter:
    """Tek satirda guncellenen ilerleme cikti."""

    def __init__(self) -> None:
        self._last = ""

    def __call__(self, event: Progress) -> None:
        eta = ""
        if event.eta_seconds and event.eta_seconds > 0:
            eta = f"  kalan ~{format_timestamp(event.eta_seconds, always_hours=True)}"
        line = f"[{event.fraction * 100:5.1f}%] {event.message}{eta}"
        pad = " " * max(0, len(self._last) - len(line))
        sys.stdout.write("\r" + line + pad)
        sys.stdout.flush()
        self._last = line

    def done(self) -> None:
        if self._last:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._last = ""


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.info:
        _print_hardware()
        return 0

    if not args.input:
        parser.error("bir adres veya dosya yolu verin (veya --info kullanin)")

    paths.ensure_dirs()
    settings = config.load()

    if args.model:
        settings.model = args.model
    if args.lang:
        settings.language = args.lang
    if args.out:
        settings.output_dir = str(args.out)
    if args.threads:
        settings.cpu_threads = args.threads
    if args.no_pdf:
        settings.export_pdf = False
    if args.no_txt:
        settings.export_txt = False
    if args.keep_audio:
        settings.keep_audio = True
    if args.low_memory:
        settings.low_memory_mode = True

    try:
        sources = resolver.resolve_one(args.input, cookie_browser=settings.cookie_browser)
    except Exception as exc:  # noqa: BLE001
        print(f"Hata: {exc}", file=sys.stderr)
        return 2

    if not sources:
        print("Islenecek bir sey bulunamadi.", file=sys.stderr)
        return 2

    hw = detect()
    print(f"Donanim: {hw.describe()}")
    print(f"{len(sources)} kaynak islenecek\n")

    failures = 0
    for index, source in enumerate(sources, start=1):
        print(f"[{index}/{len(sources)}] {source.title}")
        printer = _ProgressPrinter()
        job_id = f"cli-{abs(hash(source.source_id)) % (10**12):012d}"
        try:
            result = run_job(
                source,
                settings,
                job_id=job_id,
                progress=printer,
                use_subtitles=args.subs,
                hardware=hw,
                resume=not args.no_resume,
            )
        except JobCancelled:
            printer.done()
            print("  Iptal edildi.")
            failures += 1
            continue
        except KeyboardInterrupt:
            printer.done()
            print("\n  Durduruldu. Ara kayit saklandi, tekrar calistirinca devam eder.")
            return 130
        except Exception as exc:  # noqa: BLE001
            printer.done()
            print(f"  Hata: {exc}", file=sys.stderr)
            failures += 1
            continue

        printer.done()
        mins = result.elapsed_seconds / 60
        print(f"  {result.doc.word_count} kelime, {mins:.1f} dakikada")
        if result.from_subtitles:
            print("  Kaynak: videonun hazir altyazisi")
        if result.pdf_path:
            print(f"  PDF: {result.pdf_path}")
        if result.txt_path:
            print(f"  TXT: {result.txt_path}")
        for warning in result.warnings:
            print(f"  Uyari: {warning}")
        print()

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
