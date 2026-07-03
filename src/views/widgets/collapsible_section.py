"""Reusable collapsible section widget for side panels."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class CollapsibleSection(QFrame):
    """A titled section with a toggleable content area."""

    toggled = pyqtSignal(bool)

    def __init__(
        self,
        title: str,
        parent: Optional[QWidget] = None,
        expanded: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            """
            QFrame {
                background-color: transparent;
            }
            QToolButton {
                color: #a0a0a0;
                font-size: 12px;
                font-weight: bold;
                border: none;
                padding: 0 0 4px 0;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        self._toggle_button = QToolButton()
        self._toggle_button.setText(title)
        self._toggle_button.setCheckable(True)
        self._toggle_button.setChecked(expanded)
        self._toggle_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self._toggle_button.clicked.connect(self.set_expanded)
        header_layout.addWidget(self._toggle_button)
        header_layout.addStretch(1)
        layout.addWidget(header)

        self._content_container = QWidget()
        self._content_layout = QVBoxLayout(self._content_container)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        layout.addWidget(self._content_container)

        self._content_container.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )
        self.set_expanded(expanded)

    def add_header_widget(self, widget: QWidget) -> None:
        """Add a control to the right side of the section header."""
        header_layout = self.layout().itemAt(0).widget().layout()
        header_layout.insertWidget(header_layout.count() - 1, widget)

    def set_content_widget(self, widget: QWidget) -> None:
        """Replace the section content with the given widget."""
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            old = item.widget()
            if old is not None:
                old.setParent(None)
        self._content_layout.addWidget(widget)

    def is_expanded(self) -> bool:
        return self._toggle_button.isChecked()

    def title(self) -> str:
        return self._toggle_button.text()

    def set_header_title(self, title: str) -> None:
        self._toggle_button.setText(title)

    def set_fill_available_space(self, fill: bool) -> None:
        """Control whether the section should expand vertically."""
        policy = (
            QSizePolicy.Policy.Expanding if fill else QSizePolicy.Policy.Maximum
        )
        self.setSizePolicy(QSizePolicy.Policy.Preferred, policy)
        self._content_container.setSizePolicy(QSizePolicy.Policy.Preferred, policy)

    def set_expanded(self, expanded: bool) -> None:
        """Show or hide the content area."""
        self._toggle_button.setChecked(expanded)
        arrow = (
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self._toggle_button.setArrowType(arrow)
        self._content_container.setVisible(expanded)
        self.toggled.emit(expanded)
