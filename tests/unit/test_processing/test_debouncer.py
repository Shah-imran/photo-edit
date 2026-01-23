"""Unit tests for Debouncer utility."""

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

    def test_throttled_debouncer_initialization(self, qapp):
        """Test ThrottledDebouncer can be initialized."""
        td = ThrottledDebouncer(throttle_ms=16, debounce_ms=100)
        assert td is not None

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
