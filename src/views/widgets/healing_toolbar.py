"""Compact toolbar for heal-mode mode/feather/opacity controls and
Remove Last/Clear All/Cancel/Apply.

Mirrors ``MaskToolbar``'s ``QFrame`` structure and dark-chrome styling
(``#202020`` background, ``#343434`` border) so the three toolbars
(Crop/Mask/Heal) read as the same family of control, swapped into the same
layout slot depending on which interactive tool mode is active (never
simultaneously with ``CropToolbar``/``MaskToolbar`` -- see
docs/planning/implementation-notes/2026-10-13-healing-tool-ui.md section 5
on three-way mutual exclusion).

**What each control affects, exactly** (see the implementation note in
full): the Mode combo, and the Feather/Opacity sliders, set the values
that will be baked into the NEXT spot placed on the overlay -- they never
retroactively change an already-placed spot (there is no per-spot editing
in this v1). There is deliberately no "radius" control here: radius is
determined entirely by the drag gesture (press = center, drag distance =
radius), not by a toolbar default.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from src.views.widgets.adjustment_slider import AdjustmentSlider
from src.views.widgets.tool_drawer import drawer_buttons, drawer_page_qss

_HEAL_LABEL = "Heal"
_CLONE_LABEL = "Clone"
_MODE_BY_LABEL = {_HEAL_LABEL: "heal", _CLONE_LABEL: "clone"}
_LABEL_BY_MODE = {"heal": _HEAL_LABEL, "clone": _CLONE_LABEL}

# Feather/opacity are both 0..1 fractions per HealingProcessor's own
# contract (docs/planning/implementation-notes/
# 2026-10-13-healing-processor.md section 4) -- confirmed from the slice 1
# state shape, not guessed.
_FEATHER_RANGE = (0.0, 1.0)
_OPACITY_RANGE = (0.0, 1.0)


class HealingToolbar(QFrame):
    """View-only toolbar that emits heal-mode intents.

    Signals:
        mode_changed: Emitted with ``"heal"``/``"clone"`` whenever the
            mode combo selection changes.
        feather_changed: Emitted with a ``float`` (0..1) whenever the
            Feather slider changes.
        opacity_changed: Emitted with a ``float`` (0..1) whenever the
            Opacity slider changes.
        remove_last_requested / clear_all_requested / apply_requested /
            cancel_requested: Emitted when the corresponding button is
            clicked.
    """

    mode_changed = pyqtSignal(str)
    feather_changed = pyqtSignal(float)
    opacity_changed = pyqtSignal(float)
    remove_last_requested = pyqtSignal()
    clear_all_requested = pyqtSignal()
    apply_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("healingToolbar")
        self._suppress_signals = False
        # Lives in the right panel's tool drawer, under the tool strip (Lightroom layout; docs/UI_UX.md placement spec).
        self.setStyleSheet(drawer_page_qss("healingToolbar"))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 10)
        outer.setSpacing(6)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItem(_HEAL_LABEL)
        self._mode_combo.addItem(_CLONE_LABEL)
        mode_row.addWidget(self._mode_combo, 1)
        outer.addLayout(mode_row)

        self._feather_slider = AdjustmentSlider(
            "Feather", min_value=_FEATHER_RANGE[0], max_value=_FEATHER_RANGE[1],
            default_value=0.3, step=0.01, decimals=2,
        )
        self._opacity_slider = AdjustmentSlider(
            "Opacity", min_value=_OPACITY_RANGE[0], max_value=_OPACITY_RANGE[1],
            default_value=1.0, step=0.01, decimals=2,
        )
        outer.addWidget(self._feather_slider)
        outer.addWidget(self._opacity_slider)

        spots_row = QHBoxLayout()
        self._remove_last_button = QPushButton("Remove Last")
        self._clear_all_button = QPushButton("Clear All")
        spots_row.addWidget(self._remove_last_button)
        spots_row.addWidget(self._clear_all_button)
        outer.addLayout(spots_row)
        self._cancel_button, self._apply_button, buttons = drawer_buttons()
        outer.addLayout(buttons)

        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        self._feather_slider.value_changed.connect(self._on_feather_changed)
        self._opacity_slider.value_changed.connect(self._on_opacity_changed)
        self._remove_last_button.clicked.connect(self.remove_last_requested)
        self._clear_all_button.clicked.connect(self.clear_all_requested)
        self._cancel_button.clicked.connect(self.cancel_requested)
        self._apply_button.clicked.connect(self.apply_requested)

    # -- Public API -----------------------------------------------------

    def set_values(self, mode: str, feather: float, opacity: float) -> None:
        """Programmatic init, no signal emission (heal-mode entry)."""
        self._suppress_signals = True
        try:
            self._mode_combo.setCurrentText(_LABEL_BY_MODE.get(mode, _HEAL_LABEL))
            self._feather_slider.set_value(feather)
            self._opacity_slider.set_value(opacity)
        finally:
            self._suppress_signals = False

    def get_mode(self) -> str:
        return _MODE_BY_LABEL.get(self._mode_combo.currentText(), "heal")

    def get_feather(self) -> float:
        return self._feather_slider.get_value()

    def get_opacity(self) -> float:
        return self._opacity_slider.get_value()

    # -- Internal slots ---------------------------------------------------

    def _on_mode_changed(self, text: str) -> None:
        if self._suppress_signals:
            return
        self.mode_changed.emit(_MODE_BY_LABEL.get(text, "heal"))

    def _on_feather_changed(self, value: float) -> None:
        if self._suppress_signals:
            return
        self.feather_changed.emit(float(value))

    def _on_opacity_changed(self, value: float) -> None:
        if self._suppress_signals:
            return
        self.opacity_changed.emit(float(value))
