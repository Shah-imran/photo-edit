"""Controller for image operations."""

import logging
from time import perf_counter
from typing import Optional, Dict
from PyQt6.QtWidgets import QFileDialog, QWidget, QMessageBox
from PyQt6.QtCore import QObject, QThread, Qt, QTimer, pyqtSignal

from src.models.image_model import ImageModel
from src.services.image_service import ImageService
from src.services.history_service import HistoryService
from src.services.settings_service import SettingsService
from src.views.image_view import ImageView
from src.processors.exposure_processor import ExposureProcessor
from src.processors.color_processor import ColorProcessor
from src.commands.adjustment_commands import (
    CombinedAdjustmentCommand,
    ImageStateChangeCommand,
)
from src.processing.display_frame import DisplayFrame
from src.processing.processing_worker import ProcessingWorker
from src.utils.debouncer import ThrottledDebouncer
from src.utils.image_extensions import open_image_file_dialog_filter
logger = logging.getLogger(__name__)


def _elapsed_ms(start: float) -> float:
    return (perf_counter() - start) * 1000.0


class _ImageLoadWorker(QObject):
    """Worker that loads an image in a background thread."""

    preview_loaded = pyqtSignal(int, str, object)
    loaded = pyqtSignal(int, str, object)
    failed = pyqtSignal(int, str, str)

    def __init__(self, request_id: int, file_path: str, image_service: ImageService):
        super().__init__()
        self._request_id = request_id
        self._file_path = file_path
        self._image_service = image_service

    def run(self) -> None:
        """Decode the image and emit completion signal."""
        try:
            try:
                preview = self._image_service.load_preview_thumbnail(
                    self._file_path,
                    (1600, 1600),
                    maintain_aspect=True,
                )
                self.preview_loaded.emit(
                    self._request_id, self._file_path, preview
                )
            except Exception:
                logger.exception("Preview load failed for %s", self._file_path)

            image = self._image_service.load_image(self._file_path)
            self.loaded.emit(self._request_id, self._file_path, image)
        except Exception as e:
            self.failed.emit(self._request_id, self._file_path, str(e))


