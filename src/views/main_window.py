"""Main window for PhotoEdit application."""

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QDockWidget,
    QLabel
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QAction


class MainWindow(QMainWindow):
    """Main application window with Lightroom-like layout.
    
    The window features a three-panel layout:
    - Left: Library panel (for image browsing)
    - Center: Image view (for editing)
    - Right: Tools panel (for adjustments)
    """

    def __init__(self):
        """Initialize the main window."""
        super().__init__()
        self.setWindowTitle("PhotoEdit")
        self.setMinimumSize(1200, 800)
        
        # Set up UI
        self._setup_ui()
        self._setup_menu_bar()
        self._setup_status_bar()
        self._setup_shortcuts()

    def _setup_ui(self):
        """Set up the main UI components."""
        # Central widget with splitter
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QHBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Create main splitter
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(main_splitter)
        
        # Left panel - Library (placeholder)
        self.library_panel = QDockWidget("Library", self)
        self.library_panel.setWidget(QLabel("Library Panel\n(Image browsing will go here)"))
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.library_panel)
        
        # Center - Image view (placeholder)
        self.image_view = QLabel("Image View\n(Image display will go here)")
        self.image_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_view.setStyleSheet("background-color: #1a1a1a; color: #e0e0e0;")
        main_splitter.addWidget(self.image_view)
        
        # Right panel - Tools (placeholder)
        self.tools_panel = QDockWidget("Adjustments", self)
        self.tools_panel.setWidget(QLabel("Adjustments Panel\n(Editing tools will go here)"))
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.tools_panel)
        
        # Set splitter proportions (Library: 20%, Image: 60%, Tools: 20%)
        main_splitter.setSizes([200, 600, 200])

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
        edit_menu.addAction(self._create_action("&Undo", self._undo, "Ctrl+Z"))
        edit_menu.addAction(self._create_action("&Redo", self._redo, "Ctrl+Shift+Z"))
        edit_menu.addSeparator()
        edit_menu.addAction(self._create_action("&Reset Adjustments", self._reset_adjustments, "Ctrl+R"))
        
        # View menu
        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self._create_action("&Fit to Window", self._fit_to_window, "0"))
        view_menu.addAction(self._create_action("&100%", self._view_100_percent, "1"))
        view_menu.addSeparator()
        view_menu.addAction(self._create_action("Toggle &Library Panel", self._toggle_library_panel, "F5"))
        view_menu.addAction(self._create_action("Toggle &Tools Panel", self._toggle_tools_panel, "F6"))

    def _setup_status_bar(self):
        """Set up the status bar."""
        self.statusBar().showMessage("Ready")

    def _setup_shortcuts(self):
        """Set up keyboard shortcuts."""
        # Additional shortcuts can be added here
        pass

    # Menu action handlers (placeholders)
    def _open_image(self):
        """Handle open image action."""
        self.statusBar().showMessage("Open image (not yet implemented)", 2000)

    def _import_images(self):
        """Handle import images action."""
        self.statusBar().showMessage("Import images (not yet implemented)", 2000)

    def _export_image(self):
        """Handle export image action."""
        self.statusBar().showMessage("Export image (not yet implemented)", 2000)

    def _undo(self):
        """Handle undo action."""
        self.statusBar().showMessage("Undo (not yet implemented)", 2000)

    def _redo(self):
        """Handle redo action."""
        self.statusBar().showMessage("Redo (not yet implemented)", 2000)

    def _reset_adjustments(self):
        """Handle reset adjustments action."""
        self.statusBar().showMessage("Reset adjustments (not yet implemented)", 2000)

    def _fit_to_window(self):
        """Handle fit to window action."""
        self.statusBar().showMessage("Fit to window (not yet implemented)", 2000)

    def _view_100_percent(self):
        """Handle 100% view action."""
        self.statusBar().showMessage("100% view (not yet implemented)", 2000)

    def _toggle_library_panel(self):
        """Toggle library panel visibility."""
        self.library_panel.setVisible(not self.library_panel.isVisible())

    def _toggle_tools_panel(self):
        """Toggle tools panel visibility."""
        self.tools_panel.setVisible(not self.tools_panel.isVisible())
