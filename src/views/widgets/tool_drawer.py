"""The tool drawer: local-tool options under the tool strip.

Lightroom shows a selected tool's options in a drawer directly under the
tool strip in the right panel; the adjustment panels stay below it and the
photo keeps its full height. Crop, Heal and Mask pages live here (see the
placement spec in docs/UI_UX.md).
"""

from __future__ import annotations

from typing import Dict, Optional

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget


def drawer_page_qss(object_name: str) -> str:
    """Shared look for a drawer page (a tool's options)."""
    return f"""
        QFrame#{object_name} {{ background: #1d2227; border: none; }}
        QLabel, QCheckBox {{ color: #cbd3dc; }}
        QPushButton {{ min-height: 24px; padding: 2px 10px; }}
        QPushButton#drawerDone {{ background: #0e639c; color: white; border: none;
            border-radius: 3px; }}
        QPushButton#drawerDone:hover {{ background: #1177bb; }}
    """


def drawer_buttons():
    """``(cancel_button, done_button, row_layout)`` for a drawer page.

    "Done" commits the tool's edit, like Lightroom's Done button (clicking
    the active tool again does the same).
    """
    cancel = QPushButton("Cancel")
    done = QPushButton("Done")
    done.setObjectName("drawerDone")
    done.setDefault(True)
    row = QHBoxLayout()
    row.addStretch(1)
    row.addWidget(cancel)
    row.addWidget(done)
    return cancel, done, row


class ToolDrawer(QFrame):
    """Holds one page per tool; shows only the active tool's page and
    collapses entirely when no tool is active."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("toolDrawer")
        self.setStyleSheet(
            "QFrame#toolDrawer { background: #1d2227; border-bottom: 1px solid #343a42; }"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._pages: Dict[str, QWidget] = {}
        self._active: Optional[str] = None
        self.hide()

    def add_page(self, name: str, page: QWidget) -> None:
        page.hide()
        self._pages[name] = page
        self._layout.addWidget(page)

    def page(self, name: str) -> QWidget:
        return self._pages[name]

    @property
    def active(self) -> Optional[str]:
        return self._active

    def show_page(self, name: Optional[str]) -> None:
        """Show ``name``'s page (or collapse the drawer for None)."""
        self._active = name
        for page_name, page in self._pages.items():
            page.setVisible(page_name == name)
        self.setVisible(name is not None)
