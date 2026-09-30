"""Color Grading widget: Shadows/Midtones/Highlights + Blending/Balance.

No adjustment math lives here (INCREMENTAL_WORKFLOW.md section 5.1) -- it
only reports raw slider values via ``values_changed``. The actual per-range
weighting/tint-blend math lives in
:mod:`src.processors.color_grading_processor`, which also owns the range
names/order (:data:`COLOR_GRADING_RANGES`) this widget builds its tabs
from.

Uses three Hue/Saturation/Luminance sliders per tonal range instead of a
literal 2D color wheel -- a deliberate UI simplification documented in
docs/planning/implementation-notes/2026-09-30-color-grading.md section 1,
the same pragmatic choice ``HslMixerPanel`` already made.
"""

from __future__ import annotations

from typing import Dict, Optional

from PyQt6.QtWidgets import QTabWidget, QVBoxLayout, QWidget
from PyQt6.QtCore import pyqtSignal

from src.processors.color_grading_processor import (
    COLOR_GRADING_RANGES,
    default_color_grading_params,
)
from src.views.widgets.adjustment_slider import AdjustmentSlider

_RANGE_LABELS = {
    "shadows": "Shadows",
    "midtones": "Midtones",
    "highlights": "Highlights",
}

_CHANNEL_SPECS = {
    "hue": ("Hue", 0.0, 360.0, 0.0),
    "sat": ("Saturation", 0.0, 100.0, 0.0),
    "lum": ("Luminance", -100.0, 100.0, 0.0),
}


class ColorGradingPanel(QWidget):
    """Tabbed Hue/Saturation/Luminance sliders per tonal range, plus
    always-visible Blending/Balance sliders.

    Signals:
        values_changed: Emitted with the full 11-key flat dict whenever
            any slider changes.
        slider_released: Emitted when any slider is released (for final
            processing), mirroring ``AdjustmentSlider.slider_released``.
    """

    values_changed = pyqtSignal(dict)
    slider_released = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._values: Dict[str, float] = default_color_grading_params()
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

        for range_ in COLOR_GRADING_RANGES:
            self._tabs.addTab(self._build_range_tab(range_), _RANGE_LABELS[range_])

        self._add_global_slider("blending", "Blending", 0.0, 100.0, 50.0)
        self._add_global_slider("balance", "Balance", -100.0, 100.0, 0.0)
        layout.addStretch()

    def _build_range_tab(self, range_: str) -> QWidget:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(8, 8, 8, 8)
        tab_layout.setSpacing(4)
        for channel, (label, min_value, max_value, _default) in _CHANNEL_SPECS.items():
            key = f"{range_}_{channel}"
            slider = self._make_slider(key, label, min_value, max_value, 0.0)
            tab_layout.addWidget(slider)
        tab_layout.addStretch()
        return tab

    def _add_global_slider(
        self, key: str, label: str, min_value: float, max_value: float, default: float
    ) -> None:
        slider = self._make_slider(key, label, min_value, max_value, default)
        self.layout().addWidget(slider)

    def _make_slider(
        self,
        key: str,
        label: str,
        min_value: float,
        max_value: float,
        default_value: float,
    ) -> AdjustmentSlider:
        slider = AdjustmentSlider(
            label,
            min_value=min_value,
            max_value=max_value,
            default_value=default_value,
            step=1.0,
            decimals=0,
        )
        slider.value_changed.connect(
            lambda value, key=key: self._on_slider_changed(key, value)
        )
        slider.slider_released.connect(self._on_slider_released)
        self._sliders[key] = slider
        return slider

    def _on_slider_changed(self, key: str, value: float) -> None:
        self._values[key] = value
        if not self._suppress_signal:
            self.values_changed.emit(dict(self._values))

    def _on_slider_released(self, value: float) -> None:
        if not self._suppress_signal:
            self.slider_released.emit()

    def get_values(self) -> Dict[str, float]:
        """Return a copy of the current 11-key flat parameter dict."""
        return dict(self._values)

    def set_values(self, values: Optional[Dict[str, float]]) -> None:
        """Restore state from a (possibly partial/malformed) dict.

        Missing or invalid entries default to identity -- tolerant, like
        every other restore path in this codebase.
        """
        merged = default_color_grading_params()
        if values:
            for key in merged:
                try:
                    merged[key] = float(values.get(key, merged[key]))
                except (TypeError, ValueError):
                    pass

        self._suppress_signal = True
        try:
            for key, slider in self._sliders.items():
                slider.set_value(merged[key])
        finally:
            self._suppress_signal = False
        self._values = merged
