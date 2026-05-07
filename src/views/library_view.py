"""Library view for browsing and selecting images."""

import logging
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
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QObject, QThread
from PyQt6.QtGui import QIcon, QPixmap

from src.services.file_service import FileService
from src.services.image_service import ImageService
from src.services.settings_service import SettingsService
from src.utils.color_pipeline import linear_to_qimage
from src.utils.image_extensions import open_image_file_dialog_filter


logger = logging.getLogger(__name__)


class _ThumbnailBatchWorker(QObject):
    """Generate thumbnails in a background thread."""

    thumbnail_ready = pyqtSignal(str, object)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal()
    failed = pyqtSignal(str, str)

    def __init__(self, file_paths: List[str], size: int):
        super().__init__()
        self._file_paths = list(file_paths)
        self._size = int(size)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        service = ImageService()
        total = len(self._file_paths)
        for idx, file_path in enumerate(self._file_paths, start=1):
            if self._cancelled:
                break
            try:
                thumbnail = service.load_preview_thumbnail(
                    file_path, (self._size, self._size)
                )
                self.thumbnail_ready.emit(file_path, thumbnail)
            except Exception as e:
                self.failed.emit(file_path, str(e))
            self.progress.emit(idx, total)
        self.finished.emit()


class LibraryView(QWidget):
    """Widget for browsing and selecting images from a library.
    
    Signals:
        image_selected: Emitted when an image is selected (file_path)
        images_imported: Emitted when images are imported (list of paths)
    """
    
    image_selected = pyqtSignal(str)
    images_imported = pyqtSignal(list)
    thumbnail_batch_started = pyqtSignal(int)
    thumbnail_batch_progress = pyqtSignal(int, int)
    thumbnail_batch_finished = pyqtSignal()

    THUMBNAIL_SIZE = 80
    # Icon area + one line of filename under the thumbnail.
    THUMB_CELL_WIDTH = 112
    THUMB_CELL_HEIGHT = 118

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
        self._thumbnail_thread: Optional[QThread] = None
        self._thumbnail_worker: Optional[_ThumbnailBatchWorker] = None
        
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
        self._list_widget.setWordWrap(True)
        self._list_widget.setGridSize(
            QSize(self.THUMB_CELL_WIDTH, self.THUMB_CELL_HEIGHT)
        )
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
            open_image_file_dialog_filter()
        )
        
        if file_paths:
            if self._settings_service is not None:
                self._settings_service.set_last_open_dir(file_paths[0])
            self.add_images_async(file_paths)
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

    def add_images_async(self, file_paths: List[str]) -> None:
        """Add images using background thumbnail generation.

        This keeps the UI responsive for large imports.
        Emits ``thumbnail_batch_*`` signals for status-bar progress UI.
        """
        new_paths = [p for p in file_paths if p not in self._image_paths]
        if not new_paths:
            return

        if self._thumbnail_thread is not None:
            # Avoid overlapping batch loaders.
            return

        self.thumbnail_batch_started.emit(len(new_paths))

        self._thumbnail_thread = QThread(self)
        self._thumbnail_worker = _ThumbnailBatchWorker(new_paths, self.THUMBNAIL_SIZE)
        self._thumbnail_worker.moveToThread(self._thumbnail_thread)

        self._thumbnail_thread.started.connect(self._thumbnail_worker.run)
        self._thumbnail_worker.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._thumbnail_worker.progress.connect(self._on_thumbnail_progress)
        self._thumbnail_worker.failed.connect(self._on_thumbnail_failed)
        self._thumbnail_worker.finished.connect(self._on_thumbnail_batch_finished)
        self._thumbnail_worker.finished.connect(self._thumbnail_thread.quit)
        self._thumbnail_thread.finished.connect(self._thumbnail_worker.deleteLater)
        self._thumbnail_thread.finished.connect(self._thumbnail_thread.deleteLater)
        self._thumbnail_thread.finished.connect(self._clear_thumbnail_loader)

        self._thumbnail_thread.start()

    def _on_thumbnail_ready(self, file_path: str, thumbnail) -> None:
        if file_path in self._image_paths:
            return
        pixmap = QPixmap.fromImage(linear_to_qimage(thumbnail))
        name = Path(file_path).name
        item = QListWidgetItem()
        item.setIcon(QIcon(pixmap))
        item.setText(name)
        item.setTextAlignment(
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        )
        item.setData(Qt.ItemDataRole.UserRole, file_path)
        item.setToolTip(name)
        item.setSizeHint(
            QSize(self.THUMB_CELL_WIDTH, self.THUMB_CELL_HEIGHT)
        )
        self._list_widget.addItem(item)
        self._image_paths.append(file_path)
        self._update_info_label()

    def _on_thumbnail_progress(self, current: int, total: int) -> None:
        self.thumbnail_batch_progress.emit(current, total)

    def _on_thumbnail_failed(self, file_path: str, error: str) -> None:
        logger.warning("Failed to load thumbnail for %s: %s", file_path, error)

    def _on_thumbnail_batch_finished(self) -> None:
        self._update_info_label()
        self.thumbnail_batch_finished.emit()

    def _clear_thumbnail_loader(self) -> None:
        self._thumbnail_worker = None
        self._thumbnail_thread = None

    def cancel_thumbnail_batch(self) -> None:
        """Ask the background thumbnail worker to stop after the current file."""
        if self._thumbnail_worker is not None:
            self._thumbnail_worker.cancel()

    def _add_image_item(self, file_path: str):
        """Add an image item to the list widget.
        
        Args:
            file_path: Path to the image file
        """
        try:
            thumbnail = self._image_service.load_preview_thumbnail(
                file_path,
                (self.THUMBNAIL_SIZE, self.THUMBNAIL_SIZE),
            )
            pixmap = QPixmap.fromImage(linear_to_qimage(thumbnail))

            name = Path(file_path).name
            item = QListWidgetItem()
            item.setIcon(QIcon(pixmap))
            item.setText(name)
            item.setTextAlignment(
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            )
            item.setData(Qt.ItemDataRole.UserRole, file_path)
            item.setToolTip(name)
            item.setSizeHint(
                QSize(self.THUMB_CELL_WIDTH, self.THUMB_CELL_HEIGHT)
            )

            self._list_widget.addItem(item)
        except Exception as e:
            logger.warning("Failed to load thumbnail for %s: %s", file_path, e)

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
            self.add_images_async(image_files)
            self.images_imported.emit(image_files)
        
        return image_files
