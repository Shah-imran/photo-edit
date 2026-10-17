"""Unit tests for Debouncer utility."""

import time

import pytest
from unittest.mock import Mock
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QCoreApplication
from src.utils.debouncer import Debouncer, ThrottledDebouncer


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestDebouncer:
    """Test cases for Debouncer class."""

    def test_debouncer_initialization(self, qapp):
        """Test Debouncer can be initialized."""
        debouncer = Debouncer(delay_ms=50)
        assert debouncer is not None
        assert debouncer.delay_ms == 50

    def test_debouncer_delay_setter(self, qapp):
        """Test setting delay_ms property."""
        debouncer = Debouncer(delay_ms=50)
        debouncer.delay_ms = 100
        assert debouncer.delay_ms == 100

    def test_debouncer_call_sets_pending(self, qapp):
        """Test that call() sets a pending state."""
        debouncer = Debouncer(delay_ms=100)
        debouncer.call("test_value")
        assert debouncer.is_pending() is True

    def test_debouncer_cancel(self, qapp):
        """Test cancelling a pending call."""
        debouncer = Debouncer(delay_ms=100)
        debouncer.call("test_value")
        debouncer.cancel()
        assert debouncer.is_pending() is False

    def test_debouncer_call_immediate(self, qapp, qtbot):
        """Test immediate call bypasses debounce."""
        debouncer = Debouncer(delay_ms=100)
        callback = Mock()
        debouncer.triggered.connect(callback)
        
        debouncer.call_immediate("immediate_value")
        
        # Should be called immediately
        assert callback.called is True
        callback.assert_called_with("immediate_value")

    def test_debouncer_callback(self, qapp, qtbot):
        """Test using callback instead of signal."""
        debouncer = Debouncer(delay_ms=10)
        callback = Mock()
        debouncer.set_callback(callback)
        
        debouncer.call("test_value")
        
        # Wait for debounce
        qtbot.wait(50)
        
        callback.assert_called_with("test_value")

    def test_debouncer_flush(self, qapp, qtbot):
        """Test flush emits pending value immediately."""
        debouncer = Debouncer(delay_ms=1000)  # Long delay
        callback = Mock()
        debouncer.triggered.connect(callback)
        
        debouncer.call("flush_value")
        debouncer.flush()
        
        # Should be called immediately after flush
        callback.assert_called_with("flush_value")
        assert debouncer.is_pending() is False


class TestThrottledDebouncer:
    """Test cases for ThrottledDebouncer class."""


    def test_throttled_debouncer_cancel(self, qapp):
        """Test cancelling throttled debouncer."""
        td = ThrottledDebouncer(throttle_ms=16, debounce_ms=100)
        td.call("value")
        td.cancel()
        # Should not raise

    def test_throttled_debouncer_first_call_immediate(self, qapp, qtbot):
        """Test first call is emitted immediately via throttled signal."""
        td = ThrottledDebouncer(throttle_ms=16, debounce_ms=100)
        throttle_callback = Mock()
        td.throttled.connect(throttle_callback)
        
        td.call("first_value")
        
        # First call should be immediate
        throttle_callback.assert_called_with("first_value")


class TestDebouncingBehaviour:
    """Debouncing collapses bursts of calls (moved from tests/performance:
    these check call counts, not timing budgets)."""

    def test_debouncer_reduces_calls(self, qapp, qtbot):
        """Test that rapid calls result in only one processing."""
        debouncer = Debouncer(delay_ms=50)
        callback = Mock()
        debouncer.triggered.connect(callback)
        
        # Simulate rapid slider movements (20 calls)
        for i in range(20):
            debouncer.call(f"value_{i}")
            qtbot.wait(5)  # 5ms between calls
        
        # Wait for debounce delay
        qtbot.wait(100)
        
        # Should only be called once (with last value)
        assert callback.call_count == 1
        callback.assert_called_with("value_19")

    def test_debouncer_without_debouncing(self, qapp, qtbot):
        """Test that without debouncing, all calls would fire."""
        # This demonstrates the problem debouncing solves
        callback = Mock()
        
        # Simulate direct calls (no debouncing)
        for i in range(20):
            callback(f"value_{i}")
            qtbot.wait(5)
        
        # Without debouncing, all 20 calls fire
        assert callback.call_count == 20

    def test_debouncer_handles_rapid_changes(self, qapp, qtbot):
        """Test debouncer with very rapid changes."""
        debouncer = Debouncer(delay_ms=30)
        callback = Mock()
        debouncer.triggered.connect(callback)
        
        # 100 rapid calls
        for i in range(100):
            debouncer.call(i)
        
        qtbot.wait(100)
        
        # Should only process once
        assert callback.call_count == 1
        callback.assert_called_with(99)

    def test_debouncer_separate_events(self, qapp, qtbot):
        """Test that separate events (with pause) trigger separately."""
        debouncer = Debouncer(delay_ms=50)
        callback = Mock()
        debouncer.triggered.connect(callback)
        
        # First burst
        for i in range(10):
            debouncer.call(f"first_{i}")
        qtbot.wait(100)  # Wait for first to fire
        
        # Second burst (after pause)
        for i in range(10):
            debouncer.call(f"second_{i}")
        qtbot.wait(100)  # Wait for second to fire
        
        # Should fire twice (once per burst)
        assert callback.call_count == 2
