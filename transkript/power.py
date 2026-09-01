"""Uzun isler sirasinda Windows'un uyumasini engelleme.

Gece boyu calisacak bir kuyrugun laptop kapagi kapandi diye yarida kalmamasi
icin. Ekranin sonmesini engellemiyoruz, sadece sistemin uyku moduna girmesini:
ekranin kapanmasi ise zarar vermiyor ve gereksiz yere elektrik yakmamis oluyoruz.

Kuyruk bosaldiginda kilit birakiliyor, aksi halde uygulama acik kaldigi surece
bilgisayar hic uyumazdi.
"""

from __future__ import annotations

import ctypes
import sys
import threading

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_AWAYMODE_REQUIRED = 0x00000040


class KeepAwake:
    """Sayac tabanli uyku engeli. Ic ice acquire cagrilarina dayanikli."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count = 0
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def _apply(self, keep: bool) -> bool:
        if sys.platform != "win32":
            return False
        try:
            flags = ES_CONTINUOUS
            if keep:
                flags |= ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
            result = ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags))
            return result != 0
        except (AttributeError, OSError):
            return False

    def acquire(self) -> None:
        with self._lock:
            self._count += 1
            if self._count == 1:
                self._active = self._apply(True)

    def release(self) -> None:
        with self._lock:
            if self._count == 0:
                return
            self._count -= 1
            if self._count == 0:
                self._apply(False)
                self._active = False

    def reset(self) -> None:
        with self._lock:
            self._count = 0
            self._apply(False)
            self._active = False

    def __enter__(self) -> KeepAwake:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


keep_awake = KeepAwake()
