"""Ilerleme cubugu.

Isik bandinin gercekten hareket ettigini ekran goruntusu kanitlamiyor; iki
farkli evrede cizilen goruntulerin FARKLI oldugunu dogruluyoruz. Animasyon
sessizce durursa bu test yakalar.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from palaskript.ui.progress import ProgressCell, ShimmerBar  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _pixels(bar: ShimmerBar) -> bytes:
    image = bar.grab().toImage()
    return image.constBits().tobytes()


class TestValue:
    def test_clamps_out_of_range(self, app):
        bar = ShimmerBar()
        bar.setValue(-10)
        assert bar.value() == 0
        bar.setValue(250)
        assert bar.value() == 100

    def test_stores_fractional_values(self, app):
        bar = ShimmerBar()
        bar.setValue(41.6)
        assert bar.value() == pytest.approx(41.6)


class TestShimmer:
    def test_timer_runs_only_while_active(self, app):
        """Kuyrukta elli is varken hepsini canlandirmak bosuna CPU yakar."""
        bar = ShimmerBar()
        assert not bar._timer.isActive()

        bar.setActive(True)
        assert bar._timer.isActive()

        bar.setActive(False)
        assert not bar._timer.isActive()

    def test_repeated_set_active_does_not_restart(self, app):
        bar = ShimmerBar()
        bar.setActive(True)
        bar.setActive(True)
        assert bar._timer.isActive()

    def test_band_actually_moves(self, app):
        """Iki evre arasinda cizim degismeli, yoksa animasyon durmus demektir."""
        bar = ShimmerBar()
        bar.resize(200, 7)
        bar.setValue(60)
        bar.setActive(True)

        bar._phase = 0.15
        first = _pixels(bar)
        bar._phase = 0.65
        second = _pixels(bar)

        assert first != second

    def test_inactive_bar_is_static(self, app):
        """Band kapaliyken evre degisse bile goruntu ayni kalmali."""
        bar = ShimmerBar()
        bar.resize(200, 7)
        bar.setValue(60)
        bar.setActive(False)

        bar._phase = 0.15
        first = _pixels(bar)
        bar._phase = 0.65
        second = _pixels(bar)

        assert first == second

    def test_phase_wraps_around(self, app):
        bar = ShimmerBar()
        bar._phase = 0.99
        for _ in range(5):
            bar._advance()
        assert 0.0 <= bar._phase < 1.0

    def test_zero_progress_draws_no_fill(self, app):
        """Bos cubuk ile 0 degerli cubuk ayni gorunmeli."""
        empty = ShimmerBar()
        empty.resize(200, 7)
        empty.setValue(0)

        other = ShimmerBar()
        other.resize(200, 7)
        other.setValue(0)
        other.setActive(True)

        assert _pixels(empty) == _pixels(other)


class TestProgressCell:
    def test_percentage_comes_before_the_bar(self, app):
        """Yuzde BASTA olmali: cubugun icinde okunmuyordu."""
        cell = ProgressCell()
        layout = cell.layout()
        assert layout.itemAt(0).widget() is cell.percent
        assert layout.itemAt(1).widget() is cell.bar

    def test_update_state_sets_everything(self, app):
        cell = ProgressCell()
        cell.update_state(41.6, active=True)
        assert cell.percent.text() == "41%"
        assert cell.bar.value() == pytest.approx(41.6)
        assert cell.bar._timer.isActive()

    def test_finished_job_stops_the_shimmer(self, app):
        cell = ProgressCell()
        cell.update_state(100, active=True)
        cell.update_state(100, active=False)
        assert cell.percent.text() == "100%"
        assert not cell.bar._timer.isActive()

    def test_percentage_column_width_is_stable(self, app):
        """Sayi buyudukce cubuk kaymamali."""
        cell = ProgressCell()
        cell.update_state(5, active=False)
        narrow = cell.percent.minimumWidth()
        cell.update_state(100, active=False)
        assert cell.percent.minimumWidth() == narrow
