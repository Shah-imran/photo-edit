"""Compact toolbar for crop-mode aspect-ratio presets and Apply/Cancel.

Mirrors ``ImageToolBar``'s ``QFrame`` structure and dark-chrome styling
(``#202020`` background, ``#343434`` border) so the two toolbars read as
the same family of control, swapped in and out of the same spot in the
layout depending on whether crop mode is active.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from src.views.widgets.tool_drawer import drawer_buttons, drawer_page_qss

# (label, ratio-or-None). "Free" (no lock) and "Original" (resolved at
# runtime via set_original_ratio) are handled specially; the rest are
# fixed W/H ratios.
_FREE = "Free"
_ORIGINAL = "Original"
_FIXED_PRESETS = (
    ("1:1", 1.0),
    ("16:9", 16.0 / 9.0),
    ("9:16", 9.0 / 16.0),
    ("4:3", 4.0 / 3.0),
    ("3:4", 3.0 / 4.0),
    ("5:4", 5.0 / 4.0),
    ("4:5", 4.0 / 5.0),
)


class CropToolbar(QFrame):
    """View-only toolbar that emits crop-mode intents.

    Signals:
        aspect_ratio_changed: Emitted with a ``float`` ratio, or ``None``
            for "Free", whenever the aspect-ratio combo selection changes.
        apply_requested: Emitted when "Apply" is clicked.
        cancel_requested: Emitted when "Cancel" is clicked.
    """

    aspect_ratio_changed = pyqtSignal(object)
    apply_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("cropToolbar")
        # Lives in the right panel's tool drawer, under the tool strip (Lightroom layout; docs/UI_UX.md placement spec).
        self.setStyleSheet(drawer_page_qss("cropToolbar"))

        self._original_ratio: Optional[float] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(8)

        aspect_row = QHBoxLayout()
        aspect_row.addWidget(QLabel("Aspect"))
        self._aspect_combo = QComboBox()
        self._aspect_combo.addItem(_FREE)
        self._aspect_combo.addItem(_ORIGINAL)
        for label, _ratio in _FIXED_PRESETS:
            self._aspect_combo.addItem(label)
        aspect_row.addWidget(self._aspect_combo, 1)
        layout.addLayout(aspect_row)

        self._cancel_button, self._apply_button, buttons = drawer_buttons()
        layout.addLayout(buttons)

        self._aspect_combo.currentTextChanged.connect(self._on_combo_changed)
        self._apply_button.clicked.connect(self.apply_requested)
        self._cancel_button.clicked.connect(self.cancel_requested)

    def set_original_ratio(self, ratio: Optional[float]) -> None:
        """Set the ratio the "Original" combo entry resolves to.

        Called by the caller (``MainWindow``) once, at crop-mode-entry
        time, since this widget itself has no idea of the image's actual
        dimensions.
        """
        self._original_ratio = ratio
        if self._aspect_combo.currentText() == _ORIGINAL:
            self.aspect_ratio_changed.emit(self._original_ratio)

    def _on_combo_changed(self, text: str) -> None:
        if text == _FREE:
            self.aspect_ratio_changed.emit(None)
            return
        if text == _ORIGINAL:
            self.aspect_ratio_changed.emit(self._original_ratio)
            return
        for label, ratio in _FIXED_PRESETS:
            if label == text:
                self.aspect_ratio_changed.emit(ratio)
                return

    def reset_to_free(self) -> None:
        """Reset the combo to "Free" without emitting (crop-mode entry)."""
        self._aspect_combo.blockSignals(True)
        self._aspect_combo.setCurrentText(_FREE)
        self._aspect_combo.blockSignals(False)
