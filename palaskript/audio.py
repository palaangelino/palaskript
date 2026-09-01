"""PyAV tabanli pencereli ses akisi.

Sesi tek seferde bellege almiyoruz. Bu, tepe bellegi video uzunlugundan bagimsiz
kiliyor: 3.5 saatlik video ile 10 dakikalik video ayni RAM'i kullaniyor. 8 GB
hedefini mumkun kilan yapisal karar bu.

Pencere sinirlari ayni zamanda dogal devam noktasi: cokme sonrasi yeniden
baslatmada konteynere o saniyeye seek edip devam ediyoruz, bastan cozmuyoruz.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np

SAMPLE_RATE = 16000

# Pencere sinirini sessizlige hizalamak icin sinirin iki yaninda taranan alan.
BOUNDARY_SLACK_SECONDS = 15.0

# Sessizlik bulunamazsa uygulanan bindirme. Dikiste tekrar eden metin
# segments.stitch_windows tarafindan atiliyor.
FALLBACK_OVERLAP_SECONDS = 5.0

# Kesim noktasi sayilmasi icin gereken en kisa sessizlik.
MIN_SILENCE_SECONDS = 0.30

_RMS_FRAME_MS = 20


class AudioDecodeError(RuntimeError):
    pass


@dataclass(slots=True)
class AudioWindow:
    """Motora verilecek tek bir ses penceresi."""

    index: int
    start: float
    end: float
    samples: np.ndarray
    # Sessizlik bulunamadigi icin onceki pencereyle bindirme uygulandiysa True.
    # segments katmani dikisi buna gore temizliyor.
    overlapped: bool = False

    @property
    def duration(self) -> float:
        return len(self.samples) / SAMPLE_RATE


def probe_duration(path: Path | str) -> float:
    """Sesin saniye cinsinden suresi. ETA ve ilerleme hesabi bunu kullaniyor."""
    try:
        with av.open(str(path)) as container:
            if container.duration is not None:
                return float(container.duration) / av.time_base
            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream is not None and stream.duration and stream.time_base:
                return float(stream.duration * stream.time_base)
    except (av.FFmpegError, StopIteration, OSError) as exc:
        raise AudioDecodeError(f"Ses suresi okunamadi: {path} ({exc})") from exc
    raise AudioDecodeError(f"Ses suresi belirlenemedi: {path}")


def _rms_envelope(samples: np.ndarray) -> np.ndarray:
    frame = int(SAMPLE_RATE * _RMS_FRAME_MS / 1000)
    if frame <= 0 or len(samples) < frame:
        return np.array([], dtype=np.float32)
    usable = (len(samples) // frame) * frame
    frames = samples[:usable].reshape(-1, frame)
    return np.sqrt(np.mean(frames.astype(np.float32) ** 2, axis=1))


def find_silence_cut(samples: np.ndarray, target: int, slack: int) -> int | None:
    """target ornegi civarinda kesilecek en iyi sessiz noktayi bul.

    Konusma videolarinda duraklamalar uzun oldugu icin bu neredeyse her zaman
    tutuyor. Bulunamazsa None doner ve arayan bindirmeye duser.

    Esik mutlak degil, bolgenin kendi DINAMIK ARALIGINA gore hesaplaniyor.

    Iki tuzak var, ikisinden de kacinmak gerekiyor:

    - Sadece gurultu tabanini bir katsayiyla carpmak: seviyesi duz olan bir
      kayitta (kesintisiz konusma) esik tum sinyalin ustune cikiyor ve her yer
      "sessiz" sayiliyor. Bu yuzden once anlamli bir dinamik aralik var mi diye
      bakiyoruz.
    - Tabani yuksek bir yuzdelikle olcmek: 20 saniyelik bir bolgedeki 1
      saniyelik duraklama karelerin sadece %5'i eder, 10. yuzdelik hala konusma
      seviyesini gosterir ve gercek duraklama gorunmez olur. Taban icin 1.
      yuzdelik, tipik seviye icin ortanca kullaniyoruz.
    """
    lo = max(0, target - slack)
    hi = min(len(samples), target + slack)
    if hi - lo < SAMPLE_RATE * MIN_SILENCE_SECONDS:
        return None

    region = samples[lo:hi]
    rms = _rms_envelope(region)
    if rms.size == 0:
        return None

    floor = float(np.percentile(rms, 1))
    typical = float(np.median(rms))

    # Seviye neredeyse duz: kesintisiz konusma, kesilecek duraklama yok.
    if typical < floor * 3.0:
        return None

    threshold = max(floor + 0.25 * (typical - floor), 1e-6)
    quiet = rms < threshold
    if not quiet.any():
        return None

    frame = int(SAMPLE_RATE * _RMS_FRAME_MS / 1000)
    min_frames = max(1, int(MIN_SILENCE_SECONDS * 1000 / _RMS_FRAME_MS))

    best_start = best_len = -1
    run_start = -1
    for i, is_quiet in enumerate(quiet):
        if is_quiet:
            if run_start < 0:
                run_start = i
        elif run_start >= 0:
            if (i - run_start) > best_len:
                best_start, best_len = run_start, i - run_start
            run_start = -1
    if run_start >= 0 and (len(quiet) - run_start) > best_len:
        best_start, best_len = run_start, len(quiet) - run_start

    if best_len < min_frames:
        return None

    center_frame = best_start + best_len // 2
    return lo + center_frame * frame


def iter_windows(
    path: Path | str,
    window_seconds: int,
    *,
    start_at: float = 0.0,
    align_to_silence: bool = True,
) -> Iterator[AudioWindow]:
    """Sesi 16 kHz mono float32 pencereler halinde akit.

    start_at, ara kayittan devam ederken kullanilir: konteyner o saniyeye
    seek eder ve onceki bolumu yeniden cozmez.
    """
    slack = int(BOUNDARY_SLACK_SECONDS * SAMPLE_RATE) if align_to_silence else 0
    target = int(window_seconds * SAMPLE_RATE)
    if target <= 0:
        raise ValueError("window_seconds pozitif olmali")

    try:
        container = av.open(str(path))
    except (av.FFmpegError, OSError) as exc:
        raise AudioDecodeError(f"Ses acilamadi: {path} ({exc})") from exc

    overlap_samples = int(FALLBACK_OVERLAP_SECONDS * SAMPLE_RATE)

    try:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise AudioDecodeError(f"Dosyada ses akisi yok: {path}")
        stream.thread_type = "AUTO"

        if start_at > 0:
            container.seek(int(start_at * av.time_base), any_frame=False, backward=True)

        resampler = av.audio.resampler.AudioResampler(
            format="fltp", layout="mono", rate=SAMPLE_RATE
        )

        # Tek buyuyen tampon: pending, zaman ekseninde pending_start'ta basliyor.
        chunks: list[np.ndarray] = []
        pending = np.empty(0, dtype=np.float32)
        pending_start = start_at
        index = 0
        next_overlapped = False

        def _collect(frames) -> None:
            for resampled in frames:
                arr = resampled.to_ndarray()
                mono = arr[0] if arr.ndim > 1 else arr
                chunks.append(np.ascontiguousarray(mono, dtype=np.float32))

        def _merge() -> np.ndarray:
            nonlocal pending, chunks
            if chunks:
                pending = np.concatenate([pending, *chunks]) if pending.size else np.concatenate(chunks)
                chunks = []
            return pending

        def _emit_ready(min_length: int) -> Iterator[AudioWindow]:
            nonlocal pending, pending_start, index, next_overlapped
            while len(pending) >= min_length:
                cut = target
                aligned = False
                if align_to_silence:
                    found = find_silence_cut(pending, target, slack)
                    # Kesim en az yarim pencere ilerlemeli. Aksi halde hedefin
                    # cok gerisinde bulunan bir sessizlik minik pencereler
                    # uretip dongusel bir yavaslamaya yol acar.
                    if found is not None and found >= max(1, target // 2):
                        cut = found
                        aligned = True

                piece = pending[:cut]
                yield AudioWindow(
                    index=index,
                    start=pending_start,
                    end=pending_start + len(piece) / SAMPLE_RATE,
                    samples=piece,
                    overlapped=next_overlapped,
                )
                index += 1

                if aligned or not align_to_silence:
                    # Temiz kesim (veya hizalama kapali): bir sonraki pencere
                    # tam burada basliyor, bindirme yok.
                    advance = cut
                    next_overlapped = False
                else:
                    # Sessizlik yok. Kelimeyi ortadan bolmemek icin bir sonraki
                    # pencereyi biraz geriden basliyoruz; dikiste olusan tekrari
                    # segments.stitch_windows temizliyor.
                    advance = max(1, cut - overlap_samples)
                    next_overlapped = True

                pending_start += advance / SAMPLE_RATE
                pending = pending[advance:]

        for frame in container.decode(stream):
            _collect(resampler.resample(frame))
            if sum(len(c) for c in chunks) + len(pending) >= target + slack:
                _merge()
                yield from _emit_ready(target + slack)

        # Konteyner bitti, resampler'da kalani bosalt.
        _collect(resampler.resample(None))
        _merge()

        # Kuyruk: esik target+slack olsaydi son pencere target+slack kadar
        # buyuyebilirdi (10 dakikalik ayarda 25 dakika). Esigi target'a cekip
        # kuyrugu da normal boyutta pencerelere boluyoruz.
        yield from _emit_ready(target)

        if pending.size:
            yield AudioWindow(
                index=index,
                start=pending_start,
                end=pending_start + len(pending) / SAMPLE_RATE,
                samples=pending,
                overlapped=next_overlapped,
            )
    finally:
        container.close()


def export_archive_audio(src: Path, dst: Path, *, codec: str = "opus") -> Path:
    """Sesi arsivlik sikistirilmis formata yaz.

    Bu, sikistirmanin dogru kullanildigi tek yer: transkripsiyon icin degil,
    videoyu silip sesi saklamak icin. Opus 24 kbps mono 3.5 saatlik konusmayi
    ~38 MB'a indiriyor ve konusma icin tasarlanmis gercek bir codec.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with av.open(str(src)) as inp:
            in_stream = next((s for s in inp.streams if s.type == "audio"), None)
            if in_stream is None:
                raise AudioDecodeError(f"Dosyada ses akisi yok: {src}")
            in_stream.thread_type = "AUTO"

            with av.open(str(dst), mode="w") as out:
                if codec == "flac":
                    out_stream = out.add_stream("flac", rate=SAMPLE_RATE)
                else:
                    out_stream = out.add_stream("libopus", rate=48000)
                    out_stream.bit_rate = 24000
                out_stream.layout = "mono"

                resampler = av.audio.resampler.AudioResampler(
                    format=out_stream.format.name,
                    layout="mono",
                    rate=out_stream.rate,
                )
                for frame in inp.decode(in_stream):
                    for res in resampler.resample(frame):
                        res.pts = None
                        for packet in out_stream.encode(res):
                            out.mux(packet)
                for packet in out_stream.encode(None):
                    out.mux(packet)
    except (av.FFmpegError, OSError) as exc:
        raise AudioDecodeError(f"Ses arsivlenemedi: {exc}") from exc
    return dst
