"""Controller for image operations."""

import logging
from typing import Optional, Dict
from PyQt6.QtWidgets import QFileDialog, QWidget, QMessageBox
from PyQt6.QtCore import QObject

from src.models.image_model import ImageModel
from src.services.image_service import ImageService
from src.services.history_service import HistoryService
from src.services.settings_service import SettingsService
from src.views.image_view import ImageView
from src.processors.exposure_processor import ExposureProcessor
from src.processors.color_processor import ColorProcessor
from src.commands.adjustment_commands import CombinedAdjustmentCommand
from src.processing.processing_worker import ProcessingWorker
from src.utils.debouncer import Debouncer


logger = logging.getLogger(__name__)


class ImageController(QObject):
    """Controller for managing image operations.
    
    This controller connects the image model, services, and view,
    handling user interactions and coordinating operations.
    
    The controller uses background threading for image processing
    to keep the UI responsive during adjustments.
    """

    def __init__(
        self,
        image_view: ImageView,
        image_model: Optional[ImageModel] = None,
        image_service: Optional[ImageService] = None,
        history_service: Optional[HistoryService] = None,
        settings_service: Optional[SettingsService] = None,
        use_threading: bool = True
    ):
        """Initialize the ImageController.
        
        Args:
            image_view: The ImageView widget to control
            image_model: Optional ImageModel (creates new if not provided)
            image_service: Optional ImageService (creates new if not provided)
            history_service: Optional HistoryService (creates new if not provided)
            settings_service: Optional SettingsService for persisting last-used
                directories. When ``None`` the dialog uses an empty default,
                preserving previous behavior.
            use_threading: Whether to use background threading for processing
        """
        super().__init__()
        
        self._image_view = image_view
        self._image_model = image_model or ImageModel()
        self._image_service = image_service or ImageService()
        self._history_service = history_service or HistoryService()
        self._settings_service = settings_service
        self._use_threading = use_threading
        
        # Processors (for synchronous fallback)
        self._exposure_processor = ExposureProcessor()
        self._color_processor = ColorProcessor()
        
        # Current adjustment values
        self._exposure_params: Dict[str, float] = {}
        self._color_params: Dict[str, float] = {}
        
        # Background processing
        self._processing_worker: Optional[ProcessingWorker] = None
        self._debouncer: Optional[Debouncer] = None
        self._latest_request_id: int = -1
        
        if use_threading:
            self._setup_async_processing()
        
        # Connect signals
        self._connect_signals()

    def _setup_async_processing(self) -> None:
        """Set up asynchronous processing components."""
        # Create and start processing worker
        self._processing_worker = ProcessingWorker()
        self._processing_worker.preview_ready.connect(self._on_preview_ready)
        self._processing_worker.processing_complete.connect(self._on_processing_complete)
        self._processing_worker.error_occurred.connect(self._on_processing_error)
        self._processing_worker.start()
        
        # Create debouncer for slider input (50ms delay)
        self._debouncer = Debouncer(delay_ms=50)
        self._debouncer.triggered.connect(self._on_debounced_adjustment)

    def _connect_signals(self):
        """Connect view signals to controller methods."""
        pass  # Signals will be connected as needed

    def cleanup(self) -> None:
        """Clean up resources (call before destroying)."""
        if self._processing_worker is not None:
            self._processing_worker.stop()

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
        start_dir = (
            self._settings_service.get_last_open_dir()
            if self._settings_service is not None
            else ""
        )
        file_path, _ = QFileDialog.getOpenFileName(
            parent,
            "Open Image",
            start_dir,
            "Image Files (*.jpg *.jpeg *.png *.tiff *.tif *.bmp *.webp);;All Files (*)"
        )
        
        if file_path:
            if self._settings_service is not None:
                self._settings_service.set_last_open_dir(file_path)
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
            
            # Reset adjustment params
            self._exposure_params = {}
            self._color_params = {}
            
            # Set image in processing worker for proxy generation
            if self._processing_worker is not None:
                self._processing_worker.set_image(image)
            
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
        if current_image is not None:
            # Don't emit image_loaded signal on refresh (only on initial load)
            self._image_view.set_image(current_image, emit_loaded=False)

    def reset_to_original(self) -> None:
        """Reset the image to its original state."""
        self._image_model.reset_to_original()
        self._history_service.clear_history()
        self._exposure_params = {}
        self._color_params = {}
        
        # Cancel any pending processing
        if self._processing_worker is not None:
            self._processing_worker.cancel_pending()
        
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

    def apply_adjustments(
        self,
        exposure_params: Dict[str, float] = None,
        color_params: Dict[str, float] = None,
        add_to_history: bool = False
    ) -> None:
        """Apply adjustments to the image (synchronous).
        
        Args:
            exposure_params: Exposure adjustment parameters
            color_params: Color adjustment parameters
            add_to_history: If True, add command to history for undo
        """
        if not self.has_image():
            return
        
        # Store current params
        if exposure_params:
            self._exposure_params = exposure_params
        if color_params:
            self._color_params = color_params
        
        if add_to_history:
            # Create and execute command for undo/redo
            command = CombinedAdjustmentCommand(
                self._image_model,
                exposure_params=self._exposure_params,
                color_params=self._color_params
            )
            self._history_service.execute_command(command)
        else:
            # Apply directly without history (for live preview)
            original = self._image_model.get_original_image()
            if original is None:
                return
            
            result = original.copy()
            
            # Apply exposure adjustments
            if self._exposure_params:
                result = self._exposure_processor.process(result, **self._exposure_params)
            
            # Apply color adjustments
            if self._color_params:
                result = self._color_processor.process(result, **self._color_params)
            
            self._image_model.current_image = result
        
        self.refresh_view()

    def on_adjustments_changed(self, adjustments: Dict[str, float]) -> None:
        """Handle adjustment changes from the tools panel.
        
        This method is called frequently during slider movement.
        Uses debouncing and background processing for smooth UI.
        
        Args:
            adjustments: Dictionary of all adjustment values
        """
        if not self.has_image():
            return
        
        exposure_params = {
            'exposure': adjustments.get('exposure', 0.0),
            'contrast': adjustments.get('contrast', 0.0),
            'brightness': adjustments.get('brightness', 0.0)
        }
        color_params = {
            'saturation': adjustments.get('saturation', 0.0),
            'vibrance': adjustments.get('vibrance', 0.0)
        }
        
        # Store params
        self._exposure_params = exposure_params
        self._color_params = color_params
        
        if self._use_threading and self._debouncer is not None:
            # Use debounced async processing
            self._debouncer.call({
                'exposure': exposure_params,
                'color': color_params
            })
        else:
            # Fallback to synchronous processing
            self.apply_adjustments(exposure_params, color_params, add_to_history=False)

    def _on_debounced_adjustment(self, params: dict) -> None:
        """Handle debounced adjustment (called after slider pause).
        
        Args:
            params: Dictionary with 'exposure' and 'color' params
        """
        if not self.has_image() or self._processing_worker is None:
            return
        
        exposure_params = params.get('exposure', {})
        color_params = params.get('color', {})
        
        # Submit preview request to worker
        self._latest_request_id = self._processing_worker.submit_preview_request(
            exposure_params=exposure_params,
            color_params=color_params
        )

    def _on_preview_ready(self, request_id: int, image) -> None:
        """Handle preview ``LinearImage`` ready from worker."""
        if self._processing_worker is not None and \
           self._processing_worker.is_latest_request(request_id):
            proxy_manager = self._processing_worker.proxy_manager
            if proxy_manager.needs_proxy():
                display_image = proxy_manager.upscale_to_original_size(image)
            else:
                display_image = image

            self._image_model.current_image = display_image
            self.refresh_view()

    def _on_processing_complete(self, request_id: int, image) -> None:
        """Handle full-resolution processing complete from worker."""
        self._image_model.current_image = image
        self.refresh_view()

    def _on_processing_error(self, request_id: int, error: str) -> None:
        """Handle processing error from worker.
        
        Args:
            request_id: The request ID
            error: Error message
        """
        # Log error but don't show dialog for transient errors.
        logger.error("Processing error (request %s): %s", request_id, error)

    def on_slider_released(self) -> None:
        """Handle slider release - trigger full-resolution processing.
        
        Call this when the user releases a slider to get the final
        high-quality result.
        """
        if not self.has_image():
            return
        
        if self._use_threading and self._processing_worker is not None:
            # Flush any pending debounced calls
            if self._debouncer is not None:
                self._debouncer.flush()
            
            # Request full-resolution processing
            self._processing_worker.submit_final_request(
                exposure_params=self._exposure_params,
                color_params=self._color_params
            )
        
        # Commit to history
        self.commit_adjustments()

    def commit_adjustments(self) -> None:
        """Commit current adjustments to history.
        
        Call this when user finishes adjusting (e.g., releases slider).
        """
        if not self.has_image():
            return
        
        # Only commit if there are actual changes
        has_changes = (
            any(v != 0 for v in self._exposure_params.values()) or
            any(v != 0 for v in self._color_params.values())
        )
        
        if has_changes:
            command = CombinedAdjustmentCommand(
                self._image_model,
                exposure_params=self._exposure_params.copy(),
                color_params=self._color_params.copy()
            )
            self._history_service.execute_command(command)
