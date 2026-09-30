"""Tools panel for image adjustments."""

from typing import Any, Dict, List, Optional, Sequence, Tuple
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QScrollArea,
    QPushButton,
    QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal

from src.processors.color_grading_processor import default_color_grading_params
from src.processors.hsl_mixer_processor import default_hsl_params
from src.utils.curve_math import normalize_points
from src.views.widgets.adjustment_slider import AdjustmentSlider
from src.views.widgets.color_grading_panel import ColorGradingPanel
from src.views.widgets.curve_editor import CurveEditor
from src.views.widgets.hsl_mixer_panel import HslMixerPanel


class ToolsPanel(QWidget):
    """Panel containing adjustment controls for image editing.

    Signals:
        adjustments_changed: Emitted when any (non-curve, non-HSL) adjustment changes
        curve_changed: Emitted when the tone curve changes (list of [x, y]
            control points)
        hsl_changed: Emitted when the HSL Color Mixer changes (24-key flat dict)
        color_grading_changed: Emitted when Color Grading changes (11-key
            flat dict)
        slider_released: Emitted when any slider, the curve editor, the
            HSL mixer, or Color Grading is released (for final processing)
    """

    adjustments_changed = pyqtSignal(dict)
    curve_changed = pyqtSignal(list)
    hsl_changed = pyqtSignal(dict)
    color_grading_changed = pyqtSignal(dict)
    slider_released = pyqtSignal()

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
            'highlights': 0.0,
            'shadows': 0.0,
            'whites': 0.0,
            'blacks': 0.0,
            'temperature': 0.0,
            'tint': 0.0,
            'saturation': 0.0,
            'vibrance': 0.0,
            'texture': 0.0
        }
        self._curve_points: List[Tuple[float, float]] = list(normalize_points(None))
        self._hsl_values: Dict[str, float] = default_hsl_params()
        self._color_grading_values: Dict[str, float] = default_color_grading_params()
        self._suppress_adjustment_signal = False

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
        light_section, light_content_layout = self._create_section("Light")
        
        self._exposure_slider = AdjustmentSlider(
            "Exposure", min_value=-5.0, max_value=5.0, default_value=0.0, step=0.1
        )
        light_content_layout.addWidget(self._exposure_slider)
        
        self._contrast_slider = AdjustmentSlider(
            "Contrast", min_value=-100.0, max_value=100.0, default_value=0.0, step=1.0, decimals=0
        )
        light_content_layout.addWidget(self._contrast_slider)
        
        self._brightness_slider = AdjustmentSlider(
            "Brightness", min_value=-100.0, max_value=100.0, default_value=0.0, step=1.0, decimals=0
        )
        light_content_layout.addWidget(self._brightness_slider)

        self._highlights_slider = AdjustmentSlider(
            "Highlights", min_value=-100.0, max_value=100.0, default_value=0.0, step=1.0, decimals=0
        )
        light_content_layout.addWidget(self._highlights_slider)

        self._shadows_slider = AdjustmentSlider(
            "Shadows", min_value=-100.0, max_value=100.0, default_value=0.0, step=1.0, decimals=0
        )
        light_content_layout.addWidget(self._shadows_slider)

        self._whites_slider = AdjustmentSlider(
            "Whites", min_value=-100.0, max_value=100.0, default_value=0.0, step=1.0, decimals=0
        )
        light_content_layout.addWidget(self._whites_slider)

        self._blacks_slider = AdjustmentSlider(
            "Blacks", min_value=-100.0, max_value=100.0, default_value=0.0, step=1.0, decimals=0
        )
        light_content_layout.addWidget(self._blacks_slider)

        content_layout.addWidget(light_section)

        # Tone Curve section
        curve_section, curve_content_layout = self._create_section("Tone Curve")

        self._curve_editor = CurveEditor()
        curve_content_layout.addWidget(self._curve_editor)

        content_layout.addWidget(curve_section)

        # Color section
        color_section, color_content_layout = self._create_section("Color")

        self._temperature_slider = AdjustmentSlider(
            "Temperature", min_value=-100.0, max_value=100.0, default_value=0.0, step=1.0, decimals=0
        )
        color_content_layout.addWidget(self._temperature_slider)

        self._tint_slider = AdjustmentSlider(
            "Tint", min_value=-100.0, max_value=100.0, default_value=0.0, step=1.0, decimals=0
        )
        color_content_layout.addWidget(self._tint_slider)

        self._saturation_slider = AdjustmentSlider(
            "Saturation", min_value=-100.0, max_value=100.0, default_value=0.0, step=1.0, decimals=0
        )
        color_content_layout.addWidget(self._saturation_slider)
        
        self._vibrance_slider = AdjustmentSlider(
            "Vibrance", min_value=-100.0, max_value=100.0, default_value=0.0, step=1.0, decimals=0
        )
        color_content_layout.addWidget(self._vibrance_slider)
        
        content_layout.addWidget(color_section)

        # Color Mixer section
        mixer_section, mixer_content_layout = self._create_section("Color Mixer")

        self._hsl_mixer_panel = HslMixerPanel()
        mixer_content_layout.addWidget(self._hsl_mixer_panel)

        content_layout.addWidget(mixer_section)

        # Color Grading section
        grading_section, grading_content_layout = self._create_section("Color Grading")

        self._color_grading_panel = ColorGradingPanel()
        grading_content_layout.addWidget(self._color_grading_panel)

        content_layout.addWidget(grading_section)

        effects_section, effects_content_layout = self._create_section("Effects")
        self._texture_slider = AdjustmentSlider(
            "Texture", min_value=-100.0, max_value=100.0,
            default_value=0.0, step=1.0, decimals=0
        )
        effects_content_layout.addWidget(self._texture_slider)
        content_layout.addWidget(effects_section)

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

    def _create_section(self, title: str) -> Tuple[QFrame, QVBoxLayout]:
        """Create a section frame with title.
        
        Args:
            title: Section title
            
        Returns:
            Tuple of (QFrame, QVBoxLayout for content)
        """
        section = QFrame()
        section.setStyleSheet("""
            QFrame {
                background-color: transparent;
            }
        """)
        
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
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
        
        # Return both the section and the layout to add content to
        return section, layout

    def _connect_signals(self):
        """Connect slider signals."""
        # Value changed signals (during slider movement)
        self._exposure_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('exposure', v)
        )
        self._contrast_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('contrast', v)
        )
        self._brightness_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('brightness', v)
        )
        self._highlights_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('highlights', v)
        )
        self._shadows_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('shadows', v)
        )
        self._whites_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('whites', v)
        )
        self._blacks_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('blacks', v)
        )
        self._temperature_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('temperature', v)
        )
        self._tint_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('tint', v)
        )
        self._saturation_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('saturation', v)
        )
        self._vibrance_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('vibrance', v)
        )

        self._texture_slider.value_changed.connect(
            lambda v: self._on_adjustment_changed('texture', v)
        )

        # Slider released signals (for final processing)
        self._exposure_slider.slider_released.connect(self._on_slider_released)
        self._contrast_slider.slider_released.connect(self._on_slider_released)
        self._brightness_slider.slider_released.connect(self._on_slider_released)
        self._highlights_slider.slider_released.connect(self._on_slider_released)
        self._shadows_slider.slider_released.connect(self._on_slider_released)
        self._whites_slider.slider_released.connect(self._on_slider_released)
        self._blacks_slider.slider_released.connect(self._on_slider_released)
        self._temperature_slider.slider_released.connect(self._on_slider_released)
        self._tint_slider.slider_released.connect(self._on_slider_released)
        self._saturation_slider.slider_released.connect(self._on_slider_released)
        self._vibrance_slider.slider_released.connect(self._on_slider_released)
        self._texture_slider.slider_released.connect(self._on_slider_released)

        self._curve_editor.curve_changed.connect(self._on_curve_editor_changed)
        self._curve_editor.curve_released.connect(self._on_curve_editor_released)

        self._hsl_mixer_panel.values_changed.connect(self._on_hsl_mixer_changed)
        self._hsl_mixer_panel.slider_released.connect(self.slider_released)

        self._color_grading_panel.values_changed.connect(
            self._on_color_grading_changed
        )
        self._color_grading_panel.slider_released.connect(self.slider_released)

        self._reset_button.clicked.connect(self.reset_all)
    
    def _on_slider_released(self, value: float):
        """Handle any slider being released."""
        self.slider_released.emit()

    def _on_curve_editor_changed(self, points: list):
        """Handle the tone curve changing (continuous, during drag)."""
        self._curve_points = [tuple(p) for p in points]
        if not self._suppress_adjustment_signal:
            self.curve_changed.emit([list(p) for p in self._curve_points])

    def _on_curve_editor_released(self):
        """Handle the tone curve gesture being committed."""
        if not self._suppress_adjustment_signal:
            self.slider_released.emit()

    def _on_hsl_mixer_changed(self, values: dict):
        """Handle the HSL Color Mixer changing (continuous, during drag)."""
        self._hsl_values = dict(values)
        if not self._suppress_adjustment_signal:
            self.hsl_changed.emit(dict(self._hsl_values))

    def _on_color_grading_changed(self, values: dict):
        """Handle Color Grading changing (continuous, during drag)."""
        self._color_grading_values = dict(values)
        if not self._suppress_adjustment_signal:
            self.color_grading_changed.emit(dict(self._color_grading_values))

    def _on_adjustment_changed(self, name: str, value: float):
        """Handle adjustment value change.
        
        Args:
            name: Adjustment name
            value: New value
        """
        self._adjustments[name] = value
        if not self._suppress_adjustment_signal:
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

    def get_tonal_params(self) -> Dict[str, float]:
        """Get Highlights/Shadows/Whites/Blacks adjustment parameters.

        Returns:
            Dictionary of tonal parameters
        """
        return {
            'highlights': self._adjustments['highlights'],
            'shadows': self._adjustments['shadows'],
            'whites': self._adjustments['whites'],
            'blacks': self._adjustments['blacks']
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

    def get_wb_params(self) -> Dict[str, float]:
        """Get white balance (Temperature/Tint) adjustment parameters.

        Returns:
            Dictionary of white balance parameters
        """
        return {
            'temperature': self._adjustments['temperature'],
            'tint': self._adjustments['tint'],
        }

    def get_curve_params(self) -> Dict[str, Any]:
        """Get the tone curve parameters.

        Returns:
            Dictionary with a single ``"points"`` key (list of ``[x, y]``
            control points).
        """
        return {'points': [list(p) for p in self._curve_points]}

    def update_curve_histogram(self, counts: Optional[Sequence[int]]) -> None:
        """Set the histogram backdrop drawn behind the tone curve."""
        self._curve_editor.set_histogram(counts)

    def get_hsl_params(self) -> Dict[str, float]:
        """Get the HSL Color Mixer parameters.

        Returns:
            Flat 24-key dict (``"<band>_hue"``/``"<band>_sat"``/
            ``"<band>_lum"`` for each of the 8 color bands).
        """
        return dict(self._hsl_values)

    def get_color_grading_params(self) -> Dict[str, float]:
        """Get the Color Grading parameters.

        Returns:
            Flat 11-key dict (per-range ``"<range>_hue"``/``"<range>_sat"``/
            ``"<range>_lum"`` for Shadows/Midtones/Highlights, plus
            ``"blending"``/``"balance"``).
        """
        return dict(self._color_grading_values)

    def reset_all(self):
        """Reset all adjustments to default values."""
        self.set_adjustments({}, emit_signal=True)

    def set_adjustments(self, adjustments: Dict[str, Any], emit_signal: bool = False):
        """Apply a complete adjustment-state payload to the slider UI."""
        merged = {
            'exposure': float(adjustments.get('exposure', 0.0)),
            'contrast': float(adjustments.get('contrast', 0.0)),
            'brightness': float(adjustments.get('brightness', 0.0)),
            'highlights': float(adjustments.get('highlights', 0.0)),
            'shadows': float(adjustments.get('shadows', 0.0)),
            'whites': float(adjustments.get('whites', 0.0)),
            'blacks': float(adjustments.get('blacks', 0.0)),
            'temperature': float(adjustments.get('temperature', 0.0)),
            'tint': float(adjustments.get('tint', 0.0)),
            'saturation': float(adjustments.get('saturation', 0.0)),
            'vibrance': float(adjustments.get('vibrance', 0.0)),
            'texture': float(adjustments.get('texture', 0.0)),
        }
        curve_points = normalize_points(adjustments.get('tone_curve'))
        hsl_values = default_hsl_params()
        raw_hsl = adjustments.get('hsl')
        if raw_hsl:
            for key in hsl_values:
                try:
                    hsl_values[key] = float(raw_hsl.get(key, 0.0))
                except (TypeError, ValueError):
                    hsl_values[key] = 0.0
        color_grading_values = default_color_grading_params()
        raw_color_grading = adjustments.get('color_grading')
        if raw_color_grading:
            for key in color_grading_values:
                try:
                    color_grading_values[key] = float(
                        raw_color_grading.get(key, color_grading_values[key])
                    )
                except (TypeError, ValueError):
                    pass
        self._suppress_adjustment_signal = True
        try:
            self._exposure_slider.set_value(merged['exposure'])
            self._contrast_slider.set_value(merged['contrast'])
            self._brightness_slider.set_value(merged['brightness'])
            self._highlights_slider.set_value(merged['highlights'])
            self._shadows_slider.set_value(merged['shadows'])
            self._whites_slider.set_value(merged['whites'])
            self._blacks_slider.set_value(merged['blacks'])
            self._temperature_slider.set_value(merged['temperature'])
            self._tint_slider.set_value(merged['tint'])
            self._saturation_slider.set_value(merged['saturation'])
            self._vibrance_slider.set_value(merged['vibrance'])
            self._texture_slider.set_value(merged['texture'])
            self._curve_editor.set_points(curve_points)
            self._hsl_mixer_panel.set_values(hsl_values)
            self._color_grading_panel.set_values(color_grading_values)
        finally:
            self._suppress_adjustment_signal = False
        self._adjustments = merged
        self._curve_points = list(curve_points)
        self._hsl_values = hsl_values
        self._color_grading_values = color_grading_values
        if emit_signal:
            self.adjustments_changed.emit(self._adjustments.copy())
            self.curve_changed.emit([list(p) for p in self._curve_points])
            self.hsl_changed.emit(dict(self._hsl_values))
            self.color_grading_changed.emit(dict(self._color_grading_values))

    def set_enabled(self, enabled: bool):
        """Enable or disable all controls.

        Args:
            enabled: True to enable, False to disable
        """
        self._exposure_slider.setEnabled(enabled)
        self._contrast_slider.setEnabled(enabled)
        self._brightness_slider.setEnabled(enabled)
        self._highlights_slider.setEnabled(enabled)
        self._shadows_slider.setEnabled(enabled)
        self._whites_slider.setEnabled(enabled)
        self._blacks_slider.setEnabled(enabled)
        self._temperature_slider.setEnabled(enabled)
        self._tint_slider.setEnabled(enabled)
        self._saturation_slider.setEnabled(enabled)
        self._vibrance_slider.setEnabled(enabled)
        self._curve_editor.setEnabled(enabled)
        self._hsl_mixer_panel.setEnabled(enabled)
        self._color_grading_panel.setEnabled(enabled)
        self._texture_slider.setEnabled(enabled)
        self._reset_button.setEnabled(enabled)
