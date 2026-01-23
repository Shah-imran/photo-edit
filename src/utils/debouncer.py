"""Debouncer utility for delaying rapid signal emissions."""

from typing import Optional, Callable, Any
from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class Debouncer(QObject):
    """Debounces rapid calls, only executing after a quiet period.
    
    This is useful for slider adjustments where we don't want to process
    every tiny movement, but wait until the user pauses.
    
    Signals:
        triggered: Emitted after the debounce delay with the latest value
    """
    
    triggered = pyqtSignal(object)
    
    def __init__(
        self,
        delay_ms: int = 50,
        parent: Optional[QObject] = None
    ):
        """Initialize the debouncer.
        
        Args:
            delay_ms: Delay in milliseconds before triggering (default 50ms)
            parent: Optional parent QObject
        """
        super().__init__(parent)
        
        self._delay_ms = delay_ms
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._pending_value: Any = None
        self._callback: Optional[Callable[[Any], None]] = None
    
    @property
    def delay_ms(self) -> int:
        """Get the current delay in milliseconds."""
        return self._delay_ms
    
    @delay_ms.setter
    def delay_ms(self, value: int) -> None:
        """Set the delay in milliseconds."""
        self._delay_ms = max(0, value)
    
    def call(self, value: Any) -> None:
        """Queue a value to be emitted after the debounce delay.
        
        If called again before the delay expires, the timer resets
        and only the latest value will be emitted.
        
        Args:
            value: The value to emit when triggered
        """
        self._pending_value = value
        self._timer.stop()
        self._timer.start(self._delay_ms)
    
    def call_immediate(self, value: Any) -> None:
        """Immediately emit the value, bypassing debounce.
        
        This is useful for final values (e.g., on slider release).
        
        Args:
            value: The value to emit immediately
        """
        self._timer.stop()
        self._pending_value = value
        self._emit()
    
    def cancel(self) -> None:
        """Cancel any pending debounced call."""
        self._timer.stop()
        self._pending_value = None
    
    def is_pending(self) -> bool:
        """Check if there's a pending debounced call.
        
        Returns:
            True if a call is pending
        """
        return self._timer.isActive()
    
    def flush(self) -> None:
        """Immediately emit any pending value.
        
        If no value is pending, does nothing.
        """
        if self._timer.isActive():
            self._timer.stop()
            self._emit()
    
    def set_callback(self, callback: Optional[Callable[[Any], None]]) -> None:
        """Set a callback function to be called instead of emitting signal.
        
        This is an alternative to connecting to the triggered signal.
        
        Args:
            callback: Function to call with the value, or None to use signal
        """
        self._callback = callback
    
    def _on_timeout(self) -> None:
        """Handle timer timeout."""
        self._emit()
    
    def _emit(self) -> None:
        """Emit the pending value."""
        if self._pending_value is not None:
            value = self._pending_value
            self._pending_value = None
            
            if self._callback is not None:
                self._callback(value)
            else:
                self.triggered.emit(value)


class ThrottledDebouncer(QObject):
    """Combines throttling with debouncing for smooth updates.
    
    Provides immediate feedback at a throttled rate, plus a final
    debounced call when activity stops.
    
    This gives users immediate visual feedback while preventing
    excessive processing.
    
    Signals:
        throttled: Emitted at throttle rate during activity
        debounced: Emitted after activity stops
    """
    
    throttled = pyqtSignal(object)
    debounced = pyqtSignal(object)
    
    def __init__(
        self,
        throttle_ms: int = 16,  # ~60fps
        debounce_ms: int = 100,
        parent: Optional[QObject] = None
    ):
        """Initialize the throttled debouncer.
        
        Args:
            throttle_ms: Minimum time between throttled emissions (default 16ms for 60fps)
            debounce_ms: Delay after last call before debounced emission (default 100ms)
            parent: Optional parent QObject
        """
        super().__init__(parent)
        
        self._throttle_ms = throttle_ms
        self._debounce_ms = debounce_ms
        
        # Throttle timer - fires at regular intervals during activity
        self._throttle_timer = QTimer(self)
        self._throttle_timer.setSingleShot(True)
        self._throttle_timer.timeout.connect(self._on_throttle_timeout)
        
        # Debounce timer - fires after activity stops
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._on_debounce_timeout)
        
        self._pending_value: Any = None
        self._can_throttle = True
    
    def call(self, value: Any) -> None:
        """Queue a value for throttled/debounced emission.
        
        Args:
            value: The value to emit
        """
        self._pending_value = value
        
        # Always reset debounce timer
        self._debounce_timer.stop()
        self._debounce_timer.start(self._debounce_ms)
        
        # Emit immediately if throttle allows
        if self._can_throttle:
            self._can_throttle = False
            self._throttle_timer.start(self._throttle_ms)
            self.throttled.emit(value)
    
    def cancel(self) -> None:
        """Cancel any pending emissions."""
        self._throttle_timer.stop()
        self._debounce_timer.stop()
        self._pending_value = None
        self._can_throttle = True
    
    def _on_throttle_timeout(self) -> None:
        """Handle throttle timer timeout."""
        self._can_throttle = True
        # If there's a pending value, emit it
        if self._pending_value is not None and self._debounce_timer.isActive():
            self._can_throttle = False
            self._throttle_timer.start(self._throttle_ms)
            self.throttled.emit(self._pending_value)
    
    def _on_debounce_timeout(self) -> None:
        """Handle debounce timer timeout."""
        self._throttle_timer.stop()
        self._can_throttle = True
        if self._pending_value is not None:
            self.debounced.emit(self._pending_value)
            self._pending_value = None
