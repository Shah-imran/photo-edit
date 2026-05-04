"""Performance tests for debouncing effectiveness."""

import pytest
import time
from unittest.mock import Mock
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from src.utils.debouncer import Debouncer


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestDebouncingPerformance:
    """Test that debouncing reduces processing calls."""

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
