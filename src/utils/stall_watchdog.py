"""Detect and log UI-thread stalls.

A heartbeat ``QTimer`` fires every ``interval_ms`` on the UI thread. When
the event loop is blocked (a synchronous render, a big float-to-RGB
conversion, ...), the next tick arrives late; the lateness is how long the
window was frozen. Stalls over ``threshold_ms`` are logged as ``UI-STALL``
warnings so regressions show up in ``logs/photoedit.log`` without needing a
profiler. See docs/planning/PERFORMANCE_OVERHAUL.md (Phase 0).
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Optional

from PyQt6.QtCore import QObject, QTimer


logger = logging.getLogger(__name__)


class UiStallWatchdog(QObject):
    """Heartbeat timer that logs event-loop stalls on the UI thread."""

    def __init__(
        self,
        parent: Optional[QObject] = None,
        interval_ms: int = 20,
        threshold_ms: float = 50.0,
    ):
        super().__init__(parent)
        self._interval_ms = interval_ms
        self._threshold_ms = threshold_ms
        self._last_tick: Optional[float] = None
        self._stall_count = 0
        self._worst_stall_ms = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._on_tick)

    @property
    def stall_count(self) -> int:
        """Number of stalls over the threshold since ``start``."""
        return self._stall_count

    @property
    def worst_stall_ms(self) -> float:
        """Longest stall seen since ``start``."""
        return self._worst_stall_ms

    def start(self) -> None:
        """Begin watching the event loop."""
        self._last_tick = perf_counter()
        self._timer.start()

    def stop(self) -> None:
        """Stop watching."""
        self._timer.stop()
        self._last_tick = None

    def _on_tick(self) -> None:
        now = perf_counter()
        if self._last_tick is not None:
            blocked_ms = (now - self._last_tick) * 1000.0 - self._interval_ms
            self.record(blocked_ms)
        self._last_tick = now

    def record(self, blocked_ms: float) -> None:
        """Record one heartbeat's lateness (exposed for tests)."""
        if blocked_ms <= self._threshold_ms:
            return
        self._stall_count += 1
        self._worst_stall_ms = max(self._worst_stall_ms, blocked_ms)
        logger.warning("UI-STALL blocked_ms=%.0f", blocked_ms)
