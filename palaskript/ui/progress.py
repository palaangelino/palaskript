"""Kuyruk tablosundaki ilerleme cubugu.

Neden QProgressBar degil de kendi cizimimiz:

- Yuzde metni cubugun ICINDE okunmuyordu; metin kismen turuncu dolgunun,
  kismen krem zeminin uzerine dusuyor ve iki durumda da dogru kontrasti veren
  tek bir renk yok. Yuzde artik cubugun BASINDA, kendi zemininde.
- Uzun islerde cubuk dakikalarca ayni yerde duruyor ve uygulama donmus gibi
  gorunuyor. Uzerinden gecen bir isik bandi (shimmer) isin surdugunu
  gosteriyor. Stil sayfasiyla animasyon yapilamiyor, cizim gerekiyor.

Animasyon YALNIZCA islenen satirda calisiyor. Kuyrukta elli is varken hepsini
birden canlandirmak, uc saat suren bir isin yaninda bosuna CPU yakmak olurdu.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from . import theme

BAR_HEIGHT = 7
BAR_RADIUS = 3.5

# Cubugun en dar hali. Bunu vermezsek sutun "icerige gore" daralirken cubugu
# sifira indiriyor: ozel widget'in kendiliginden bir genislik ipucu yok.
BAR_MIN_WIDTH = 110

# Isik bandinin bir uctan digerine gecme suresi.
SHIMMER_PERIOD_MS = 1500
SHIMMER_FPS = 30

# Bandin genisligi, dolgunun yuzdesi olarak.
SHIMMER_WIDTH = 0.35


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
        self._timer.setInterval(1000 // SHIMMER_FPS)
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
        step = (1000 / SHIMMER_FPS) / SHIMMER_PERIOD_MS
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
        # bandi oraya hapsetmek onu gorunmez yapiyordu; oysa kullanicinin
        # "calisiyor mu" sorusuna cevap veren tam da bu.
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
            # Dolgunun uzerinde daha parlak, ayni evrede ilerleyen ikinci band.
            self._sweep(painter, rect, fill, QColor(255, 255, 255), 120)

    def _sweep(self, painter, area: QRectF, clip: QPainterPath, colour: QColor, alpha: int) -> None:  # noqa: ANN001
        """Verilen sekle kirpilmis, soldan saga gecen isik bandi.

        Bandin konumu her zaman TUM cubuga gore hesaplaniyor; boylece
        dolgudaki ve zemindeki bandlar ayni hizada hareket ediyor.
        """
        painter.save()
        painter.setClipPath(clip)

        band = area.width() * SHIMMER_WIDTH
        # Band tamamen disaridan girip tamamen disariya ciksin.
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
    goz once cubuga, sonra sayiya gidiyordu. Basta olunca satiri soldan saga
    okurken sayi ilk geliyor.
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

    def update_state(self, percent: float, *, active: bool) -> None:
        self.bar.setValue(percent)
        self.bar.setActive(active)
        self.percent.setText(f"{int(percent)}%")
