"""Donanim profili ve bellek korumasi.

En kritik senaryo: nominal 8 GB'lik makine ~7.8 GB rapor ediyor. Duz "< 8"
karsilastirmasi bu makineleri en dusuk profile dusururdu; esiklerin bunu dogru
ele aldigini burada dogruluyoruz.
"""

from __future__ import annotations

import pytest

from palaskript.resources import (
    DEFAULT_MODEL,
    FALLBACK_MODEL,
    MODEL_CATALOG,
    HardwareInfo,
    InsufficientDiskError,
    MemoryGuard,
    Profile,
    available_models,
    check_disk_for_model,
    choose_profile,
    detect,
    usable_budget_gb,
)


def hw(total: float, *, available: float | None = None, cores: int = 4, disk: float = 100.0):
    return HardwareInfo(
        total_ram_gb=total,
        available_ram_gb=available if available is not None else total * 0.6,
        physical_cores=cores,
        logical_cores=cores * 2,
        free_disk_gb=disk,
    )


class TestProfileSelection:
    def test_nominal_8gb_machine_gets_turbo_not_fallback(self):
        # Nominal 8 GB makineler ~7.8 GB rapor ediyor. Bu testin amaci
        # esiklerin 8.0 degil 6.5 oldugunu korumak.
        profile = choose_profile(hw(7.8))
        assert profile.model == DEFAULT_MODEL
        assert profile.batch_size == 4
        assert profile.window_seconds == 300

    @pytest.mark.parametrize("total", [7.6, 7.8, 7.9, 8.0])
    def test_all_reported_8gb_variants_get_turbo(self, total: float):
        assert choose_profile(hw(total)).model == DEFAULT_MODEL

    def test_nominal_16gb_machine_gets_large_window(self):
        profile = choose_profile(hw(15.8))
        assert profile.model == DEFAULT_MODEL
        assert profile.batch_size == 8
        assert profile.window_seconds == 600

    def test_genuinely_small_machine_falls_back(self):
        profile = choose_profile(hw(4.0))
        assert profile.model == FALLBACK_MODEL
        assert profile.batch_size == 1

    def test_threads_default_to_physical_cores(self):
        assert choose_profile(hw(15.8, cores=6)).cpu_threads == 6

    def test_threads_override_is_capped_at_logical(self):
        assert choose_profile(hw(15.8, cores=4), threads_override=99).cpu_threads == 8

    def test_low_memory_mode_is_most_conservative(self):
        profile = choose_profile(hw(15.8), low_memory_mode=True)
        assert profile.batch_size == 1
        assert profile.window_seconds == 300
        assert profile.model == FALLBACK_MODEL

    def test_low_memory_mode_rejects_model_that_does_not_fit(self):
        profile = choose_profile(hw(7.8), model_override="large-v3", low_memory_mode=True)
        assert profile.model == FALLBACK_MODEL

    def test_manual_large_v3_shrinks_batch_to_fit_budget(self):
        # Kullanici 16 GB'da large-v3 zorlarsa yigin butceye gore kuculmeli.
        machine = hw(15.8)
        profile = choose_profile(machine, model_override="large-v3")
        assert profile.model == "large-v3"
        spec = MODEL_CATALOG["large-v3"]
        assert spec.ram_estimate_gb(profile.batch_size) <= usable_budget_gb(machine)

    def test_unknown_model_raises(self):
        with pytest.raises(ValueError):
            choose_profile(hw(15.8), model_override="yok-boyle-model")


class TestModelGating:
    def test_large_v3_blocked_on_8gb(self):
        reason = available_models(hw(7.8))["large-v3"]
        assert reason is not None
        assert "16 GB" in reason

    def test_large_v3_allowed_on_16gb(self):
        assert available_models(hw(15.8))["large-v3"] is None

    def test_turbo_blocked_on_4gb_but_small_allowed(self):
        gates = available_models(hw(4.0))
        assert gates["large-v3-turbo"] is not None
        assert gates["small"] is None


class TestBudget:
    def test_budget_never_exceeds_half_of_total(self):
        # Bos bellek yuksek gorunse bile toplamin yarisini asmamali: kullanici
        # is sirasinda tarayici acacak.
        machine = hw(8.0, available=7.5)
        assert usable_budget_gb(machine) <= 8.0 * 0.55 + 1e-9

    def test_budget_tracks_available_when_memory_is_tight(self):
        machine = hw(16.0, available=2.0)
        assert usable_budget_gb(machine) == pytest.approx(1.5)


class TestMemoryGuard:
    def test_halves_batch_when_memory_drops(self, monkeypatch):
        guard = MemoryGuard(Profile("large-v3-turbo", 8, 600, 4), floor_gb=99999)
        batch, note = guard.check()
        assert batch == 4
        assert note is not None and "yığın" in note

    def test_keeps_batch_when_memory_is_fine(self):
        guard = MemoryGuard(Profile("large-v3-turbo", 8, 600, 4), floor_gb=0.0)
        batch, note = guard.check()
        assert batch == 8
        assert note is None

    def test_never_drops_below_one_and_stops_reporting(self):
        guard = MemoryGuard(Profile("small", 8, 300, 4), floor_gb=99999)
        for _ in range(10):
            batch, _ = guard.check()
        assert batch == 1
        # 1'e indikten sonra bos yere uyari uretmemeli.
        assert guard.check() == (1, None)

    def test_reduction_is_one_way(self):
        """Bellek boslasa bile yigin geri buyumemeli: salinimi onlemek icin."""
        guard = MemoryGuard(Profile("large-v3-turbo", 8, 600, 4), floor_gb=99999)
        guard.check()
        guard.floor_gb = 0.0
        batch, note = guard.check()
        assert batch == 4
        assert note is None


class TestDisk:
    def test_raises_when_disk_is_too_small(self):
        with pytest.raises(InsufficientDiskError) as excinfo:
            check_disk_for_model("large-v3", hw(15.8, disk=1.0))
        assert "GB" in str(excinfo.value)

    def test_passes_when_disk_is_sufficient(self):
        check_disk_for_model("large-v3", hw(15.8, disk=50.0))


class TestDetect:
    def test_simulate_ram_overrides_measurement(self):
        info = detect(simulate_ram_gb=8.0)
        assert info.total_ram_gb == 8.0
        assert info.available_ram_gb == pytest.approx(4.8)

    def test_real_detection_is_sane(self):
        info = detect()
        assert info.total_ram_gb > 0
        assert info.physical_cores >= 1
        assert info.logical_cores >= info.physical_cores


class TestRamEstimates:
    def test_turbo_needs_much_less_than_large_v3(self):
        """Turbo'nun 8 GB varsayilani olmasinin gerekcesi bu fark."""
        turbo = MODEL_CATALOG["large-v3-turbo"].ram_estimate_gb(4)
        large = MODEL_CATALOG["large-v3"].ram_estimate_gb(4)
        assert turbo < large * 0.65

    def test_estimates_grow_with_batch_size(self):
        spec = MODEL_CATALOG["large-v3-turbo"]
        assert spec.ram_estimate_gb(8) > spec.ram_estimate_gb(4) > spec.ram_estimate_gb(1)
