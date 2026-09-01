"""Faz 0: model, is parcacigi ve yigin boyutu olcumu.

Neden ilk is bu: palaskript/resources.py icindeki RAM tahminleri su an hesaba
dayaniyor, olcume degil. 8 GB'lik makinelerde hangi modelin sigacagini tahminle
belirlemek, o makinelerde takas bellegine dusmek demek. Bu arac gercek sayilari
uretiyor ve MODEL_CATALOG'daki degerler bunlara gore duzeltiliyor.

Uc eksen olculuyor:
  1. Hiz  : gercek zaman katsayisi (ses suresi / islem suresi)
  2. Bellek: tepe RSS, her yapilandirma AYRI SUREC'te olculuyor
  3. Kalite: metin ciktilari yan yana, gozle karsilastirmak icin

Kullanim:
    python scripts/benchmark.py "https://www.youtube.com/watch?v=..."
    python scripts/benchmark.py C:\\video\\konusma.mp4 --slice-minutes 5

Turkce kalitesini olcen otomatik bir metrik yok. Rapordaki metin orneklerini
gozle karsilastirmak gerekiyor; bu bilincli bir tercih, referans metin olmadan
uretilen WER sayilari yaniltici olurdu.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from palaskript import catalog, paths  # noqa: E402
from palaskript.audio import SAMPLE_RATE, iter_windows, probe_duration  # noqa: E402
from palaskript.chapters import format_timestamp  # noqa: E402
from palaskript.resources import MODEL_CATALOG, Profile, detect  # noqa: E402
from palaskript.source import resolver, ytdlp_source  # noqa: E402

DEFAULT_MODELS = ["small", "medium", "large-v3-turbo"]
DEFAULT_BATCHES = [1, 4, 8]
_RSS_POLL_SECONDS = 0.25


@dataclass
class Result:
    model: str
    threads: int
    batch: int
    vad: bool
    seconds: float = 0.0
    peak_rss_gb: float = 0.0
    text: str = ""
    error: str | None = None
    audio_seconds: float = 0.0

    @property
    def rtf(self) -> float:
        """Gercek zaman katsayisi. 2.0 = sesin iki kati hizinda isleniyor."""
        return self.audio_seconds / self.seconds if self.seconds > 0 else 0.0

    @property
    def label(self) -> str:
        return f"{self.model} t{self.threads} b{self.batch}{'' if self.vad else ' (VAD kapali)'}"


# --------------------------------------------------------------- ses hazirligi


def prepare_slice(raw_input: str, slice_minutes: float, out_path: Path) -> Path:
    """Girdiden sabit bir kesit cikarip WAV olarak yaz.

    Tum yapilandirmalar birebir ayni sese bakmali, yoksa karsilastirma anlamsiz.
    Kesit videonun %30'undan aliniyor: acilis muzigi ve tanitim yerine asil
    konusmaya denk gelsin.
    """
    if ytdlp_source.is_url(raw_input):
        sources = resolver.resolve_one(raw_input)
        if not sources:
            raise SystemExit("Adres cozumlenemedi.")
        source = ytdlp_source.probe_full(sources[0].url or raw_input)
        print(f"Indiriliyor: {source.title}")
        work = paths.cache_dir() / "benchmark"
        audio = ytdlp_source.download_audio(
            source, work, progress=lambda f, m: print(f"\r  {m}", end="", flush=True)
        )
        print()
    else:
        audio = Path(raw_input)
        if not audio.exists():
            raise SystemExit(f"Dosya bulunamadi: {audio}")

    duration = probe_duration(audio)
    slice_seconds = min(slice_minutes * 60.0, duration)
    offset = max(0.0, min(duration * 0.30, duration - slice_seconds))

    print(
        f"Kesit aliniyor: {format_timestamp(offset)} - "
        f"{format_timestamp(offset + slice_seconds)} ({slice_seconds / 60:.1f} dk)"
    )

    collected: list[np.ndarray] = []
    total = 0
    want = int(slice_seconds * SAMPLE_RATE)
    for window in iter_windows(audio, window_seconds=60, start_at=offset, align_to_silence=False):
        collected.append(window.samples)
        total += len(window.samples)
        if total >= want:
            break

    samples = np.concatenate(collected)[:want] if collected else np.zeros(0, dtype=np.float32)
    if samples.size == 0:
        raise SystemExit("Sesten kesit alinamadi.")

    pcm16 = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(out_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm16.tobytes())
    return out_path


# ------------------------------------------------------------------- olcum


def run_single(wav: Path, model: str, threads: int, batch: int, vad: bool) -> dict:
    """Alt surecte tek bir yapilandirmayi calistir (bu fonksiyon cocukta calisir)."""
    from palaskript.engine.local import LocalWhisperEngine

    model_dir = catalog.ensure_model(model)
    profile = Profile(model=model, batch_size=batch, window_seconds=600, cpu_threads=threads)

    with wave.open(str(wav), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32767.0

    engine = LocalWhisperEngine(model_dir, profile, language=None)
    if not vad:
        original = engine._common_kwargs

        def no_vad(batch_size: int) -> dict:
            kwargs = original(batch_size)
            kwargs["vad_filter"] = False
            return kwargs

        engine._common_kwargs = no_vad  # type: ignore[method-assign]

    started = time.monotonic()
    segments = engine.transcribe_window(samples, offset=0.0, batch_size=batch)
    elapsed = time.monotonic() - started
    engine.close()

    return {
        "seconds": elapsed,
        "audio_seconds": len(samples) / SAMPLE_RATE,
        "text": " ".join(s.text for s in segments),
    }


def measure(wav: Path, model: str, threads: int, batch: int, vad: bool) -> Result:
    """Yapilandirmayi ayri surecte calistirip tepe RSS'i olc.

    Ayri surec sart: CTranslate2 model bellegini surec omru boyunca tutuyor,
    ayni surecte pes pese olcum yapilsa ikinci model birincinin bellegini de
    tasirdi ve sayilar anlamsiz olurdu.
    """
    result = Result(model=model, threads=threads, batch=batch, vad=vad)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        str(wav),
        model,
        str(threads),
        str(batch),
        "1" if vad else "0",
    ]

    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8"
    )
    monitor = psutil.Process(process.pid)
    peak = 0.0

    while process.poll() is None:
        try:
            rss = monitor.memory_info().rss
            for child in monitor.children(recursive=True):
                rss += child.memory_info().rss
            peak = max(peak, rss / 1024**3)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            break
        time.sleep(_RSS_POLL_SECONDS)

    stdout, stderr = process.communicate()
    result.peak_rss_gb = round(peak, 2)

    if process.returncode != 0:
        tail = (stderr or "").strip().splitlines()
        result.error = tail[-1] if tail else f"cikis kodu {process.returncode}"
        return result

    try:
        payload = json.loads((stdout or "").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        result.error = "cikti okunamadi"
        return result

    result.seconds = payload["seconds"]
    result.audio_seconds = payload["audio_seconds"]
    result.text = payload["text"]
    return result


# ------------------------------------------------------------------- rapor


def project_full_video(rtf: float, hours: float = 3.5) -> str:
    if rtf <= 0:
        return "-"
    return format_timestamp(hours * 3600 / rtf, always_hours=True)


def write_report(results: list[Result], path: Path, hw, slice_minutes: float) -> None:
    lines = [
        "# Transkript benchmark raporu",
        "",
        f"- Donanim: {hw.describe()}",
        f"- Kesit uzunlugu: {slice_minutes:.1f} dakika",
        "",
        "## Olcumler",
        "",
        "| Yapilandirma | Gercek zaman kat. | Tepe RAM | 3.5 saatlik video | Sure |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        if r.error:
            lines.append(f"| {r.label} | HATA | {r.peak_rss_gb:.2f} GB | - | {r.error} |")
            continue
        lines.append(
            f"| {r.label} | {r.rtf:.2f}x | {r.peak_rss_gb:.2f} GB | "
            f"{project_full_video(r.rtf)} | {r.seconds:.0f} sn |"
        )

    lines += [
        "",
        "## MODEL_CATALOG icin onerilen degerler",
        "",
        "Asagidaki tepe RSS olcumleri palaskript/resources.py icindeki",
        "`weights_gb` / `act_per_batch_gb` degerlerini duzeltmek icin kullanilir.",
        "",
        "| Model | Yigin | Olculen tepe RAM | Kataloktaki tahmin |",
        "|---|---|---|---|",
    ]
    for r in results:
        if r.error or not r.vad:
            continue
        spec = MODEL_CATALOG.get(r.model)
        estimate = f"{spec.ram_estimate_gb(r.batch):.2f} GB" if spec else "-"
        lines.append(f"| {r.model} | {r.batch} | {r.peak_rss_gb:.2f} GB | {estimate} |")

    lines += ["", "## Metin ornekleri (Turkce kalitesini gozle karsilastirin)", ""]
    for r in results:
        if r.error:
            continue
        sample = r.text[:900] + ("..." if len(r.text) > 900 else "")
        lines += [f"### {r.label}", "", sample or "(bos)", ""]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_table(results: list[Result]) -> None:
    print()
    print(f"{'Yapilandirma':<34}{'Hiz':>9}{'Tepe RAM':>11}{'3.5 saat':>12}")
    print("-" * 66)
    for r in results:
        if r.error:
            print(f"{r.label:<34}{'HATA':>9}{r.peak_rss_gb:>9.2f} GB{r.error[:12]:>12}")
            continue
        print(
            f"{r.label:<34}{r.rtf:>8.2f}x{r.peak_rss_gb:>9.2f} GB"
            f"{project_full_video(r.rtf):>12}"
        )
    print()


# -------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Alt surec modu: tek yapilandirma calistirip JSON yaz.
    if argv and argv[0] == "--worker":
        _, wav, model, threads, batch, vad = argv
        payload = run_single(Path(wav), model, int(threads), int(batch), vad == "1")
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    parser = argparse.ArgumentParser(description="Model, hiz ve bellek olcumu")
    parser.add_argument("input", help="YouTube adresi veya yerel dosya")
    parser.add_argument("--slice-minutes", type=float, default=8.0)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--threads", default="")
    parser.add_argument("--batch", default=",".join(str(b) for b in DEFAULT_BATCHES))
    parser.add_argument(
        "--no-vad-comparison",
        action="store_true",
        help="VAD acik/kapali karsilastirmasini atla",
    )
    parser.add_argument(
        "--simulate-ram",
        type=float,
        help="Dusuk bellekli makine profilini taklit et (sadece boyutlandirma mantigi)",
    )
    parser.add_argument("--out", type=Path, default=Path("benchmark-raporu.md"))
    args = parser.parse_args(argv)

    paths.ensure_dirs()
    hw = detect(simulate_ram_gb=args.simulate_ram)
    print(f"Donanim: {hw.describe()}")
    print(f"Bos disk: {hw.free_disk_gb:.1f} GB\n")

    threads_list = (
        [int(t) for t in args.threads.split(",") if t.strip()]
        if args.threads
        else sorted({hw.physical_cores, hw.logical_cores})
    )
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    batches = [int(b) for b in args.batch.split(",") if b.strip()]

    unknown = [m for m in models if m not in MODEL_CATALOG]
    if unknown:
        raise SystemExit(f"Bilinmeyen model: {', '.join(unknown)}")

    wav = paths.cache_dir() / "benchmark-slice.wav"
    prepare_slice(args.input, args.slice_minutes, wav)
    audio_minutes = probe_duration(wav) / 60

    configs: list[tuple[str, int, int, bool]] = []
    for model in models:
        for threads in threads_list:
            for batch in batches:
                configs.append((model, threads, batch, True))
    if not args.no_vad_comparison:
        # VAD etkisini olcmek icin tek bir referans yapilandirma yeter.
        configs.append((models[-1], threads_list[0], batches[-1], False))

    print(f"{len(configs)} yapilandirma calistirilacak.")
    print("Modeller ilk kullanimda inecek, bu biraz surebilir.\n")

    results: list[Result] = []
    for index, (model, threads, batch, vad) in enumerate(configs, start=1):
        label = f"{model} t{threads} b{batch}{'' if vad else ' (VAD kapali)'}"
        print(f"[{index}/{len(configs)}] {label} ... ", end="", flush=True)
        result = measure(wav, model, threads, batch, vad)
        results.append(result)
        if result.error:
            print(f"HATA: {result.error}")
        else:
            print(
                f"{result.rtf:.2f}x, tepe {result.peak_rss_gb:.2f} GB, "
                f"3.5 saat -> {project_full_video(result.rtf)}"
            )

    print_table(results)
    write_report(results, args.out, hw, audio_minutes)
    print(f"Rapor: {args.out.resolve()}")
    print("Turkce kalitesini raporun sonundaki metin orneklerinden karsilastirin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
