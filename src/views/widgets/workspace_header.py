"""Top-level workspace navigation and primary actions."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from src.views.icons import line_icon


class WorkspaceHeader(QFrame):
    """Lightroom-style application header with workspace and action controls."""

    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()
    compare_requested = pyqtSignal()
    export_requested = pyqtSignal()
    workspace_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceHeader")
        self.setFixedHeight(54)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            """
            QFrame#workspaceHeader { background: #171a1e; border-bottom: 1px solid #343a42; }
            QLabel#workspaceBrand { font-size: 20px; font-weight: 700; color: white; }
            QPushButton#workspaceTab { background: transparent; border: none; border-radius: 0;
                color: #9da6b0; font-size: 13px; padding: 17px 24px 13px 24px; }
            QPushButton#workspaceTab:checked { color: white; border-bottom: 3px solid #168cff; }
            QToolButton#headerAction { background: transparent; border: none; color: #cbd3dc;
                padding: 7px 9px; }
            QToolButton#headerAction:hover { background: #2a3037; }
            QToolButton#exportAction { background: #168cff; border: none; color: white;
                border-radius: 5px; padding: 8px 14px; font-weight: 600; }
            QToolButton#exportAction:hover { background: #2a9aff; }
            """
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 14, 0)
        layout.setSpacing(4)
        brand = QLabel("PhotoEdit")
        brand.setObjectName("workspaceBrand")
        layout.addWidget(brand)
        layout.addStretch(2)

        self._library_tab = self._tab("Library", False)
        self._develop_tab = self._tab("Develop", True)
        self._library_tab.clicked.connect(lambda: self._select_workspace("library"))
        self._develop_tab.clicked.connect(lambda: self._select_workspace("develop"))
        layout.addWidget(self._library_tab)
        layout.addWidget(self._develop_tab)
        layout.addStretch(2)

        self._undo_button = self._action("Undo", "undo", self.undo_requested)
        self._redo_button = self._action("Redo", "redo", self.redo_requested)
        self._compare_button = self._action("Compare", "compare", self.compare_requested)
        self._compare_button.setEnabled(False)
        self._compare_button.setToolTip("Before / After comparison is not implemented yet")
        self._export_button = self._action("Export", "export", self.export_requested)
        self._export_button.setObjectName("exportAction")
        for button in (self._undo_button, self._redo_button, self._compare_button, self._export_button):
            layout.addWidget(button)

    @staticmethod
    def _tab(text: str, checked: bool) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("workspaceTab")
        button.setCheckable(True)
        button.setChecked(checked)
        return button

    def _select_workspace(self, workspace: str) -> None:
        is_library = workspace == "library"
        self._library_tab.setChecked(is_library)
        self._develop_tab.setChecked(not is_library)
        self.workspace_changed.emit(workspace)

    @staticmethod
    def _action(text: str, icon_name: str, signal) -> QToolButton:
        button = QToolButton()
        button.setObjectName("headerAction")
        button.setText(text)
        button.setIcon(line_icon(icon_name))
        button.setIconSize(button.iconSize())
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setAccessibleName(text)
        button.clicked.connect(signal)
        return button


class EditingToolStrip(QFrame):
    """Visible home for future local-editing tools."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("editingToolStrip")
        self.setStyleSheet(
            """
            QFrame#editingToolStrip { background: #20252b; border-top: 1px solid #343a42;
                border-bottom: 1px solid #343a42; }
            QToolButton { background: transparent; border: none; border-radius: 4px;
                padding: 7px 4px; color: #cbd3dc; min-width: 56px; }
            QToolButton:hover { background: #2d343c; }
            QToolButton:disabled { color: #79818a; }
            """
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        for label, icon_name in (
            ("Crop", "crop"),
            ("Heal", "heal"),
            ("Mask", "mask"),
            ("Transform", "transform"),
        ):
            button = QToolButton()
            button.setText(label)
            button.setIcon(line_icon(icon_name, "#b8c2cc", 20))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setEnabled(False)
            button.setToolTip(f"{label} is planned but not implemented yet")
            button.setAccessibleName(label)
            layout.addWidget(button, 1)
