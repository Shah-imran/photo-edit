"""Adjustment slider widget for editing controls."""

from typing import Optional
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QSlider,
    QDoubleSpinBox
)
from PyQt6.QtCore import Qt, pyqtSignal


class AdjustmentSlider(QWidget):
    """Custom slider widget for image adjustments.
    
    Features:
    - Label showing adjustment name
    - Slider for visual adjustment
    - Spin box for precise value entry
    - Reset on double-click
    
    Signals:
        value_changed: Emitted when value changes (float)
    """
    
    value_changed = pyqtSignal(float)

    def __init__(
        self,
        label: str,
        min_value: float = -100.0,
        max_value: float = 100.0,
        default_value: float = 0.0,
        step: float = 1.0,
        decimals: int = 1,
        parent: Optional[QWidget] = None
    ):
        """Initialize the adjustment slider.
        
        Args:
            label: Label text for the slider
            min_value: Minimum slider value
            max_value: Maximum slider value
            default_value: Default/reset value
            step: Step increment for slider
            decimals: Number of decimal places for spin box
            parent: Optional parent widget
        """
        super().__init__(parent)
        
        self._min_value = min_value
        self._max_value = max_value
        self._default_value = default_value
        self._step = step
        self._decimals = decimals
        self._scale_factor = 10 ** decimals  # For slider integer conversion
        
        self._setup_ui(label)
        self._connect_signals()

    def _setup_ui(self, label: str):
        """Set up the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(4)
        
        # Top row: label and value
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        
        self._label = QLabel(label)
        self._label.setStyleSheet("color: #e0e0e0; font-size: 11px;")
        top_row.addWidget(self._label)
        
        top_row.addStretch()
        
        self._spin_box = QDoubleSpinBox()
        self._spin_box.setRange(self._min_value, self._max_value)
        self._spin_box.setSingleStep(self._step)
        self._spin_box.setDecimals(self._decimals)
        self._spin_box.setValue(self._default_value)
        self._spin_box.setFixedWidth(70)
        self._spin_box.setStyleSheet("""
            QDoubleSpinBox {
                background-color: #2d2d2d;
                color: #e0e0e0;
                border: 1px solid #3a3a3a;
                border-radius: 3px;
                padding: 2px 4px;
            }
            QDoubleSpinBox:focus {
                border-color: #0078d4;
            }
        """)
        top_row.addWidget(self._spin_box)
        
        layout.addLayout(top_row)
        
        # Slider
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(
            int(self._min_value * self._scale_factor),
            int(self._max_value * self._scale_factor)
        )
        self._slider.setValue(int(self._default_value * self._scale_factor))
        self._slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #3a3a3a;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 14px;
                height: 14px;
                background: #0078d4;
                border-radius: 7px;
                margin: -5px 0;
            }
            QSlider::handle:horizontal:hover {
                background: #0086f0;
            }
            QSlider::sub-page:horizontal {
                background: #0078d4;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self._slider)

    def _connect_signals(self):
        """Connect internal signals."""
        self._slider.valueChanged.connect(self._on_slider_changed)
        self._spin_box.valueChanged.connect(self._on_spinbox_changed)

    def _on_slider_changed(self, value: int):
        """Handle slider value change."""
        float_value = value / self._scale_factor
        # Block spin box signals to prevent loop
        self._spin_box.blockSignals(True)
        self._spin_box.setValue(float_value)
        self._spin_box.blockSignals(False)
        self.value_changed.emit(float_value)

    def _on_spinbox_changed(self, value: float):
        """Handle spin box value change."""
        # Block slider signals to prevent loop
        self._slider.blockSignals(True)
        self._slider.setValue(int(value * self._scale_factor))
        self._slider.blockSignals(False)
        self.value_changed.emit(value)

    def get_value(self) -> float:
        """Get the current slider value.
        
        Returns:
            Current value
        """
        return self._spin_box.value()

    def set_value(self, value: float) -> None:
        """Set the slider value.
        
        Args:
            value: Value to set
        """
        value = max(self._min_value, min(self._max_value, value))
        self._spin_box.setValue(value)

    def reset(self) -> None:
        """Reset the slider to default value."""
        self.set_value(self._default_value)

    def mouseDoubleClickEvent(self, event):
        """Handle double-click to reset value."""
        self.reset()
        super().mouseDoubleClickEvent(event)
