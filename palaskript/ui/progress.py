"""Kuyruk tablosundaki ilerleme cubugu.

Motor segmentleri YIGIN YIGIN uretiyor: yigin boyutu 8 iken bir yigin yaklasik
dort dakikalik ses demek. Yani bes dakikalik bir videoda topu topu bir iki
gercek bildirim geliyor ve cubuk %15'ten %37'ye, oradan %100'e sicriyor.
Yigini kucultmek cozum degil, olculdu: yavaslatiyor.

Cozum aradaki bosluğu HESAPLAMAK. Elimizde hiz bilgisi zaten var (kalan sure
tahmini), cubugu onunla ilerletiyoruz:

- Kalan sure biliniyorsa dogrusal ilerliyor: her saniye, o saniyede yapilmasi
  beklenen kadar.
- Bilinmiyorsa (model bellege yuklenirken oldugu gibi) asamanin sonuna dogru
  gittikce yavaslayarak yaklasiyor. Ne zaman bitecegini bilmiyoruz ama
  calistigimizi gosteriyoruz ve bitmis gibi yapmiyoruz.

Uc kural hicbir zaman bozulmuyor:

1. Cubuk GERI GITMIYOR. Tahmin gercegin onune gecmisse yeni gercek deger
   gelince geri sarmiyor, gercek deger yetisene kadar bekliyor.
2. Icinde bulunulan asamanin sonunu ASMIYOR. Yazma asamasindaki bir tahmin
   belge yazma payina tasamaz.
3. Is gercekten bitmeden %100 OLMUYOR (stages.CEILING). Bitmeyen bir isi
   bitmis gostermek, gec kalmis bir cubuktan kotudur.
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from .. import stages
from . import theme

BAR_HEIGHT = 7
BAR_RADIUS = 3.5

# Cubugun en dar hali. Bunu vermezsek sutun "icerige gore" daralirken cubugu
# sifira indiriyor: ozel widget'in kendiliginden bir genislik ipucu yok.
BAR_MIN_WIDTH = 110

# Isik bandinin bir uctan digerine gecme suresi.
SHIMMER_PERIOD_MS = 1500
FPS = 30

# Bandin genisligi, dolgunun yuzdesi olarak.
SHIMMER_WIDTH = 0.35

# Hiz bilgisi yokken asamanin sonuna yaklasma zaman sabiti (saniye). Buyudukce
# daha temkinli ilerliyor. Model yukleme tipik olarak 30-60 saniye suruyor.
UNKNOWN_RATE_TAU = 40.0

# Hiz bilinmezken asamanin ne kadarina kadar ilerlenebilir. Ustel yaklasma
# teoride sinira hic varmiyor ama kayan noktada uzun surede tam oturuyor;
# bu pay, ne zaman bitecegini bilmedigimiz bir asamayi bitmis gostermemizi
# engelliyor.
UNKNOWN_RATE_MAX_SPAN = 0.97


class ShimmerBar(QWidget):
    """Ince ilerleme cubugu, uzerinden gecen isik bandiyla."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self._active = False
        self._phase = 0.0

        self.setFixedHeight(BAR_HEIGHT)
        self.setMinimumWidth(BAR_MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._timer = QTimer(self)
        self._timer.setInterval(1000 // FPS)
        self._timer.timeout.connect(self._advance)

    # ------------------------------------------------------------- durum

    def value(self) -> float:
        return self._value

    def setValue(self, percent: float) -> None:  # noqa: N802 - Qt adlandirmasi
        percent = max(0.0, min(100.0, float(percent)))
        if percent != self._value:
            self._value = percent
            self.update()

    def setActive(self, active: bool) -> None:  # noqa: N802 - Qt adlandirmasi
        """Isik bandini baslat veya durdur.

        Yalnizca gercekten islenen satir icin acilmali.
        """
        if active == self._active:
            return
        self._active = active
        if active:
            self._timer.start()
        else:
            self._timer.stop()
            self._phase = 0.0
        self.update()

    def _advance(self) -> None:
        step = (1000 / FPS) / SHIMMER_PERIOD_MS
        self._phase = (self._phase + step) % 1.0
        self.update()

    # ------------------------------------------------------------- cizim

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802 - Qt imzasi
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        track = QPainterPath()
        track.addRoundedRect(rect, BAR_RADIUS, BAR_RADIUS)

        painter.fillPath(track, QColor(theme.SURFACE_SUNKEN))
        painter.strokePath(track, QColor(theme.BORDER))

        # Band TUM cubuk boyunca geciyor, yalnizca dolgunun uzerinde degil.
        # Ilerleme %15'teyken dolgu birkac piksel genisliginde kaliyor ve
        # bandi oraya hapsetmek onu gorunmez yapiyordu.
        if self._active:
            self._sweep(painter, rect, track, QColor(theme.ACCENT), 60)

        if self._value <= 0:
            return

        fill_width = rect.width() * (self._value / 100.0)
        # Cok kucuk degerlerde yuvarlak kose sigmiyor; en az kose capi kadar.
        fill_width = max(fill_width, BAR_RADIUS * 2)
        fill_rect = QRectF(rect.left(), rect.top(), fill_width, rect.height())

        fill = QPainterPath()
        fill.addRoundedRect(fill_rect, BAR_RADIUS, BAR_RADIUS)
        painter.fillPath(fill, QColor(theme.ACCENT))

        if self._active:
            self._sweep(painter, rect, fill, QColor(255, 255, 255), 120)

    def _sweep(self, painter, area: QRectF, clip: QPainterPath, colour: QColor, alpha: int) -> None:  # noqa: ANN001
        """Verilen sekle kirpilmis, soldan saga gecen isik bandi."""
        painter.save()
        painter.setClipPath(clip)

        band = area.width() * SHIMMER_WIDTH
        start = area.left() - band + self._phase * (area.width() + band)

        gradient = QLinearGradient(start, 0.0, start + band, 0.0)
        bright = QColor(colour)
        bright.setAlpha(alpha)
        clear = QColor(colour)
        clear.setAlpha(0)
        gradient.setColorAt(0.0, clear)
        gradient.setColorAt(0.5, bright)
        gradient.setColorAt(1.0, clear)

        painter.fillRect(area, gradient)
        painter.restore()


class ProgressCell(QWidget):
    """Tablo hucresi: once yuzde, sonra cubuk.

    Yuzde BASTA cunku cubugun icine yazilinca okunmuyordu ve sonuna konunca
    goz once cubuga, sonra sayiya gidiyordu.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 6, 0)
        row.setSpacing(9)

        self.percent = QLabel("0%")
        # Sabit genislik: satirlar arasinda cubuklar hizali dursun, sayi
        # buyudukce cubuk kaymasin.
        self.percent.setMinimumWidth(36)
        self.percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.percent.setProperty("muted", True)
        row.addWidget(self.percent)

        self.bar = ShimmerBar()
        row.addWidget(self.bar, 1)

        # Gosterilen deger ile en son GERCEK deger ayri tutuluyor.
        self._shown = 0.0
        self._real = 0.0
        self._real_at = time.monotonic()
        self._rate = 0.0          # saniyede yuzde puani
        self._ceiling = stages.CEILING * 100
        self._running = False
        self._finished = False
        self._last_tick = time.monotonic()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000 // FPS)
        self._tick_timer.timeout.connect(self._tick)

    # ------------------------------------------------------------- girdi

    def set_state(
        self,
        *,
        percent: float,
        stage: str | None,
        eta_seconds: float | None,
        running: bool,
        finished: bool,
    ) -> None:
        """Veritabanindan gelen GERCEK durumu ver."""
        now = time.monotonic()
        percent = max(0.0, min(100.0, percent))

        self._finished = finished
        self._running = running

        if finished:
            self._real = self._shown = 100.0
            self._rate = 0.0
            self._stop_ticking()
            self._render()
            return

        if not running:
            # Bekleyen, iptal veya hatali is: oldugu yerde dursun.
            self._real = self._shown = percent
            self._rate = 0.0
            self._stop_ticking()
            self._render()
            return

        if percent > self._real:
            self._real = percent
            self._real_at = now
        # percent daha kucukse gercege sadik kaliyoruz ama gosterileni geri
        # sarmiyoruz: geri giden bir cubuk, gec kalan cubuktan kotudur.

        # GERCEK deger her zaman aninda gecerli. Tahmin yalnizca ILERI dogru
        # dolduruyor. Boylece uygulama acildiginda yarim kalmis bir is
        # sifirdan animasyon yapmiyor, oldugu yerden devam ediyor.
        self._shown = max(self._shown, self._real)

        self._ceiling = min(stages.stage_ceiling(stage) * 100, stages.CEILING * 100)

        if eta_seconds and eta_seconds > 0:
            # Kalan sure biliniyor: asamanin sonuna tam o surede varacak hiz.
            remaining = max(0.0, self._ceiling - self._real)
            self._rate = remaining / eta_seconds
        else:
            self._rate = 0.0

        self._start_ticking()
        # Gercek deger geldigi anda ciziliyor. Bir sonraki tiki beklemek,
        # olay dongusu olmayan baglamlarda (testler) degeri hic gostermiyor
        # ve normal kullanimda da 33 ms'lik gereksiz bir gecikme ekliyor.
        self._render()

    # ------------------------------------------------------------ hesap

    def _start_ticking(self) -> None:
        if not self._tick_timer.isActive():
            self._last_tick = time.monotonic()
            self._tick_timer.start()

    def _stop_ticking(self) -> None:
        if self._tick_timer.isActive():
            self._tick_timer.stop()

    def _tick(self) -> None:
        now = time.monotonic()
        delta = now - self._last_tick
        self._last_tick = now
        if delta <= 0:
            return

        projected = self._project(now)
        # Tahmin yalnizca ilerletir; asla geri almaz.
        self._shown = min(max(self._shown, projected), self._ceiling)
        self._render()

    def _project(self, now: float) -> float:
        """Su an gosterilebilecek en yuksek deger."""
        if self._real >= self._ceiling:
            return self._ceiling

        elapsed = now - self._real_at
        if self._rate > 0:
            return min(self._real + self._rate * elapsed, self._ceiling)

        # Hiz bilinmiyor: asamanin sonuna gittikce yavaslayarak yaklas.
        # Asla varmaz, ama hep ilerler.
        span = (self._ceiling - self._real) * UNKNOWN_RATE_MAX_SPAN
        return self._real + span * (1.0 - math.exp(-elapsed / UNKNOWN_RATE_TAU))

    def _render(self) -> None:
        self.bar.setValue(self._shown)
        self.bar.setActive(self._running and not self._finished)
        self.percent.setText(f"{int(self._shown)}%")

    # ------------------------------------------------------- geriye uyum

    def update_state(self, percent: float, *, active: bool) -> None:
        """Eski, tahmin yapmayan arayuz. Testler ve basit kullanim icin."""
        self.set_state(
            percent=percent,
            stage=None,
            eta_seconds=None,
            running=active,
            finished=not active and percent >= 100,
        )
