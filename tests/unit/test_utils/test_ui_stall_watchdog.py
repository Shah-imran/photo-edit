"""Tests for the UI-thread stall watchdog."""

import logging

from src.utils.stall_watchdog import UiStallWatchdog


def test_short_delays_are_ignored(qtbot):
    watchdog = UiStallWatchdog(threshold_ms=50.0)
    watchdog.record(10.0)
    watchdog.record(49.0)
    assert watchdog.stall_count == 0


def test_long_delay_is_counted_and_logged(qtbot, caplog):
    watchdog = UiStallWatchdog(threshold_ms=50.0)
    with caplog.at_level(logging.WARNING, logger="src.utils.stall_watchdog"):
        watchdog.record(120.0)
    assert watchdog.stall_count == 1
    assert watchdog.worst_stall_ms == 120.0
    assert "UI-STALL blocked_ms=120" in caplog.text


def test_blocking_the_event_loop_is_detected(qtbot):
    import time

    watchdog = UiStallWatchdog(interval_ms=10, threshold_ms=50.0)
    watchdog.start()
    qtbot.wait(30)
    time.sleep(0.15)  # freeze the UI thread
    qtbot.wait(40)
    watchdog.stop()
    assert watchdog.stall_count >= 1
    assert watchdog.worst_stall_ms >= 80.0
