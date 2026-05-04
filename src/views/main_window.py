"""Main window for PhotoEdit application."""

import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QDockWidget,
    QLabel,
    QStatusBar,
    QFileDialog,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QAction


logger = logging.getLogger(__name__)

from src.views.image_view import ImageView
from src.views.tools_panel import ToolsPanel
from src.views.export_dialog import ExportDialog
from src.views.library_view import LibraryView
from src.controllers.image_controller import ImageController
from src.services.settings_service import SettingsService


class MainWindow(QMainWindow):
    """Main application window with Lightroom-like layout.
    
    The window features a three-panel layout:
    - Left: Library panel (for image browsing)
    - Center: Image view (for editing)
    - Right: Tools panel (for adjustments)
    """

    def __init__(self, settings_service: Optional[SettingsService] = None):
        """Initialize the main window.

        Args:
            settings_service: Optional SettingsService instance. When ``None``,
                a default one is created using the application's QSettings.
        """
        super().__init__()
        self.setWindowTitle("PhotoEdit")
        self.setMinimumSize(1200, 800)
        
        # One settings service shared by the window and its consumers.
        self._settings_service = settings_service or SettingsService()
        
        # Initialize components
        self._image_view = ImageView()
        self._tools_panel = ToolsPanel()
        self._library_view = LibraryView(settings_service=self._settings_service)
        self._image_controller = ImageController(
            self._image_view, settings_service=self._settings_service
        )
        
        # Set up UI
        self._setup_ui()
        self._setup_menu_bar()
        self._setup_status_bar()
        self._setup_shortcuts()
        self._connect_signals()
        self._restore_window_geometry()

    def _setup_ui(self):
        """Set up the main UI components."""
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QHBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Add image view as central widget
        layout.addWidget(self._image_view)
        
        # Left panel - Library
        self.library_dock = QDockWidget("Library", self)
        self.library_dock.setWidget(self._library_view)
        self.library_dock.setMinimumWidth(200)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.library_dock)
        
        # Right panel - Tools
        self.tools_dock = QDockWidget("Adjustments", self)
        self.tools_dock.setWidget(self._tools_panel)
        self.tools_dock.setMinimumWidth(280)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.tools_dock)
        
        # Disable tools panel until image is loaded
        self._tools_panel.set_enabled(False)

    def _create_action(self, text: str, callback, shortcut: str = None) -> QAction:
        """Create a QAction with text, callback, and optional shortcut.
        
        Args:
            text: Action text
            callback: Function to call when action is triggered
            shortcut: Optional keyboard shortcut
            
        Returns:
            QAction instance
        """
        action = QAction(text, self)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        return action

    def _setup_menu_bar(self):
        """Set up the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self._create_action("&Open Image...", self._open_image, "Ctrl+O"))
        file_menu.addAction(self._create_action("&Import Images...", self._import_images, "Ctrl+Shift+O"))
        file_menu.addSeparator()
        file_menu.addAction(self._create_action("&Export...", self._export_image, "Ctrl+E"))
        file_menu.addSeparator()
        file_menu.addAction(self._create_action("E&xit", self.close, "Ctrl+Q"))
        
        # Edit menu
        edit_menu = menubar.addMenu("&Edit")
        self._undo_action = self._create_action("&Undo", self._undo, "Ctrl+Z")
        self._redo_action = self._create_action("&Redo", self._redo, "Ctrl+Shift+Z")
        edit_menu.addAction(self._undo_action)
        edit_menu.addAction(self._redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self._create_action("&Reset Adjustments", self._reset_adjustments, "Ctrl+R"))
        
        # View menu
        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self._create_action("&Fit to Window", self._fit_to_window, "0"))
        view_menu.addAction(self._create_action("&100%", self._view_100_percent, "1"))
        view_menu.addAction(self._create_action("Zoom &In", self._zoom_in, "Ctrl+="))
        view_menu.addAction(self._create_action("Zoom &Out", self._zoom_out, "Ctrl+-"))
        view_menu.addSeparator()
        view_menu.addAction(self._create_action("Toggle &Library Panel", self._toggle_library_panel, "F5"))
        view_menu.addAction(self._create_action("Toggle &Tools Panel", self._toggle_tools_panel, "F6"))

    def _setup_status_bar(self):
        """Set up the status bar."""
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        
        # Zoom label
        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet("padding: 0 10px;")
        self._status_bar.addPermanentWidget(self._zoom_label)
        
        self._status_bar.showMessage("Ready")

    def _setup_shortcuts(self):
        """Set up keyboard shortcuts."""
        # Additional shortcuts can be added here
        pass

    def _connect_signals(self):
        """Connect signals to slots."""
        self._image_view.image_loaded.connect(self._on_image_loaded)
        self._image_view.zoom_changed.connect(self._on_zoom_changed)
        self._tools_panel.adjustments_changed.connect(self._on_adjustments_changed)
        self._tools_panel.slider_released.connect(self._on_slider_released)
        self._library_view.image_selected.connect(self._on_library_image_selected)

    def _on_image_loaded(self):
        """Handle image loaded event."""
        file_path = self._image_controller.image_model.file_path
        if file_path:
            self.setWindowTitle(f"PhotoEdit - {file_path}")
            self._status_bar.showMessage(f"Loaded: {file_path}", 3000)
            # Enable tools panel
            self._tools_panel.set_enabled(True)
            self._tools_panel.reset_all()

    def _on_zoom_changed(self, zoom_factor: float):
        """Handle zoom changed event."""
        self._zoom_label.setText(f"{int(zoom_factor * 100)}%")

    def _on_adjustments_changed(self, adjustments: dict):
        """Handle adjustments changed from tools panel."""
        self._image_controller.on_adjustments_changed(adjustments)

    def _on_slider_released(self):
        """Handle slider released - trigger final processing."""
        self._image_controller.on_slider_released()

    def _on_library_image_selected(self, file_path: str):
        """Handle image selection from library."""
        self._image_controller.load_image(file_path, self)

    # Menu action handlers
    def _open_image(self):
        """Handle open image action."""
        if self._image_controller.open_image(self):
            # Add to library
            file_path = self._image_controller.image_model.file_path
            if file_path:
                self._library_view.add_image(file_path)

    def _import_images(self):
        """Handle import images action."""
        start_dir = self._settings_service.get_last_open_dir()
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Images",
            start_dir,
            "Image Files (*.jpg *.jpeg *.png *.tiff *.tif *.bmp *.webp);;All Files (*)"
        )
        
        if file_paths:
            self._settings_service.set_last_open_dir(file_paths[0])
            self._library_view.add_images(file_paths)
            self._status_bar.showMessage(f"Imported {len(file_paths)} images", 2000)

    def _export_image(self):
        """Handle export image action."""
        if not self._image_controller.has_image():
            self._status_bar.showMessage("No image to export", 2000)
            return
        
        # Get current image
        image = self._image_controller.get_current_image()
        if image is None:
            self._status_bar.showMessage("No image to export", 2000)
            return
        
        # Get default path from current file
        default_path = self._image_controller.image_model.file_path or ""
        if default_path:
            from pathlib import Path
            p = Path(default_path)
            default_path = str(p.parent / f"{p.stem}_edited{p.suffix}")
        
        # If we have no source path, seed default location with the
        # last-used export directory so the dialog is not empty.
        if not default_path:
            from pathlib import Path

            default_path = str(Path(self._settings_service.get_last_export_dir()))

        # Show export dialog
        dialog = ExportDialog(
            image,
            default_path,
            settings_service=self._settings_service,
            parent=self,
        )
        if dialog.exec():
            export_path = dialog.get_export_path()
            if export_path:
                self._settings_service.set_last_export_dir(export_path)
            self._status_bar.showMessage(f"Exported to: {export_path}", 3000)

    def _undo(self):
        """Handle undo action."""
        if self._image_controller.can_undo():
            self._image_controller.undo()
            self._status_bar.showMessage("Undo", 1000)
        else:
            self._status_bar.showMessage("Nothing to undo", 1000)

    def _redo(self):
        """Handle redo action."""
        if self._image_controller.can_redo():
            self._image_controller.redo()
            self._status_bar.showMessage("Redo", 1000)
        else:
            self._status_bar.showMessage("Nothing to redo", 1000)

    def _reset_adjustments(self):
        """Handle reset adjustments action."""
        if self._image_controller.has_image():
            self._image_controller.reset_to_original()
            self._status_bar.showMessage("Reset to original", 2000)

    def _fit_to_window(self):
        """Handle fit to window action."""
        self._image_controller.fit_to_window()

    def _view_100_percent(self):
        """Handle 100% view action."""
        self._image_controller.view_100_percent()

    def _zoom_in(self):
        """Handle zoom in action."""
        self._image_controller.zoom_in()

    def _zoom_out(self):
        """Handle zoom out action."""
        self._image_controller.zoom_out()

    def _toggle_library_panel(self):
        """Toggle library panel visibility."""
        self.library_dock.setVisible(not self.library_dock.isVisible())

    def _toggle_tools_panel(self):
        """Toggle tools panel visibility."""
        self.tools_dock.setVisible(not self.tools_dock.isVisible())

    def _restore_window_geometry(self) -> None:
        """Restore window size and position from settings (if any)."""
        try:
            blob = self._settings_service.get_window_geometry()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to read window geometry from settings")
            return
        if not blob:
            return
        try:
            from PyQt6.QtCore import QByteArray

            self.restoreGeometry(QByteArray(blob))
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to restore window geometry; using defaults")

    def _save_window_geometry(self) -> None:
        """Persist current window size and position to settings."""
        try:
            blob = bytes(self.saveGeometry())
            self._settings_service.set_window_geometry(blob)
            self._settings_service.sync()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to save window geometry")

    def closeEvent(self, event):
        """Handle window close event."""
        self._save_window_geometry()
        # Clean up the image controller (stops background threads)
        self._image_controller.cleanup()
        super().closeEvent(event)
