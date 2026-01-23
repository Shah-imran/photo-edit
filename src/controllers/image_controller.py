"""Controller for image operations."""

from typing import Optional
from PyQt6.QtWidgets import QFileDialog, QWidget, QMessageBox
from src.models.image_model import ImageModel
from src.services.image_service import ImageService
from src.services.history_service import HistoryService
from src.views.image_view import ImageView


class ImageController:
    """Controller for managing image operations.
    
    This controller connects the image model, services, and view,
    handling user interactions and coordinating operations.
    """

    def __init__(
        self,
        image_view: ImageView,
        image_model: Optional[ImageModel] = None,
        image_service: Optional[ImageService] = None,
        history_service: Optional[HistoryService] = None
    ):
        """Initialize the ImageController.
        
        Args:
            image_view: The ImageView widget to control
            image_model: Optional ImageModel (creates new if not provided)
            image_service: Optional ImageService (creates new if not provided)
            history_service: Optional HistoryService (creates new if not provided)
        """
        self._image_view = image_view
        self._image_model = image_model or ImageModel()
        self._image_service = image_service or ImageService()
        self._history_service = history_service or HistoryService()
        
        # Connect signals
        self._connect_signals()

    def _connect_signals(self):
        """Connect view signals to controller methods."""
        pass  # Signals will be connected as needed

    @property
    def image_model(self) -> ImageModel:
        """Get the image model."""
        return self._image_model

    @property
    def history_service(self) -> HistoryService:
        """Get the history service."""
        return self._history_service

    def open_image(self, parent: Optional[QWidget] = None) -> bool:
        """Open an image file dialog and load the selected image.
        
        Args:
            parent: Parent widget for the dialog
            
        Returns:
            True if an image was loaded successfully
        """
        file_path, _ = QFileDialog.getOpenFileName(
            parent,
            "Open Image",
            "",
            "Image Files (*.jpg *.jpeg *.png *.tiff *.tif *.bmp *.webp);;All Files (*)"
        )
        
        if file_path:
            return self.load_image(file_path, parent)
        return False

    def load_image(self, file_path: str, parent: Optional[QWidget] = None) -> bool:
        """Load an image from a file path.
        
        Args:
            file_path: Path to the image file
            parent: Parent widget for error dialogs
            
        Returns:
            True if image was loaded successfully
        """
        try:
            image = self._image_service.load_image(file_path)
            self._image_model.file_path = file_path
            self._image_model.set_original_image(image)
            self._image_view.set_image(image)
            self._history_service.clear_history()
            return True
        except FileNotFoundError:
            QMessageBox.warning(
                parent,
                "File Not Found",
                f"Could not find file: {file_path}"
            )
            return False
        except ValueError as e:
            QMessageBox.warning(
                parent,
                "Invalid Image",
                f"Could not load image: {str(e)}"
            )
            return False

    def has_image(self) -> bool:
        """Check if an image is currently loaded.
        
        Returns:
            True if an image is loaded
        """
        return self._image_model.has_image()

    def get_current_image(self):
        """Get the current image.
        
        Returns:
            Current PIL Image or None
        """
        return self._image_model.get_current_image()

    def refresh_view(self) -> None:
        """Refresh the image view with the current image state."""
        current_image = self._image_model.get_current_image()
        if current_image:
            self._image_view.set_image(current_image)

    def reset_to_original(self) -> None:
        """Reset the image to its original state."""
        self._image_model.reset_to_original()
        self._history_service.clear_history()
        self.refresh_view()

    def undo(self) -> bool:
        """Undo the last operation.
        
        Returns:
            True if undo was successful
        """
        result = self._history_service.undo()
        if result:
            self.refresh_view()
        return result

    def redo(self) -> bool:
        """Redo the last undone operation.
        
        Returns:
            True if redo was successful
        """
        result = self._history_service.redo()
        if result:
            self.refresh_view()
        return result

    def can_undo(self) -> bool:
        """Check if undo is available.
        
        Returns:
            True if undo is available
        """
        return self._history_service.can_undo()

    def can_redo(self) -> bool:
        """Check if redo is available.
        
        Returns:
            True if redo is available
        """
        return self._history_service.can_redo()

    def zoom_in(self) -> None:
        """Zoom in on the image."""
        self._image_view.zoom_in()

    def zoom_out(self) -> None:
        """Zoom out on the image."""
        self._image_view.zoom_out()

    def fit_to_window(self) -> None:
        """Fit the image to the window."""
        self._image_view.fit_to_window()

    def view_100_percent(self) -> None:
        """View the image at 100% zoom."""
        self._image_view.view_100_percent()

    def get_zoom_factor(self) -> float:
        """Get the current zoom factor.
        
        Returns:
            Current zoom factor
        """
        return self._image_view.get_zoom_factor()
