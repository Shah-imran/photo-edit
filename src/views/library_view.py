"""Library view for browsing and selecting images."""

from typing import Optional, List
from pathlib import Path
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QPushButton,
    QFileDialog,
    QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QIcon, QPixmap

from src.services.image_service import ImageService
from src.services.file_service import FileService
from src.services.settings_service import SettingsService


class LibraryView(QWidget):
    """Widget for browsing and selecting images from a library.
    
    Signals:
        image_selected: Emitted when an image is selected (file_path)
        images_imported: Emitted when images are imported (list of paths)
    """
    
    image_selected = pyqtSignal(str)
    images_imported = pyqtSignal(list)

    THUMBNAIL_SIZE = 80

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        settings_service: Optional[SettingsService] = None,
    ):
        """Initialize the library view.
        
        Args:
            parent: Optional parent widget
            settings_service: Optional SettingsService for persisting the
                last-used import directory.
        """
        super().__init__(parent)
        
        self._image_service = ImageService()
        self._file_service = FileService()
        self._settings_service = settings_service
        self._image_paths: List[str] = []
        
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Set up the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Header with import button
        header_layout = QHBoxLayout()
        
        title = QLabel("Library")
        title.setStyleSheet("color: #a0a0a0; font-weight: bold; font-size: 12px;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        import_button = QPushButton("+ Import")
        import_button.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 4px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #0086f0;
            }
        """)
        import_button.clicked.connect(self._import_images)
        header_layout.addWidget(import_button)
        
        layout.addLayout(header_layout)
        
        # Image list
        self._list_widget = QListWidget()
        self._list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self._list_widget.setIconSize(QSize(self.THUMBNAIL_SIZE, self.THUMBNAIL_SIZE))
        self._list_widget.setSpacing(8)
        self._list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list_widget.setWrapping(True)
        self._list_widget.setStyleSheet("""
            QListWidget {
                background-color: #1a1a1a;
                border: none;
            }
            QListWidget::item {
                background-color: #2d2d2d;
                border: 2px solid transparent;
                border-radius: 4px;
                padding: 4px;
            }
            QListWidget::item:selected {
                border-color: #0078d4;
                background-color: #2d2d2d;
            }
            QListWidget::item:hover {
                background-color: #3a3a3a;
            }
        """)
        layout.addWidget(self._list_widget)
        
        # Info label
        self._info_label = QLabel("No images")
        self._info_label.setStyleSheet("color: #606060; font-size: 10px;")
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._info_label)

    def _connect_signals(self):
        """Connect widget signals."""
        self._list_widget.itemClicked.connect(self._on_item_clicked)
        self._list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)

    def _import_images(self):
        """Open file dialog to import images."""
        start_dir = (
            self._settings_service.get_last_open_dir()
            if self._settings_service is not None
            else ""
        )
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Images",
            start_dir,
            "Image Files (*.jpg *.jpeg *.png *.tiff *.tif *.bmp *.webp);;All Files (*)"
        )
        
        if file_paths:
            if self._settings_service is not None:
                self._settings_service.set_last_open_dir(file_paths[0])
            self.add_images(file_paths)
            self.images_imported.emit(file_paths)

    def add_images(self, file_paths: List[str]) -> None:
        """Add images to the library.
        
        Args:
            file_paths: List of image file paths
        """
        for path in file_paths:
            if path not in self._image_paths:
                self._add_image_item(path)
                self._image_paths.append(path)
        
        self._update_info_label()

    def add_image(self, file_path: str) -> None:
        """Add a single image to the library.
        
        Args:
            file_path: Path to the image file
        """
        self.add_images([file_path])

    def _add_image_item(self, file_path: str):
        """Add an image item to the list widget.
        
        Args:
            file_path: Path to the image file
        """
        try:
            # Load and create thumbnail
            image = self._image_service.load_image(file_path)
            thumbnail = self._image_service.create_thumbnail(
                image,
                (self.THUMBNAIL_SIZE, self.THUMBNAIL_SIZE)
            )
            
            # Convert to QPixmap
            from src.views.image_view import ImageView
            temp_view = ImageView()
            pixmap = temp_view._pil_to_pixmap(thumbnail)
            
            # Create list item
            item = QListWidgetItem()
            item.setIcon(QIcon(pixmap))
            item.setData(Qt.ItemDataRole.UserRole, file_path)
            item.setToolTip(Path(file_path).name)
            item.setSizeHint(QSize(
                self.THUMBNAIL_SIZE + 16,
                self.THUMBNAIL_SIZE + 16
            ))
            
            self._list_widget.addItem(item)
        except Exception as e:
            print(f"Failed to load thumbnail for {file_path}: {e}")

    def _on_item_clicked(self, item: QListWidgetItem):
        """Handle item click."""
        file_path = item.data(Qt.ItemDataRole.UserRole)
        if file_path:
            self.image_selected.emit(file_path)

    def _on_item_double_clicked(self, item: QListWidgetItem):
        """Handle item double-click."""
        # Same as single click for now
        self._on_item_clicked(item)

    def _update_info_label(self):
        """Update the info label with image count."""
        count = len(self._image_paths)
        if count == 0:
            self._info_label.setText("No images")
        elif count == 1:
            self._info_label.setText("1 image")
        else:
            self._info_label.setText(f"{count} images")

    def get_image_count(self) -> int:
        """Get the number of images in the library.
        
        Returns:
            Number of images
        """
        return len(self._image_paths)

    def get_selected_path(self) -> Optional[str]:
        """Get the currently selected image path.
        
        Returns:
            Path to selected image or None
        """
        current = self._list_widget.currentItem()
        if current:
            return current.data(Qt.ItemDataRole.UserRole)
        return None

    def clear(self):
        """Clear all images from the library."""
        self._list_widget.clear()
        self._image_paths.clear()
        self._update_info_label()

    def import_folder(self, folder_path: str, recursive: bool = False) -> List[str]:
        """Import all images from a folder.
        
        Args:
            folder_path: Path to the folder
            recursive: If True, search subdirectories
            
        Returns:
            List of imported file paths
        """
        image_files = self._file_service.get_image_files_from_directory(
            folder_path,
            recursive=recursive
        )
        
        if image_files:
            self.add_images(image_files)
            self.images_imported.emit(image_files)
        
        return image_files
