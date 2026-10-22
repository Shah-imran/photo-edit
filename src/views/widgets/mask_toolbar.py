"""The Masking drawer page: the mask list (add Radial/Linear, delete),
the selected mask's type/invert and 4 local adjustment sliders, and
Cancel/Done -- Lightroom's mask panel, in the tool drawer.

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
    QLabel,
    QListWidget,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.views.widgets.adjustment_slider import AdjustmentSlider
from src.views.widgets.tool_drawer import drawer_buttons, drawer_page_qss

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
        add_requested: Emitted with ``"radial"``/``"linear"`` when a new
            mask of that type is requested.
        selection_changed: Emitted with the row index when the user picks
            another mask in the list.
        remove_requested: Delete the selected mask.
        apply_requested / cancel_requested: Done / Cancel.
    """

    mask_type_changed = pyqtSignal(str)
    invert_changed = pyqtSignal(bool)
    adjustments_changed = pyqtSignal(dict)
    add_requested = pyqtSignal(str)
    selection_changed = pyqtSignal(int)
    remove_requested = pyqtSignal()
    apply_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("maskToolbar")
        self._suppress_signals = False
        # Lives in the right panel's tool drawer, under the tool strip (Lightroom layout; docs/UI_UX.md placement spec).
        self.setStyleSheet(drawer_page_qss("maskToolbar"))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 10)
        outer.setSpacing(6)

        # Mask list, as in Lightroom's masks panel.
        header = QHBoxLayout()
        header.setSpacing(4)
        title = QLabel("Masks")
        title.setStyleSheet("font-weight: 600;")
        header.addWidget(title)
        header.addStretch(1)
        self._add_radial_button = QToolButton()
        self._add_radial_button.setText("+ Radial")
        self._add_radial_button.setToolTip("New radial gradient mask")
        self._add_linear_button = QToolButton()
        self._add_linear_button.setText("+ Linear")
        self._add_linear_button.setToolTip("New linear gradient mask")
        for button in (self._add_radial_button, self._add_linear_button):
            button.setStyleSheet(
                "QToolButton { color: #cbd3dc; padding: 2px 6px; border: 1px solid #3a424b;"
                " border-radius: 3px; } QToolButton:hover { background: #2d343c; }"
            )
            header.addWidget(button)
        outer.addLayout(header)

        self._mask_list = QListWidget()
        self._mask_list.setFixedHeight(92)
        self._mask_list.setStyleSheet(
            "QListWidget { background: #161a1e; border: 1px solid #343a42; color: #cbd3dc; }"
            " QListWidget::item { padding: 3px 6px; }"
            " QListWidget::item:selected { background: #2b4a66; color: #ffffff; }"
        )
        outer.addWidget(self._mask_list)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self._type_combo = QComboBox()
        self._type_combo.addItem(_LINEAR_LABEL)
        self._type_combo.addItem(_RADIAL_LABEL)
        # A mask's type is chosen when it is added (+ Radial / + Linear) and,
        # as in Lightroom, not changed afterwards; the list row shows it. The
        # combo stays as the selected mask's type model, hidden.
        self._type_combo.setVisible(False)
        top_row.addWidget(self._type_combo)
        top_row.addStretch(1)
        self._invert_checkbox = QCheckBox("Invert")
        self._invert_checkbox.setToolTip("Apply the adjustments outside the mask instead")
        top_row.addWidget(self._invert_checkbox)
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

        self._remove_button = QPushButton("Delete")
        self._remove_button.setToolTip("Delete the selected mask")
        self._cancel_button, self._apply_button, buttons = drawer_buttons()
        buttons.insertWidget(0, self._remove_button)
        outer.addLayout(buttons)

        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        self._invert_checkbox.toggled.connect(self._on_invert_toggled)
        self._exposure_slider.value_changed.connect(self._on_adjustment_changed)
        self._contrast_slider.value_changed.connect(self._on_adjustment_changed)
        self._saturation_slider.value_changed.connect(self._on_adjustment_changed)
        self._clarity_slider.value_changed.connect(self._on_adjustment_changed)
        self._remove_button.clicked.connect(self.remove_requested)
        self._add_radial_button.clicked.connect(lambda: self.add_requested.emit("radial"))
        self._add_linear_button.clicked.connect(lambda: self.add_requested.emit("linear"))
        self._mask_list.currentRowChanged.connect(self._on_row_changed)
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

    def set_masks(self, labels: list, selected: int) -> None:
        """Show the mask list and select row ``selected``. No signals."""
        self._suppress_signals = True
        try:
            self._mask_list.clear()
            self._mask_list.addItems(list(labels))
            if 0 <= selected < len(labels):
                self._mask_list.setCurrentRow(selected)
        finally:
            self._suppress_signals = False

    def selected_index(self) -> int:
        return self._mask_list.currentRow()

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

    def _on_row_changed(self, row: int) -> None:
        if self._suppress_signals or row < 0:
            return
        self.selection_changed.emit(row)
