"""Adjustment slider widget for editing controls."""

from typing import Optional
from PyQt6.QtWidgets import (
    QWidget,
    QHBoxLayout,
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
        slider_released: Emitted when slider is released (float)
    """
    
    value_changed = pyqtSignal(float)
    slider_released = pyqtSignal(float)

    def __init__(
        self,
        label: str,
        min_value: float = -100.0,
        max_value: float = 100.0,
        default_value: float = 0.0,
        step: float = 1.0,
        decimals: int = 1,
        color_gradient: Optional[str] = None,
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
        
        self._color_gradient = color_gradient
        self._setup_ui(label)
        self._connect_signals()

    def _setup_ui(self, label: str):
        """Set up the UI components."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 4)
        layout.setSpacing(8)
        
        self._label = QLabel(label)
        self._label.setStyleSheet("color: #e0e0e0; font-size: 11px;")
        self._label.setMinimumWidth(70)
        layout.addWidget(self._label)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(
            int(self._min_value * self._scale_factor),
            int(self._max_value * self._scale_factor)
        )
        self._slider.setValue(int(self._default_value * self._scale_factor))
        groove = self._color_gradient or "#59616a"
        sub_page = "transparent" if self._color_gradient else "#168cff"
        self._slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 2px;
                background: {groove};
                border-radius: 1px;
            }}
            QSlider::handle:horizontal {{
                width: 11px;
                height: 11px;
                background: #e8edf2;
                border: 1px solid #168cff;
                border-radius: 6px;
                margin: -5px 0;
            }}
            QSlider::handle:horizontal:hover {{ background: white; }}
            QSlider::sub-page:horizontal {{
                background: {sub_page};
                border-radius: 1px;
            }}
        """)
        layout.addWidget(self._slider, 1)

        self._spin_box = QDoubleSpinBox()
        self._spin_box.setRange(self._min_value, self._max_value)
        self._spin_box.setSingleStep(self._step)
        self._spin_box.setDecimals(self._decimals)
        self._spin_box.setValue(self._default_value)
        self._spin_box.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self._spin_box.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._spin_box.setFixedWidth(52)
        self._spin_box.setStyleSheet("""
            QDoubleSpinBox {
                background: transparent;
                color: #e0e0e0;
                border: none;
                padding: 0;
            }
            QDoubleSpinBox:focus { color: white; }
        """)
        layout.addWidget(self._spin_box)

    def _connect_signals(self):
        """Connect internal signals."""
        self._slider.valueChanged.connect(self._on_slider_changed)
        self._slider.sliderReleased.connect(self._on_slider_released)
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

    def _on_slider_released(self):
        """Handle slider release."""
        self.slider_released.emit(self.get_value())

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