class ImageController(QObject):
    """Controller for managing image operations.
    
    This controller connects the image model, services, and view,
    handling user interactions and coordinating operations.
    
    The controller uses background threading for image processing
    to keep the UI responsive during adjustments.
    """

    image_load_started = pyqtSignal(str)
    image_preview_ready = pyqtSignal(str)
    image_load_finished = pyqtSignal(str, bool)
    _worker_image_set_requested = pyqtSignal(object)

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
        self._final_processing_worker: Optional[ProcessingWorker] = None
        self._debouncer: Optional[ThrottledDebouncer] = None
        self._latest_request_id: int = -1
        self._latest_presented_preview_id: int = -1
        self._latest_load_request_id: int = -1
        self._pending_final_request_id: int = -1
        self._pending_history_previous_image = None
        self._load_parent_widget: Optional[QWidget] = None
        self._load_threads: list[QThread] = []
        self._load_workers: list[_ImageLoadWorker] = []
        self._pending_preview: Optional[tuple[int, DisplayFrame]] = None
        self._preview_present_timer = QTimer(self)
        self._preview_present_timer.setSingleShot(True)
        self._preview_present_timer.setInterval(16)  # Cap UI presents ~60 FPS
        self._preview_present_timer.timeout.connect(self._present_pending_preview)
        self._final_render_timer = QTimer(self)
        self._final_render_timer.setSingleShot(True)
        self._final_render_timer.setInterval(1500)
        self._final_render_timer.timeout.connect(self._submit_delayed_final_render)
        
        if use_threading:
            self._setup_async_processing()
        
        # Connect signals
        self._connect_signals()

    def _setup_async_processing(self) -> None:
        """Set up asynchronous processing components."""
        # Create and start processing worker
        self._processing_worker = ProcessingWorker()
        self._processing_worker.preview_ready.connect(self._on_preview_ready)
        self._processing_worker.error_occurred.connect(self._on_processing_error)
        self._final_processing_worker = ProcessingWorker()
        self._final_processing_worker.processing_complete.connect(
            self._on_processing_complete
        )
        self._final_processing_worker.error_occurred.connect(
            self._on_processing_error
        )
        # Ensure expensive proxy generation runs in the worker thread.
        self._worker_image_set_requested.connect(
            self._processing_worker.set_image,
            Qt.ConnectionType.QueuedConnection,
        )
        self._worker_image_set_requested.connect(
            self._final_processing_worker.set_image,
            Qt.ConnectionType.QueuedConnection,
        )
        self._processing_worker.start()
        self._final_processing_worker.start()
        
        # Max-performance profile: throttle previews to smooth frame cadence
        # and debounce to consolidate final pause events.
        self._debouncer = ThrottledDebouncer(throttle_ms=16, debounce_ms=50)
        self._debouncer.throttled.connect(self._on_throttled_adjustment)
        self._debouncer.debounced.connect(self._on_debounced_adjustment)

    def _connect_signals(self):
        """Connect view signals to controller methods."""
        pass  # Signals will be connected as needed

    def cleanup(self) -> None:
        """Clean up resources (call before destroying)."""
        if self._processing_worker is not None:
            self._processing_worker.stop()
        if self._final_processing_worker is not None:
            self._final_processing_worker.stop()
        for thread in self._load_threads:
            thread.quit()
            thread.wait(2000)
        self._load_threads.clear()
        self._load_workers.clear()

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
            open_image_file_dialog_filter()
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
            self._apply_loaded_image(file_path, image)
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

    def load_image_async(self, file_path: str, parent: Optional[QWidget] = None) -> None:
        """Load an image in the background to keep UI responsive."""
        self._latest_load_request_id += 1
        request_id = self._latest_load_request_id
        self._load_parent_widget = parent
        self.image_load_started.emit(file_path)

        thread = QThread()
        worker = _ImageLoadWorker(request_id, file_path, self._image_service)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.preview_loaded.connect(self._on_async_image_preview_loaded)
        worker.loaded.connect(self._on_async_image_loaded)
        worker.failed.connect(self._on_async_image_failed)
        worker.loaded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda t=thread, w=worker: self._on_load_thread_finished(t, w)
        )
        self._load_threads.append(thread)
        self._load_workers.append(worker)
        thread.start()

    def _on_load_thread_finished(
        self, thread: QThread, worker: _ImageLoadWorker
    ) -> None:
        """Remove completed load resources from active tracking."""
        if thread in self._load_threads:
            self._load_threads.remove(thread)
        if worker in self._load_workers:
            self._load_workers.remove(worker)

    def _apply_loaded_image(self, file_path: str, image) -> None:
        """Apply a decoded image to model/view state on the UI thread."""
        self._image_model.file_path = file_path
        self._image_model.set_original_image(image)
        self._image_view.set_image(image)
        self._history_service.clear_history()

        # Reset adjustment params
        self._exposure_params = {}
        self._color_params = {}
        self._pending_final_request_id = -1
        self._pending_history_previous_image = None
        self._final_render_timer.stop()

        # Set image in processing worker for proxy generation
        if self._processing_worker is not None:
            self._worker_image_set_requested.emit(image)

    def _on_async_image_preview_loaded(
        self, request_id: int, file_path: str, preview
    ) -> None:
        """Show a fast preview while full-resolution decode continues."""
        if request_id != self._latest_load_request_id:
            return
        self._image_view.set_image(preview, emit_loaded=False)
        QTimer.singleShot(0, self._image_view.fit_to_window)
        self.image_preview_ready.emit(file_path)

    def _on_async_image_loaded(self, request_id: int, file_path: str, image) -> None:
        """Handle successful async image load."""
        if request_id != self._latest_load_request_id:
            return
        self._apply_loaded_image(file_path, image)
        self.image_load_finished.emit(file_path, True)

    def _on_async_image_failed(
        self, request_id: int, file_path: str, error_message: str
    ) -> None:
        """Handle async image load failure."""
        if request_id != self._latest_load_request_id:
            return
        # Preserve user-facing error semantics from synchronous load.
        if "not found" in error_message.lower():
            QMessageBox.warning(
                self._load_parent_widget,
                "File Not Found",
                f"Could not find file: {file_path}",
            )
        else:
            QMessageBox.warning(
                self._load_parent_widget,
                "Invalid Image",
                f"Could not load image: {error_message}",
            )
        self.image_load_finished.emit(file_path, False)

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
            self._image_view.set_image(
                current_image,
                emit_loaded=False,
                preserve_view_scale=True,
            )

    def reset_to_original(self) -> None:
        """Reset the image to its original state."""
        self._image_model.reset_to_original()
        self._history_service.clear_history()
        self._exposure_params = {}
        self._color_params = {}
        self._pending_final_request_id = -1
        self._pending_history_previous_image = None
        self._final_render_timer.stop()
        
        # Cancel any pending processing
        if self._processing_worker is not None:
            self._processing_worker.cancel_pending()
        if self._final_processing_worker is not None and \
           hasattr(self._final_processing_worker, "cancel_pending"):
            self._final_processing_worker.cancel_pending()
        
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

        self._final_render_timer.stop()
        self._pending_final_request_id = -1

        if self._pending_history_previous_image is None:
            current = self._image_model.get_current_image()
            if current is not None:
                # LinearImage instances are treated as immutable in the
                # pipeline. Keep the reference instead of copying a full-res
                # buffer on the UI thread.
                self._pending_history_previous_image = current
        
        # Store current params
        if exposure_params:
            self._exposure_params = exposure_params
        if color_params:
            self._color_params = color_params

        if self._use_threading and self._processing_worker is not None:
            if add_to_history:
                final_worker = self._final_processing_worker or self._processing_worker
                self._pending_final_request_id = (
                    final_worker.submit_final_request(
                        exposure_params=self._exposure_params,
                        color_params=self._color_params,
                    )
                )
            else:
                self._pending_final_request_id = -1
                self._latest_request_id = (
                    self._processing_worker.submit_preview_request(
                        exposure_params=self._exposure_params,
                        color_params=self._color_params,
                        interactive_preview=True,
                    )
                )
            return
        
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
        total_start = perf_counter()
        if not self.has_image():
            return

        cancel_start = perf_counter()
        self._final_render_timer.stop()
        self._pending_final_request_id = -1
        if self._final_processing_worker is not None and hasattr(
            self._final_processing_worker, "cancel_pending"
        ):
            self._final_processing_worker.cancel_pending()
        cancel_ms = _elapsed_ms(cancel_start)
        
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
            # Use throttled + debounced async processing
            self._debouncer.call({
                'exposure': exposure_params,
                'color': color_params
            })
            mode = "debounced-threaded"
        else:
            # Fallback to synchronous processing
            self.apply_adjustments(exposure_params, color_params, add_to_history=False)
            mode = "sync-fallback"

        logger.info(
            "PERF controller.adjustments_changed mode=%s cancel_final_ms=%.2f "
            "total_ms=%.2f exposure=%s contrast=%s brightness=%s saturation=%s "
            "vibrance=%s",
            mode,
            cancel_ms,
            _elapsed_ms(total_start),
            exposure_params.get("exposure"),
            exposure_params.get("contrast"),
            exposure_params.get("brightness"),
            color_params.get("saturation"),
            color_params.get("vibrance"),
        )

    def _on_throttled_adjustment(self, params: dict) -> None:
        """Handle throttled live preview updates during slider drags."""
        start = perf_counter()
        if not self.has_image() or self._processing_worker is None:
            return
        self._final_render_timer.stop()
        self._pending_final_request_id = -1

        exposure_params = params.get('exposure', {})
        color_params = params.get('color', {})
        self._latest_request_id = self._processing_worker.submit_preview_request(
            exposure_params=exposure_params,
            color_params=color_params,
            interactive_preview=True,
        )
        logger.info(
            "PERF controller.submit_preview request=%s tier=interactive "
            "schedule_ms=%.2f",
            self._latest_request_id,
            _elapsed_ms(start),
        )

    def _on_debounced_adjustment(self, params: dict) -> None:
        """Handle debounced adjustment (called after slider pause).
        
        Args:
            params: Dictionary with 'exposure' and 'color' params
        """
        start = perf_counter()
        if not self.has_image() or self._processing_worker is None:
            return
        self._final_render_timer.stop()
        self._pending_final_request_id = -1
        
        exposure_params = params.get('exposure', {})
        color_params = params.get('color', {})
        
        # Keep pause updates on the cheap interactive tier. Quality previews are
        # presented on release so larger frames cannot interrupt active drags.
        self._latest_request_id = self._processing_worker.submit_preview_request(
            exposure_params=exposure_params,
            color_params=color_params,
            interactive_preview=True,
        )
        logger.info(
            "PERF controller.submit_preview request=%s tier=interactive-idle "
            "schedule_ms=%.2f",
            self._latest_request_id,
            _elapsed_ms(start),
        )

    def _on_preview_ready(self, request_id: int, frame) -> None:
        """Handle preview ``DisplayFrame`` ready from worker."""
        start = perf_counter()
        if self._processing_worker is not None and \
           self._processing_worker.is_latest_request(request_id):
            if not isinstance(frame, DisplayFrame):
                logger.warning(
                    "Ignoring preview request=%s with unexpected payload %s",
                    request_id,
                    type(frame).__name__,
                )
                return
            # Coalesce preview presents so conversion/paint cadence is bounded.
            if request_id < self._latest_presented_preview_id:
                return
            if frame.tier == "quality" and request_id != self._latest_request_id:
                return
            self._pending_preview = (request_id, frame)
            if not self._preview_present_timer.isActive():
                self._present_pending_preview()
                self._preview_present_timer.start()
            logger.info(
                "PERF controller.preview_ready request=%s shape=%s total_ms=%.2f",
                request_id,
                frame.shape,
                _elapsed_ms(start),
            )

    def _present_pending_preview(self) -> None:
        """Present the latest pending preview frame (if any)."""
        start = perf_counter()
        if self._pending_preview is None:
            return
        request_id, frame = self._pending_preview
        self._pending_preview = None
        self._latest_presented_preview_id = request_id
        if frame.linear_image is not None:
            self._image_model.current_image = frame.linear_image
        self._image_view.set_display_frame(frame, preserve_view_scale=True)
        logger.info(
            "PERF controller.present_preview request=%s shape=%s total_ms=%.2f",
            request_id,
            frame.shape,
            _elapsed_ms(start),
        )

    def _on_processing_complete(self, request_id: int, image) -> None:
        """Handle full-resolution processing complete from worker."""
        final_worker = self._final_processing_worker or self._processing_worker
        if final_worker is not None and \
           not final_worker.is_latest_request(request_id):
            return
        if request_id != self._pending_final_request_id:
            return

        # Final frame should supersede queued previews immediately.
        self._pending_preview = None
        self._preview_present_timer.stop()
        self._image_model.current_image = image

        self._commit_rendered_adjustment(image)

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
        start = perf_counter()
        if not self.has_image():
            return
        
        if self._use_threading and self._processing_worker is not None:
            # Cancel any pending throttled/debounced preview events so release
            # goes straight to final processing.
            if self._debouncer is not None:
                self._debouncer.cancel()

            # Show a better quality proxy immediately; the full-res render is
            # delayed and uses a separate worker so it cannot block previews.
            self._latest_request_id = self._processing_worker.submit_preview_request(
                exposure_params=self._exposure_params,
                color_params=self._color_params,
                interactive_preview=False,
            )

            # Delay full-resolution processing. If the user grabs
            # the slider again, the next adjustment cancels this timer before
            # an expensive full render can occupy the worker.
            self._final_render_timer.start()
            logger.info(
                "PERF controller.slider_released quality_request=%s "
                "full_idle_delay_ms=%s schedule_ms=%.2f",
                self._latest_request_id,
                self._final_render_timer.interval(),
                _elapsed_ms(start),
            )
            return
        
        # Synchronous fallback for tests/non-threaded callers only.
        self.commit_adjustments()

    def _submit_delayed_final_render(self) -> None:
        """Submit full-resolution render after the user has stayed idle."""
        start = perf_counter()
        final_worker = self._final_processing_worker or self._processing_worker
        if not self.has_image() or final_worker is None:
            return

        has_changes = (
            any(v != 0 for v in self._exposure_params.values()) or
            any(v != 0 for v in self._color_params.values())
        )
        if not has_changes:
            self._pending_history_previous_image = None
            return

        self._pending_final_request_id = final_worker.submit_final_request(
            exposure_params=self._exposure_params,
            color_params=self._color_params,
        )
        logger.info(
            "PERF controller.submit_full request=%s schedule_ms=%.2f",
            self._pending_final_request_id,
            _elapsed_ms(start),
        )

    def _commit_rendered_adjustment(self, rendered_image) -> None:
        """Add a completed worker render to history without reprocessing."""
        start = perf_counter()
        previous = self._pending_history_previous_image
        self._pending_history_previous_image = None
        self._pending_final_request_id = -1

        if previous is None:
            return

        has_changes = (
            any(v != 0 for v in self._exposure_params.values()) or
            any(v != 0 for v in self._color_params.values())
        )
        if not has_changes:
            return

        command = ImageStateChangeCommand(
            self._image_model,
            previous_image=previous,
            new_image=rendered_image,
        )
        self._history_service.execute_command(command)
        logger.info(
            "PERF controller.commit_rendered shape=%s total_ms=%.2f",
            rendered_image.shape,
            _elapsed_ms(start),
        )

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
