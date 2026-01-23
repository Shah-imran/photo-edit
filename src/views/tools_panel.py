"""Tools panel for image adjustments."""

from typing import Optional, Dict
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QScrollArea,
    QPushButton,
    QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal

from src.views.widgets.adjustment_slider import AdjustmentSlider


class ToolsPanel(QWidget):
    """Panel containing adjustment controls for image editing.
    
    Signals:
        adjustments_changed: Emitted when any adjustment changes
    """
    
    adjustments_changed = pyqtSignal(dict)

    def __init__(self, parent: Optional[QWidget] = None):
        """Initialize the tools panel.
        
        Args:
            parent: Optional parent widget
        """
        super().__init__(parent)
        
        # Current adjustment values
        self._adjustments: Dict[str, float] = {
            'exposure': 0.0,
            'contrast': 0.0,
            'brightness': 0.0,
            'saturation': 0.0,
            'vibrance': 0.0
        }
        
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Set up the UI components."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Scroll area for controls
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #242424;
                border: none;
            }
        """)
        
        # Content widget
        content = QWidget()
        content.setStyleSheet("background-color: #242424;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(16)
        
        # Light section
        light_section = self._create_section("Light")
        light_layout = QVBoxLayout(light_section)
        light_layout.setContentsMargins(0, 8, 0, 0)
        light_layout.setSpacing(8)
        
        self._exposure_slider = AdjustmentSlider(
            "Exposure", min_value=-5.0, max_value=5.0, default_value=0.0, step=0.1
        )
        light_layout.addWidget(self._exposure_slider)
        
        self._contrast_slider = AdjustmentSlider(
            "Contrast", min_value=-100.0, max_value=100.0, default_value=0.0, step=1.0, decimals=0
        )
        light_layout.addWidget(self._contrast_slider)
        
        self._brightness_slider = AdjustmentSlider(
            "Brightness", min_value=-100.0, max_value=100.0, default_value=0.0, step=1.0, decimals=0
        )
        light_layout.addWidget(self._brightness_slider)
        
        content_layout.addWidget(light_section)
        
        # Color section
        color_section = self._create_section("Color")
        color_layout = QVBoxLayout(color_section)
        color_layout.setContentsMargins(0, 8, 0, 0)
        color_layout.setSpacing(8)
        
        self._saturation_slider = AdjustmentSlider(
            "Saturation", min_value=-100.0, max_value=100.0, default_value=0.0, step=1.0, decimals=0
        )
        color_layout.addWidget(self._saturation_slider)
        
        self._vibrance_slider = AdjustmentSlider(
            "Vibrance", min_value=-100.0, max_value=100.0, default_value=0.0, step=1.0, decimals=0
        )
        color_layout.addWidget(self._vibrance_slider)
        
        content_layout.addWidget(color_section)
        
        # Reset button
        self._reset_button = QPushButton("Reset All")
        self._reset_button.setStyleSheet("""
            QPushButton {
                background-color: #3a3a3a;
                color: #e0e0e0;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
            QPushButton:pressed {
                background-color: #2d2d2d;
            }
        """)
        content_layout.addWidget(self._reset_button)
        
        content_layout.addStretch()
        
        scroll_area.setWidget(content)
        main_layout.addWidget(scroll_area)

    def _create_section(self, title: str) -> QFrame:
        """Create a section frame with title.
        
        Args:
            title: Section title
            
        Returns:
            QFrame containing the section
        """
        section = QFrame()
        section.setStyleSheet("""
            QFrame {
                background-color: transparent;
            }
        """)
        
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Section title
        title_label = QLabel(title)
        title_label.setStyleSheet("""
            QLabel {
                color: #a0a0a0;
                font-size: 12px;
                font-weight: bold;
                padding-bottom: 4px;
                border-bottom: 1px solid #3a3a3a;
            }
        """)
        layout.addWidget(title_label)
        
        return section

    def _connect_signals(self):
        """Connect slider signals."""
        self._exposure_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('exposure', v)
        )
        self._contrast_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('contrast', v)
        )
        self._brightness_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('brightness', v)
        )
        self._saturation_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('saturation', v)
        )
        self._vibrance_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('vibrance', v)
        )
        self._reset_button.clicked.connect(self.reset_all)

    def _on_adjustment_changed(self, name: str, value: float):
        """Handle adjustment value change.
        
        Args:
            name: Adjustment name
            value: New value
        """
        self._adjustments[name] = value
        self.adjustments_changed.emit(self._adjustments.copy())

    def get_adjustments(self) -> Dict[str, float]:
        """Get all current adjustment values.
        
        Returns:
            Dictionary of adjustment name to value
        """
        return self._adjustments.copy()

    def get_exposure_params(self) -> Dict[str, float]:
        """Get exposure-related adjustment parameters.
        
        Returns:
            Dictionary of exposure parameters
        """
        return {
            'exposure': self._adjustments['exposure'],
            'contrast': self._adjustments['contrast'],
            'brightness': self._adjustments['brightness']
        }

    def get_color_params(self) -> Dict[str, float]:
        """Get color-related adjustment parameters.
        
        Returns:
            Dictionary of color parameters
        """
        return {
            'saturation': self._adjustments['saturation'],
            'vibrance': self._adjustments['vibrance']
        }

    def reset_all(self):
        """Reset all adjustments to default values."""
        self._exposure_slider.reset()
        self._contrast_slider.reset()
        self._brightness_slider.reset()
        self._saturation_slider.reset()
        self._vibrance_slider.reset()

    def set_enabled(self, enabled: bool):
        """Enable or disable all controls.
        
        Args:
            enabled: True to enable, False to disable
        """
        self._exposure_slider.setEnabled(enabled)
        self._contrast_slider.setEnabled(enabled)
        self._brightness_slider.setEnabled(enabled)
        self._saturation_slider.setEnabled(enabled)
        self._vibrance_slider.setEnabled(enabled)
        self._reset_button.setEnabled(enabled)
