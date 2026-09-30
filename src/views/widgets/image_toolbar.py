"""Compact controls displayed directly below the image canvas."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QWidget


class ImageToolBar(QFrame):
    """View-only toolbar that emits image navigation intents."""

    fit_requested = pyqtSignal()
    actual_size_requested = pyqtSignal()
    zoom_in_requested = pyqtSignal()
    zoom_out_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("imageToolbar")
        self.setFixedHeight(44)
        self.setStyleSheet(
            """
            QFrame#imageToolbar {
                background: #202020;
                border-top: 1px solid #343434;
                border-bottom: 1px solid #343434;
            }
            QToolButton { min-width: 28px; min-height: 24px; padding: 2px 7px; }
            QLabel#toolbarZoomLabel { color: #d8d8d8; min-width: 44px; }
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(6)
        layout.addStretch(1)

        self._before_after_button = self._button("Y", "Before / After (coming soon)")
        self._before_after_button.setEnabled(False)
        layout.addWidget(self._before_after_button)
        layout.addSpacing(8)

        self._fit_button = self._button("Fit", "Fit image to window")
        self._actual_size_button = self._button("100%", "View at actual pixel size")
        self._zoom_out_button = self._button("−", "Zoom out")
        self._zoom_label = QLabel("100%")
        self._zoom_label.setObjectName("toolbarZoomLabel")
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_in_button = self._button("+", "Zoom in")

        for widget in (
            self._fit_button,
            self._actual_size_button,
            self._zoom_out_button,
            self._zoom_label,
            self._zoom_in_button,
        ):
            layout.addWidget(widget)

        self._pan_button = self._button("Hand", "Pan by dragging the image")
        self._pan_button.setCheckable(True)
        self._pan_button.setChecked(True)
        self._pan_button.setEnabled(False)
        layout.addSpacing(8)
        layout.addWidget(self._pan_button)
        layout.addStretch(1)

        self._fit_button.clicked.connect(self.fit_requested)
        self._actual_size_button.clicked.connect(self.actual_size_requested)
        self._zoom_in_button.clicked.connect(self.zoom_in_requested)
        self._zoom_out_button.clicked.connect(self.zoom_out_requested)

    @staticmethod
    def _button(text: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def set_zoom_factor(self, zoom_factor: float) -> None:
        percent = max(1, int(round(zoom_factor * 100)))
        self._zoom_label.setText(f"{percent}%")

