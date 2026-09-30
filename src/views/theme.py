"""Centralized visual tokens and application stylesheet for PhotoEdit."""

from __future__ import annotations

from PyQt6.QtWidgets import QApplication


COLORS = {
    "background": "#1a1a1a",
    "panel": "#242424",
    "card": "#2d2d2d",
    "border": "#3a3a3a",
    "text": "#e0e0e0",
    "muted": "#a0a0a0",
    "disabled": "#606060",
    "accent": "#0078d4",
    "accent_hover": "#0086f0",
    "accent_active": "#005a9e",
}


APP_STYLESHEET = """
QWidget {
    color: #e0e0e0;
    font-family: "Segoe UI";
    font-size: 11px;
}
QMainWindow, QDialog { background: #1a1a1a; }
QMenuBar {
    background: #1d1d1d;
    border-bottom: 1px solid #343434;
    padding: 3px 8px;
}
QMenuBar::item { padding: 5px 10px; border-radius: 3px; }
QMenuBar::item:selected { background: #343434; }
QMenu {
    background: #242424;
    border: 1px solid #3a3a3a;
    padding: 5px;
}
QMenu::item { padding: 6px 28px 6px 10px; border-radius: 3px; }
QMenu::item:selected { background: #005a9e; color: white; }
QDockWidget {
    background: #242424;
    color: #e0e0e0;
    font-weight: 600;
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}
QDockWidget::title {
    background: #202020;
    border-bottom: 1px solid #3a3a3a;
    padding: 9px 12px;
    text-align: left;
}
QDockWidget > QWidget { border: none; }
QStatusBar {
    background: #202020;
    border-top: 1px solid #353535;
    color: #a0a0a0;
}
QStatusBar::item { border: none; }
QPushButton, QToolButton {
    background: #303030;
    border: 1px solid #414141;
    border-radius: 4px;
    padding: 5px 9px;
}
QPushButton:hover, QToolButton:hover { background: #3a3a3a; }
QPushButton:pressed, QToolButton:pressed { background: #252525; }
QPushButton:checked, QToolButton:checked {
    background: #005a9e;
    border-color: #0078d4;
}
QPushButton:disabled, QToolButton:disabled { color: #606060; }
QLineEdit, QSpinBox, QDoubleSpinBox {
    background: #2b2b2b;
    border: 1px solid #424242;
    border-radius: 3px;
    padding: 3px 6px;
    selection-background-color: #0078d4;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #0078d4;
}
QScrollArea, QAbstractScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #202020; width: 9px; margin: 0; }
QScrollBar:horizontal { background: #202020; height: 9px; margin: 0; }
QScrollBar::handle { background: #515151; border-radius: 4px; min-height: 28px; min-width: 28px; }
QScrollBar::handle:hover { background: #666666; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSlider::groove:horizontal {
    height: 2px;
    background: #484848;
    border-radius: 1px;
}
QSlider::sub-page:horizontal { background: #0078d4; border-radius: 1px; }
QSlider::handle:horizontal {
    width: 12px;
    height: 12px;
    margin: -5px 0;
    background: #e2e2e2;
    border: 1px solid #707070;
    border-radius: 6px;
}
QSlider::handle:horizontal:hover { background: white; border-color: #0086f0; }
QProgressBar {
    background: #2d2d2d;
    border: 1px solid #3a3a3a;
    border-radius: 3px;
}
QProgressBar::chunk { background: #0078d4; border-radius: 2px; }
QToolTip {
    background: #303030;
    color: #e0e0e0;
    border: 1px solid #505050;
    padding: 4px;
}
"""


def apply_theme(app: QApplication | None = None) -> None:
    """Install the PhotoEdit theme on an application, if one exists."""
    application = app or QApplication.instance()
    if application is not None and application.styleSheet() != APP_STYLESHEET:
        application.setStyleSheet(APP_STYLESHEET)

