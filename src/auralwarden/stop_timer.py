from __future__ import annotations

import math
import time
from dataclasses import dataclass


@dataclass
class StopTimer:
    """An explicit one-shot stop request; never shuts down the computer."""

    duration_seconds: float | None = None
    stop_at_epoch: float | None = None
    _deadline: float | None = None

    def configure(self, *, duration_seconds=None, stop_at_epoch=None):
        if duration_seconds is not None and stop_at_epoch is not None:
            raise ValueError("Elige una duración o una hora, no ambas.")
        value = duration_seconds if duration_seconds is not None else stop_at_epoch
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("El tiempo no es válido.")
            try:
                finite = math.isfinite(value)
            except (OverflowError, ValueError, TypeError):
                finite = False
            if not finite or value <= 0:
                raise ValueError("El tiempo debe ser positivo y finito.")
        if duration_seconds is not None and duration_seconds > 7 * 86400:
            raise ValueError("La duración máxima es de siete días.")
        if stop_at_epoch is not None and stop_at_epoch <= time.time():
            raise ValueError("Elige una hora futura.")
        self.duration_seconds, self.stop_at_epoch = duration_seconds, stop_at_epoch
        self._deadline = None

    def arm(self, *, monotonic_now=None):
        if self.duration_seconds is not None:
            self._deadline = (time.monotonic() if monotonic_now is None else monotonic_now) + self.duration_seconds

    def remaining(self, *, monotonic_now=None, epoch_now=None):
        if self.stop_at_epoch is not None:
            return max(0.0, self.stop_at_epoch - (time.time() if epoch_now is None else epoch_now))
        if self._deadline is not None:
            return max(0.0, self._deadline - (time.monotonic() if monotonic_now is None else monotonic_now))
        return None

    def clear(self):
        self.duration_seconds = self.stop_at_epoch = self._deadline = None
