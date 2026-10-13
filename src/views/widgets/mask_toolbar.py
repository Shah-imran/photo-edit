"""Compact toolbar for mask-mode type/invert controls, the 4 local
adjustment sliders, and Remove/Cancel/Apply.

Mirrors ``CropToolbar``'s ``QFrame`` structure and dark-chrome styling
(``#202020`` background, ``#343434`` border) so the two toolbars read as
the same family of control, swapped into the same layout slot depending
on whether mask mode is active (and never simultaneously with
``CropToolbar`` -- see docs/planning/implementation-notes/
2026-10-13-mask-tool-ui.md section 5).
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.views.widgets.adjustment_slider import AdjustmentSlider

_LINEAR_LABEL = "Linear"
_RADIAL_LABEL = "Radial"
_TYPE_BY_LABEL = {_LINEAR_LABEL: "linear", _RADIAL_LABEL: "radial"}
_LABEL_BY_TYPE = {"linear": _LINEAR_LABEL, "radial": _RADIAL_LABEL}

# Ranges confirmed directly from MaskProcessor/ImageController's own
# documented _MASK_ADJUSTMENT_RANGES (see
# docs/planning/implementation-notes/2026-10-13-mask-processor.md section
# 3.8) -- the exact same ranges ExposureProcessor/ColorProcessor/
# ClarityProcessor already enforce for the global adjustment stack.
_EXPOSURE_RANGE = (-5.0, 5.0)
_CONTRAST_RANGE = (-100.0, 100.0)
_SATURATION_RANGE = (-100.0, 100.0)
_CLARITY_RANGE = (-100.0, 100.0)


class MaskToolbar(QFrame):
    """View-only toolbar that emits mask-mode intents.

    Signals:
        mask_type_changed: Emitted with ``"linear"``/``"radial"`` whenever
            the type combo selection changes.
        invert_changed: Emitted with a ``bool`` whenever the Invert
            checkbox changes.
        adjustments_changed: Emitted with
            ``{"exposure", "contrast", "saturation", "clarity"}`` whenever
            any of the 4 sliders changes (for live-preview wiring).
        remove_requested / apply_requested / cancel_requested: Emitted
            when the corresponding button is clicked.
    """

    mask_type_changed = pyqtSignal(str)
    invert_changed = pyqtSignal(bool)
    adjustments_changed = pyqtSignal(dict)
    remove_requested = pyqtSignal()
    apply_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("maskToolbar")
        self._suppress_signals = False
        self.setStyleSheet(
            """
            QFrame#maskToolbar {
                background: #202020;
                border-top: 1px solid #343434;
                border-bottom: 1px solid #343434;
            }
            QToolButton, QPushButton { min-width: 28px; min-height: 24px; padding: 2px 7px; }
            QLabel { color: #e0e0e0; }
            QCheckBox { color: #e0e0e0; }
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 6)
        outer.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self._type_combo = QComboBox()
        self._type_combo.addItem(_LINEAR_LABEL)
        self._type_combo.addItem(_RADIAL_LABEL)
        top_row.addWidget(self._type_combo)

        self._invert_checkbox = QCheckBox("Invert")
        top_row.addWidget(self._invert_checkbox)
        top_row.addStretch(1)

        self._remove_button = QPushButton("Remove Mask")
        self._cancel_button = QPushButton("Cancel")
        self._apply_button = QPushButton("Apply")
        top_row.addWidget(self._remove_button)
        top_row.addWidget(self._cancel_button)
        top_row.addWidget(self._apply_button)
        outer.addLayout(top_row)

        self._exposure_slider = AdjustmentSlider(
            "Exposure", min_value=_EXPOSURE_RANGE[0], max_value=_EXPOSURE_RANGE[1],
            default_value=0.0, step=0.1,
        )
        self._contrast_slider = AdjustmentSlider(
            "Contrast", min_value=_CONTRAST_RANGE[0], max_value=_CONTRAST_RANGE[1],
            default_value=0.0, step=1.0, decimals=0,
        )
        self._saturation_slider = AdjustmentSlider(
            "Saturation", min_value=_SATURATION_RANGE[0], max_value=_SATURATION_RANGE[1],
            default_value=0.0, step=1.0, decimals=0,
        )
        self._clarity_slider = AdjustmentSlider(
            "Clarity", min_value=_CLARITY_RANGE[0], max_value=_CLARITY_RANGE[1],
            default_value=0.0, step=1.0, decimals=0,
        )
        for slider in (
            self._exposure_slider,
            self._contrast_slider,
            self._saturation_slider,
            self._clarity_slider,
        ):
            outer.addWidget(slider)

        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        self._invert_checkbox.toggled.connect(self._on_invert_toggled)
        self._exposure_slider.value_changed.connect(self._on_adjustment_changed)
        self._contrast_slider.value_changed.connect(self._on_adjustment_changed)
        self._saturation_slider.value_changed.connect(self._on_adjustment_changed)
        self._clarity_slider.value_changed.connect(self._on_adjustment_changed)
        self._remove_button.clicked.connect(self.remove_requested)
        self._cancel_button.clicked.connect(self.cancel_requested)
        self._apply_button.clicked.connect(self.apply_requested)

    # -- Public API -----------------------------------------------------

    def set_values(
        self,
        mask_type: str,
        invert: bool,
        exposure: float,
        contrast: float,
        saturation: float,
        clarity: float,
    ) -> None:
        """Programmatic init, no signal emission (mask-mode entry)."""
        self._suppress_signals = True
        try:
            self._type_combo.setCurrentText(_LABEL_BY_TYPE.get(mask_type, _LINEAR_LABEL))
            self._invert_checkbox.setChecked(bool(invert))
            self._exposure_slider.set_value(exposure)
            self._contrast_slider.set_value(contrast)
            self._saturation_slider.set_value(saturation)
            self._clarity_slider.set_value(clarity)
        finally:
            self._suppress_signals = False

    def get_adjustments(self) -> dict:
        return {
            "exposure": self._exposure_slider.get_value(),
            "contrast": self._contrast_slider.get_value(),
            "saturation": self._saturation_slider.get_value(),
            "clarity": self._clarity_slider.get_value(),
        }

    def get_mask_type(self) -> str:
        return _TYPE_BY_LABEL.get(self._type_combo.currentText(), "linear")

    def get_invert(self) -> bool:
        return self._invert_checkbox.isChecked()

    # -- Internal slots ---------------------------------------------------

    def _on_type_changed(self, text: str) -> None:
        if self._suppress_signals:
            return
        self.mask_type_changed.emit(_TYPE_BY_LABEL.get(text, "linear"))

    def _on_invert_toggled(self, checked: bool) -> None:
        if self._suppress_signals:
            return
        self.invert_changed.emit(bool(checked))

    def _on_adjustment_changed(self, _value: float) -> None:
        if self._suppress_signals:
            return
        self.adjustments_changed.emit(self.get_adjustments())
