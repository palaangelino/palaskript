"""Donanim tespiti, model kapilama ve calisma ani bellek korumasi.

Uygulama 8 GB RAM'li GPU'suz makinelerde de calismak zorunda. Bu modul acilista
donanimi olcup hangi modelin, hangi yigin boyutunun ve hangi pencere boyunun
guvenli oldugunu belirliyor; is sirasinda da bos bellegi izleyip gerekirse
yigini kucultuyor.

RAM tahminleri (MODEL_CATALOG icindeki weights_gb / act_per_batch_gb) su an
olcume degil hesaba dayaniyor. scripts/benchmark.py bunlari gercek tepe RSS ile
degistirmek icin var; 8 GB hedefi tahminle birakilmamali.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

import psutil

# Python yorumlayicisi + Qt + onnxruntime + ctranslate2 calisma ani sabit yuku.
RUNTIME_OVERHEAD_GB = 0.35

# Bellek korumasi bu esigin altina inince yigini yariya boler.
MEMORY_FLOOR_GB = 1.2


@dataclass(frozen=True, slots=True)
class ModelSpec:
    name: str
    label: str
    download_gb: float
    weights_gb: float
    act_per_batch_gb: float
    quality: str
    # Bu model icin gereken en dusuk TOPLAM RAM. Nominal 8 GB'lik makineler
    # ~7.8 GB, nominal 16 GB'likler ~15.8 GB rapor ediyor (paylasimli ekran
    # bellegi dusuluyor), bu yuzden esikler nominal degerin altinda tutuluyor.
    min_total_ram_gb: float

    def ram_estimate_gb(self, batch_size: int) -> float:
        return RUNTIME_OVERHEAD_GB + self.weights_gb + self.act_per_batch_gb * batch_size


MODEL_CATALOG: dict[str, ModelSpec] = {
    "small": ModelSpec(
        name="small",
        label="Small (hizli, Turkce kalitesi zayif)",
        download_gb=0.25,
        weights_gb=0.26,
        act_per_batch_gb=0.10,
        quality="Zayif",
        min_total_ram_gb=0.0,
    ),
    "medium": ModelSpec(
        name="medium",
        label="Medium (dengeli)",
        download_gb=1.5,
        weights_gb=0.78,
        act_per_batch_gb=0.22,
        quality="Orta",
        min_total_ram_gb=0.0,
    ),
    "large-v3-turbo": ModelSpec(
        name="large-v3-turbo",
        label="Large v3 Turbo (onerilen)",
        download_gb=1.6,
        weights_gb=0.83,
        act_per_batch_gb=0.26,
        quality="Iyi",
        min_total_ram_gb=7.0,
    ),
    "large-v3": ModelSpec(
        name="large-v3",
        label="Large v3 (en iyi, yavas)",
        download_gb=3.1,
        weights_gb=1.62,
        act_per_batch_gb=0.51,
        quality="En iyi",
        min_total_ram_gb=15.0,
    ),
}

DEFAULT_MODEL = "large-v3-turbo"
FALLBACK_MODEL = "small"


@dataclass(frozen=True, slots=True)
class HardwareInfo:
    total_ram_gb: float
    available_ram_gb: float
    physical_cores: int
    logical_cores: int
    free_disk_gb: float

    def describe(self) -> str:
        return (
            f"{self.total_ram_gb:.1f} GB RAM ({self.available_ram_gb:.1f} GB bos), "
            f"{self.physical_cores} fiziksel / {self.logical_cores} mantiksal cekirdek"
        )


@dataclass(frozen=True, slots=True)
class Profile:
    """Bir isin calisacagi somut ayarlar."""

    model: str
    batch_size: int
    window_seconds: int
    cpu_threads: int
    compute_type: str = "int8"

    def describe(self) -> str:
        return (
            f"{self.model}, yigin {self.batch_size}, "
            f"{self.window_seconds // 60} dk pencere, {self.cpu_threads} is parcacigi"
        )


def detect(simulate_ram_gb: float | None = None, disk_path: Path | None = None) -> HardwareInfo:
    """Donanimi olc.

    simulate_ram_gb, benchmark ve testler icin dusuk bellekli makineyi taklit eder.
    Bu yalnizca boyutlandirma mantigini test eder, gercek bellek baskisini degil.
    """
    vm = psutil.virtual_memory()
    if simulate_ram_gb:
        total = simulate_ram_gb
        # Taklit modda bos bellegi orantili varsayiyoruz: Windows 11 + tarayici
        # acikken tipik olarak toplamin ~%60'i bos kaliyor.
        available = simulate_ram_gb * 0.6
    else:
        total = vm.total / 1024**3
        available = vm.available / 1024**3

    physical = psutil.cpu_count(logical=False) or 1
    logical = psutil.cpu_count(logical=True) or physical

    target = disk_path or Path.home()
    try:
        free_disk = shutil.disk_usage(target).free / 1024**3
    except OSError:
        free_disk = 0.0

    return HardwareInfo(
        total_ram_gb=round(total, 2),
        available_ram_gb=round(available, 2),
        physical_cores=physical,
        logical_cores=logical,
        free_disk_gb=round(free_disk, 2),
    )


def usable_budget_gb(hw: HardwareInfo) -> float:
    """Transkripsiyona ayrilabilecek bellek.

    Bos bellegin tamamini almiyoruz: kullanici is sirasinda tarayici acacak ve
    Windows'un da nefes almasi gerekiyor. Toplam RAM'in yarisini da asmiyoruz,
    aksi halde 8 GB'lik makinede su an bos gorunen bellege guvenip takasa dusebiliriz.
    """
    return max(0.5, min(hw.available_ram_gb * 0.75, hw.total_ram_gb * 0.55))


def available_models(hw: HardwareInfo) -> dict[str, str | None]:
    """Her model icin None (kullanilabilir) veya engel sebebi dondurur."""
    result: dict[str, str | None] = {}
    for name, spec in MODEL_CATALOG.items():
        if hw.total_ram_gb < spec.min_total_ram_gb:
            need = int(round(spec.min_total_ram_gb / 8.0) * 8) or 8
            result[name] = (
                f"{spec.name} icin {need} GB RAM gerekir, sistemde {hw.total_ram_gb:.1f} GB var"
            )
        else:
            result[name] = None
    return result


def choose_profile(
    hw: HardwareInfo,
    *,
    model_override: str | None = None,
    threads_override: int | None = None,
    low_memory_mode: bool = False,
) -> Profile:
    """Donanima gore model, yigin boyutu, pencere ve is parcacigi sec.

    Katmanlar toplam RAM'e gore; nominal 8 GB makineler ~7.8 GB rapor ettigi icin
    esikler 8.0 degil 6.5 ve 11.5. Duz "< 8" karsilastirmasi gercek 8 GB'lik
    makineleri yanlislikla en dusuk profile dusururdu.
    """
    if low_memory_mode:
        model = model_override or FALLBACK_MODEL
        if MODEL_CATALOG[model].min_total_ram_gb > hw.total_ram_gb:
            model = FALLBACK_MODEL
        return Profile(
            model=model,
            batch_size=1,
            window_seconds=300,
            cpu_threads=threads_override or max(1, hw.physical_cores - 1),
        )

    if hw.total_ram_gb < 6.5:
        model, batch, window = FALLBACK_MODEL, 1, 300
    elif hw.total_ram_gb < 11.5:
        model, batch, window = DEFAULT_MODEL, 4, 300
    else:
        model, batch, window = DEFAULT_MODEL, 8, 600

    if model_override:
        model = model_override

    spec = MODEL_CATALOG.get(model)
    if spec is None:
        raise ValueError(f"Bilinmeyen model: {model}")

    # Elle secilen model katman varsayilanindan agirsa yigini butceye sigacak
    # sekilde kucult. Kullanici large-v3'u zorlayabiliyor ama yigin buna uyar.
    budget = usable_budget_gb(hw)
    while batch > 1 and spec.ram_estimate_gb(batch) > budget:
        batch //= 2

    threads = threads_override or hw.physical_cores
    threads = max(1, min(threads, hw.logical_cores))

    return Profile(model=model, batch_size=batch, window_seconds=window, cpu_threads=threads)


def fits_in_memory(spec: ModelSpec, batch_size: int, hw: HardwareInfo) -> bool:
    return spec.ram_estimate_gb(batch_size) <= usable_budget_gb(hw)


class InsufficientDiskError(RuntimeError):
    pass


def check_disk_for_model(model: str, hw: HardwareInfo, *, headroom_gb: float = 1.0) -> None:
    """Model indirmeden once yer var mi bak. Yarim inen model sessiz hataya doner."""
    spec = MODEL_CATALOG[model]
    needed = spec.download_gb + headroom_gb
    if hw.free_disk_gb < needed:
        raise InsufficientDiskError(
            f"{spec.name} modeli icin {needed:.1f} GB bos alan gerekiyor, "
            f"diskte {hw.free_disk_gb:.1f} GB var. Yer acip tekrar deneyin."
        )


class MemoryGuard:
    """Pencere sinirlarinda bos bellegi izleyip yigini kuculten koruma.

    Tek yonlu calisiyor: yigin duser, geri yukselmez. Bellek boslasti diye tekrar
    buyutmek uzun islerde salinima yol aciyor (buyut, bellek dolar, kucult, tekrarla)
    ve her degisiklik model durumunu yeniden kurmayi gerektiriyor. Bir isin
    yavaslamasi, ortasinda takasa dusmesinden iyidir.
    """

    def __init__(self, profile: Profile, *, floor_gb: float = MEMORY_FLOOR_GB) -> None:
        self.initial_batch = profile.batch_size
        self.batch_size = profile.batch_size
        self.floor_gb = floor_gb
        self.reductions = 0

    def check(self) -> tuple[int, str | None]:
        """Pencere basinda cagrilir.

        (kullanilacak_yigin, kullaniciya_gosterilecek_mesaj) dondurur.
        """
        if self.batch_size <= 1:
            return self.batch_size, None

        available = psutil.virtual_memory().available / 1024**3
        if available >= self.floor_gb:
            return self.batch_size, None

        self.batch_size = max(1, self.batch_size // 2)
        self.reductions += 1
        return self.batch_size, (
            f"Bos bellek {available:.1f} GB'a dustu, yigin boyutu {self.batch_size} yapildi "
            "(islem yavaslar, is devam ediyor)"
        )


def lower_process_priority() -> bool:
    """Isci sureci arka plan onceligine al.

    6 saatlik bir is sururken bilgisayarin kullanilabilir kalmasi icin. Basarisiz
    olursa is yine calisir, sadece daha fazla CPU payi alir.
    """
    try:
        proc = psutil.Process(os.getpid())
        if hasattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS"):
            proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:
            proc.nice(10)
        return True
    except (psutil.Error, OSError, ValueError):
        return False


def profile_with_batch(profile: Profile, batch_size: int) -> Profile:
    return replace(profile, batch_size=batch_size)
