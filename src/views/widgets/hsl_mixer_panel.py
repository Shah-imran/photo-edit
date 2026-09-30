"""HSL Color Mixer widget: 8 color bands x Hue/Saturation/Luminance tabs.

No adjustment math lives here (INCREMENTAL_WORKFLOW.md section 5.1) -- it
only reports raw slider values via ``values_changed``. The actual per-band
weighting/hue-rotation math lives in
:mod:`src.processors.hsl_mixer_processor`, which also owns the band
names/order (:data:`HSL_BAND_NAMES`) this widget builds its sliders from.
"""

from __future__ import annotations

from typing import Dict, Optional

from PyQt6.QtWidgets import QTabWidget, QVBoxLayout, QWidget
from PyQt6.QtCore import pyqtSignal

from src.processors.hsl_mixer_processor import (
    HSL_BAND_NAMES,
    HSL_CHANNELS,
    default_hsl_params,
)
from src.views.widgets.adjustment_slider import AdjustmentSlider

_CHANNEL_LABELS = {"hue": "Hue", "sat": "Saturation", "lum": "Luminance"}
_BAND_LABELS = {
    "red": "Red",
    "orange": "Orange",
    "yellow": "Yellow",
    "green": "Green",
    "aqua": "Aqua",
    "blue": "Blue",
    "purple": "Purple",
    "magenta": "Magenta",
}


class HslMixerPanel(QWidget):
    """Tabbed Hue/Saturation/Luminance sliders for 8 color bands.

    Signals:
        values_changed: Emitted with the full 24-key flat dict whenever
            any slider changes.
        slider_released: Emitted when any slider is released (for final
            processing), mirroring ``AdjustmentSlider.slider_released``.
    """

    values_changed = pyqtSignal(dict)
    slider_released = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._values: Dict[str, float] = default_hsl_params()
        self._suppress_signal = False
        self._sliders: Dict[str, AdjustmentSlider] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            """
            QTabWidget::pane {
                border: 1px solid #3a3a3a;
                border-radius: 4px;
            }
            QTabBar::tab {
                background: #2d2d2d;
                color: #a0a0a0;
                padding: 4px 10px;
                font-size: 11px;
            }
            QTabBar::tab:selected {
                background: #3a3a3a;
                color: #e0e0e0;
            }
            """
        )
        layout.addWidget(self._tabs)

        for channel in HSL_CHANNELS:
            self._tabs.addTab(self._build_channel_tab(channel), _CHANNEL_LABELS[channel])

    def _build_channel_tab(self, channel: str) -> QWidget:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(8, 8, 8, 8)
        tab_layout.setSpacing(4)
        for band in HSL_BAND_NAMES:
            key = f"{band}_{channel}"
            slider = AdjustmentSlider(
                _BAND_LABELS[band],
                min_value=-100.0,
                max_value=100.0,
                default_value=0.0,
                step=1.0,
                decimals=0,
            )
            slider.value_changed.connect(
                lambda value, key=key: self._on_slider_changed(key, value)
            )
            slider.slider_released.connect(self._on_slider_released)
            self._sliders[key] = slider
            tab_layout.addWidget(slider)
        tab_layout.addStretch()
        return tab

    def _on_slider_changed(self, key: str, value: float) -> None:
        self._values[key] = value
        if not self._suppress_signal:
            self.values_changed.emit(dict(self._values))

    def _on_slider_released(self, value: float) -> None:
        if not self._suppress_signal:
            self.slider_released.emit()

    def get_values(self) -> Dict[str, float]:
        """Return a copy of the current 24-key flat parameter dict."""
        return dict(self._values)

    def set_values(self, values: Optional[Dict[str, float]]) -> None:
        """Restore state from a (possibly partial/malformed) dict.

        Missing or invalid entries default to 0 -- tolerant, like every
        other restore path in this codebase.
        """
        merged = default_hsl_params()
        if values:
            for key in merged:
                try:
                    merged[key] = float(values.get(key, 0.0))
                except (TypeError, ValueError):
                    merged[key] = 0.0

        self._suppress_signal = True
        try:
            for key, slider in self._sliders.items():
                slider.set_value(merged[key])
        finally:
            self._suppress_signal = False
        self._values = merged
