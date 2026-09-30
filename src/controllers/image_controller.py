"""Controller for image operations."""

import logging
from time import perf_counter
from typing import Any, Dict, List, Optional
from PyQt6.QtWidgets import QFileDialog, QWidget, QMessageBox
from PyQt6.QtCore import QObject, QThread, Qt, QTimer, pyqtSignal

from src.models.image_model import ImageModel
from src.services.image_service import ImageService
from src.services.history_service import HistoryService
from src.services.settings_service import SettingsService
from src.views.image_view import ImageView
from src.processors.exposure_processor import ExposureProcessor
from src.processors.tonal_processor import TonalProcessor
from src.processors.color_processor import ColorProcessor
from src.processors.curve_processor import CurveProcessor
from src.processors.white_balance_processor import WhiteBalanceProcessor
from src.processors.hsl_mixer_processor import HslMixerProcessor, default_hsl_params
from src.processors.color_grading_processor import (
    ColorGradingProcessor,
    default_color_grading_params,
)
from src.commands.adjustment_commands import (
    CombinedAdjustmentCommand,
    ImageStateChangeCommand,
)
from src.processing.display_frame import DisplayFrame
from src.processing.processing_worker import ProcessingWorker
from src.utils.curve_math import DEFAULT_CURVE_POINTS, is_identity_curve, normalize_points
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
    _ADJUSTMENT_DEFAULTS = {
        "exposure": 0.0,
        "contrast": 0.0,
        "brightness": 0.0,
        "highlights": 0.0,
        "shadows": 0.0,
        "whites": 0.0,
        "blacks": 0.0,
        "temperature": 0.0,
        "tint": 0.0,
        "saturation": 0.0,
        "vibrance": 0.0,
    }
    # Tone curve control points are not floats, so they are kept out of
    # _ADJUSTMENT_DEFAULTS (which _normalize_adjustment_state float-casts
    # every value of) and threaded as a separate, parallel parameter --
    # see docs/planning/implementation-notes/2026-09-29-tone-curve.md.
    _CURVE_DEFAULT_POINTS = DEFAULT_CURVE_POINTS
    # The HSL Color Mixer's 24 keys are plain floats, but are kept out of
    # the top-level get_adjustment_state()/_ADJUSTMENT_DEFAULTS contract
    # (nested under one "hsl" key instead) so persistence/exact-dict tests
    # don't have to list 24 extra entries -- see
    # docs/planning/implementation-notes/2026-09-30-hsl-color-mixer.md.
    _HSL_DEFAULTS = default_hsl_params()
    # Color Grading's 11 keys follow the exact same reasoning as HSL above
    # -- nested under one "color_grading" key -- see
    # docs/planning/implementation-notes/2026-09-30-color-grading.md.
    _COLOR_GRADING_DEFAULTS = default_color_grading_params()

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
        
        # Processors (for synchronous fallback / export)
        self._exposure_processor = ExposureProcessor()
        self._tonal_processor = TonalProcessor()
        self._curve_processor = CurveProcessor()
        self._wb_processor = WhiteBalanceProcessor()
        self._color_processor = ColorProcessor()
        self._hsl_processor = HslMixerProcessor()
        self._color_grading_processor = ColorGradingProcessor()

        # Current adjustment values
        self._exposure_params: Dict[str, float] = {}
        self._tonal_params: Dict[str, float] = {}
        self._color_params: Dict[str, float] = {}
        self._curve_params: Dict[str, Any] = {}
        self._wb_params: Dict[str, float] = {}
        self._hsl_params: Dict[str, float] = {}
        self._color_grading_params: Dict[str, float] = {}
        
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
        self._skip_intermediate_preview_request_ids: set[int] = set()
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
        """Clean up resources (call before destroying).

        A load thread runs an uninterruptible, unbounded-length decode
        (``_ImageLoadWorker.run()`` has no cancellation check), so
        ``thread.wait(2000)`` can time out while it is still mid-decode --
        e.g. a large RAW file, or simply a slow machine. The previous
        version unconditionally cleared ``_load_threads``/``_load_workers``
        regardless of whether ``wait()`` actually succeeded, dropping the
        last Python reference to a ``QThread``/worker pair whose native
        thread was still running. Garbage-collecting that pair while the
        background thread still touches it is a use-after-free at the Qt
        C++ level -- reproduced directly as a ``Fatal Python error:
        Aborted`` crash when a slow load thread was still in flight at
        teardown. Only threads that actually stopped in time are
        forgotten here; a still-running one is left tracked so it stays
        referenced until its own ``finished`` handlers (already connected
        in :meth:`load_image_async`) tear it down once the decode
        completes on its own.
        """
        if self._processing_worker is not None:
            self._processing_worker.stop()
        if self._final_processing_worker is not None:
            self._final_processing_worker.stop()

        still_running_threads: list[QThread] = []
        still_running_workers: list[_ImageLoadWorker] = []
        for thread, worker in zip(self._load_threads, self._load_workers):
            thread.quit()
            if not thread.wait(2000):
                logger.warning(
                    "Image load thread still running after cleanup timeout; "
                    "leaving it tracked until it finishes on its own"
                )
                still_running_threads.append(thread)
                still_running_workers.append(worker)
        self._load_threads = still_running_threads
        self._load_workers = still_running_workers

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
        self._load_parent_widget = parent
        self.image_load_started.emit(file_path)
        try:
            image = self._image_service.load_image(file_path)
            self._apply_loaded_image(file_path, image)
            self.image_load_finished.emit(file_path, True)
            return True
        except FileNotFoundError:
            QMessageBox.warning(
                parent,
                "File Not Found",
                f"Could not find file: {file_path}"
            )
            self.image_load_finished.emit(file_path, False)
            return False
        except ValueError as e:
            QMessageBox.warning(
                parent,
                "Invalid Image",
                f"Could not load image: {str(e)}"
            )
            self.image_load_finished.emit(file_path, False)
            return False

    def load_image_async(
        self,
        file_path: str,
        parent: Optional[QWidget] = None,
        show_intermediate_preview: bool = True,
    ) -> None:
        """Load an image in the background to keep UI responsive."""
        self._latest_load_request_id += 1
        request_id = self._latest_load_request_id
        self._load_parent_widget = parent
        if not show_intermediate_preview:
            self._skip_intermediate_preview_request_ids.add(request_id)
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
        self._tonal_params = {}
        self._color_params = {}
        self._curve_params = {}
        self._wb_params = {}
        self._hsl_params = {}
        self._color_grading_params = {}
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
        if request_id in self._skip_intermediate_preview_request_ids:
            return
        self._image_view.set_image(preview, emit_loaded=False)
        QTimer.singleShot(0, self._image_view.fit_to_window)
        self.image_preview_ready.emit(file_path)

    def _on_async_image_loaded(self, request_id: int, file_path: str, image) -> None:
        """Handle successful async image load."""
        if request_id != self._latest_load_request_id:
            return
        self._skip_intermediate_preview_request_ids.discard(request_id)
        self._apply_loaded_image(file_path, image)
        self.image_load_finished.emit(file_path, True)

    def _on_async_image_failed(
        self, request_id: int, file_path: str, error_message: str
    ) -> None:
        """Handle async image load failure."""
        if request_id != self._latest_load_request_id:
            return
        self._skip_intermediate_preview_request_ids.discard(request_id)
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
            Current ``LinearImage`` or None
        """
        return self._image_model.get_current_image()

    def get_export_image(self):
        """Get the full-resolution image for export.

        Recomputes directly from the original image and the currently
        active adjustment parameters, rather than trusting whatever is
        cached in ``current_image``. That field is deliberately allowed to
        hold a lower-resolution preview frame for a moment during an
        interactive drag (see ``_present_pending_preview``), so reading it
        directly risks exporting an undersized image if export is
        triggered before it settles back to a full-resolution render.
        This always reprocesses the true original at full size, so it is
        correct regardless of that timing.

        Returns:
            Full-resolution ``LinearImage`` with current adjustments
            applied, or None if no image is loaded.
        """
        if not self.has_image():
            return None

        original = self._image_model.get_original_image()
        if original is None:
            return None

        result = original.copy()
        if self._exposure_params:
            result = self._exposure_processor.process(result, **self._exposure_params)
        if self._tonal_params:
            result = self._tonal_processor.process(result, **self._tonal_params)
        if self._wb_params:
            result = self._wb_processor.process(result, **self._wb_params)
        if self._curve_params:
            result = self._curve_processor.process(result, **self._curve_params)
        if self._color_params:
            result = self._color_processor.process(result, **self._color_params)
        if self._hsl_params:
            result = self._hsl_processor.process(result, **self._hsl_params)
        if self._color_grading_params:
            result = self._color_grading_processor.process(
                result, **self._color_grading_params
            )
        return result

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

    def get_adjustment_state(self) -> Dict[str, Any]:
        """Return the current normalized adjustment payload.

        Includes three non-flat keys alongside the eleven float keys:
        ``"tone_curve"`` (a JSON-plain list of ``[x, y]`` control points --
        see docs/planning/implementation-notes/2026-09-29-tone-curve.md
        section 4), ``"hsl"`` (a flat 24-key dict for the Color Mixer --
        see docs/planning/implementation-notes/2026-09-30-hsl-color-mixer.md
        section 4), and ``"color_grading"`` (a flat 11-key dict -- see
        docs/planning/implementation-notes/2026-09-30-color-grading.md
        section 4).
        """
        state: Dict[str, Any] = self._ADJUSTMENT_DEFAULTS.copy()
        state.update(self._exposure_params)
        state.update(self._tonal_params)
        state.update(self._wb_params)
        state.update(self._color_params)
        curve_points = self._curve_params.get("points", self._CURVE_DEFAULT_POINTS)
        state["tone_curve"] = [list(point) for point in curve_points]
        state["hsl"] = {**self._HSL_DEFAULTS, **self._hsl_params}
        state["color_grading"] = {
            **self._COLOR_GRADING_DEFAULTS,
            **self._color_grading_params,
        }
        return state

    def restore_adjustment_state(self, adjustments: Optional[Dict[str, Any]]) -> None:
        """Apply a saved adjustment payload without creating undo history."""
        normalized = self._normalize_adjustment_state(adjustments)
        curve_points = normalize_points(
            adjustments.get("tone_curve") if adjustments else None
        )
        hsl_values = self._normalize_hsl_state(
            adjustments.get("hsl") if adjustments else None
        )
        color_grading_values = self._normalize_color_grading_state(
            adjustments.get("color_grading") if adjustments else None
        )
        self._history_service.clear_history()
        self._pending_history_previous_image = None
        self._pending_final_request_id = -1
        self._final_render_timer.stop()
        if self._debouncer is not None:
            self._debouncer.cancel()
        if self._processing_worker is not None and hasattr(
            self._processing_worker, "cancel_pending"
        ):
            self._processing_worker.cancel_pending()
        if self._final_processing_worker is not None and hasattr(
            self._final_processing_worker, "cancel_pending"
        ):
            self._final_processing_worker.cancel_pending()

        self._exposure_params = {
            "exposure": normalized["exposure"],
            "contrast": normalized["contrast"],
            "brightness": normalized["brightness"],
        }
        self._tonal_params = {
            "highlights": normalized["highlights"],
            "shadows": normalized["shadows"],
            "whites": normalized["whites"],
            "blacks": normalized["blacks"],
        }
        self._wb_params = {
            "temperature": normalized["temperature"],
            "tint": normalized["tint"],
        }
        self._color_params = {
            "saturation": normalized["saturation"],
            "vibrance": normalized["vibrance"],
        }
        self._curve_params = (
            {"points": curve_points} if not is_identity_curve(curve_points) else {}
        )
        self._hsl_params = hsl_values
        self._color_grading_params = color_grading_values

        if not self.has_image():
            return

        has_changes = (
            any(value != 0.0 for value in normalized.values())
            or not is_identity_curve(curve_points)
            or any(value != 0.0 for value in hsl_values.values())
            or any(
                color_grading_values.get(key, 0.0) != default
                for key, default in self._COLOR_GRADING_DEFAULTS.items()
            )
        )
        if not has_changes:
            self._image_model.reset_to_original()
            self.refresh_view()
            return

        original = self._image_model.get_original_image()
        if original is None:
            return

        result = original.copy()
        result = self._exposure_processor.process(result, **self._exposure_params)
        result = self._tonal_processor.process(result, **self._tonal_params)
        result = self._wb_processor.process(result, **self._wb_params)
        if self._curve_params:
            result = self._curve_processor.process(result, **self._curve_params)
        result = self._color_processor.process(result, **self._color_params)
        result = self._hsl_processor.process(result, **self._hsl_params)
        result = self._color_grading_processor.process(
            result, **self._color_grading_params
        )
        self._image_model.current_image = result
        self.refresh_view()

    def reset_to_original(self) -> None:
        """Reset the image to its original state."""
        self._image_model.reset_to_original()
        self._history_service.clear_history()
        self._exposure_params = {}
        self._tonal_params = {}
        self._color_params = {}
        self._curve_params = {}
        self._wb_params = {}
        self._hsl_params = {}
        self._color_grading_params = {}
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
        tonal_params: Dict[str, float] = None,
        color_params: Dict[str, float] = None,
        curve_params: Dict[str, Any] = None,
        wb_params: Dict[str, float] = None,
        hsl_params: Dict[str, float] = None,
        color_grading_params: Dict[str, float] = None,
        add_to_history: bool = False
    ) -> None:
        """Apply adjustments to the image (synchronous).

        Args:
            exposure_params: Exposure adjustment parameters
            tonal_params: Highlights/Shadows/Whites/Blacks parameters
            color_params: Color adjustment parameters
            curve_params: Tone curve parameters (``{"points": [...]}`)
            wb_params: White balance (Temperature/Tint) parameters
            hsl_params: HSL Color Mixer parameters (24-key flat dict)
            color_grading_params: Color Grading parameters (11-key flat dict)
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
        if tonal_params:
            self._tonal_params = tonal_params
        if color_params:
            self._color_params = color_params
        if curve_params is not None:
            self._curve_params = curve_params
        if wb_params:
            self._wb_params = wb_params
        if hsl_params:
            self._hsl_params = hsl_params
        if color_grading_params:
            self._color_grading_params = color_grading_params

        if self._use_threading and self._processing_worker is not None:
            if add_to_history:
                final_worker = self._final_processing_worker or self._processing_worker
                self._pending_final_request_id = (
                    final_worker.submit_final_request(
                        exposure_params=self._exposure_params,
                        tonal_params=self._tonal_params,
                        color_params=self._color_params,
                        curve_params=self._curve_params,
                        wb_params=self._wb_params,
                        hsl_params=self._hsl_params,
                        color_grading_params=self._color_grading_params,
                    )
                )
            else:
                self._pending_final_request_id = -1
                self._latest_request_id = (
                    self._processing_worker.submit_preview_request(
                        exposure_params=self._exposure_params,
                        tonal_params=self._tonal_params,
                        color_params=self._color_params,
                        curve_params=self._curve_params,
                        wb_params=self._wb_params,
                        hsl_params=self._hsl_params,
                        color_grading_params=self._color_grading_params,
                        interactive_preview=True,
                    )
                )
            return

        if add_to_history:
            # Create and execute command for undo/redo
            command = CombinedAdjustmentCommand(
                self._image_model,
                exposure_params=self._exposure_params,
                tonal_params=self._tonal_params,
                color_params=self._color_params,
                curve_params=self._curve_params,
                wb_params=self._wb_params,
                hsl_params=self._hsl_params,
                color_grading_params=self._color_grading_params,
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

            # Apply tonal adjustments
            if self._tonal_params:
                result = self._tonal_processor.process(result, **self._tonal_params)

            # Apply white balance
            if self._wb_params:
                result = self._wb_processor.process(result, **self._wb_params)

            # Apply tone curve
            if self._curve_params:
                result = self._curve_processor.process(result, **self._curve_params)

            # Apply color adjustments
            if self._color_params:
                result = self._color_processor.process(result, **self._color_params)

            # Apply HSL Color Mixer
            if self._hsl_params:
                result = self._hsl_processor.process(result, **self._hsl_params)

            # Apply Color Grading
            if self._color_grading_params:
                result = self._color_grading_processor.process(
                    result, **self._color_grading_params
                )

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

        # Capture the state this adjustment gesture started from, once per
        # gesture, so that when the delayed full-resolution render lands
        # (see _submit_delayed_final_render / _commit_rendered_adjustment)
        # there is a "before" image to diff against and undo has something
        # to restore. Without this, dragging a slider through the normal
        # UI path and releasing it would compute the final image correctly
        # but silently never add it to history.
        if self._pending_history_previous_image is None:
            current = self._image_model.get_current_image()
            if current is not None:
                self._pending_history_previous_image = current

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
        tonal_params = {
            'highlights': adjustments.get('highlights', 0.0),
            'shadows': adjustments.get('shadows', 0.0),
            'whites': adjustments.get('whites', 0.0),
            'blacks': adjustments.get('blacks', 0.0)
        }
        wb_params = {
            'temperature': adjustments.get('temperature', 0.0),
            'tint': adjustments.get('tint', 0.0),
        }
        color_params = {
            'saturation': adjustments.get('saturation', 0.0),
            'vibrance': adjustments.get('vibrance', 0.0)
        }

        # Store params
        self._exposure_params = exposure_params
        self._tonal_params = tonal_params
        self._wb_params = wb_params
        self._color_params = color_params

        if self._use_threading and self._debouncer is not None:
            # Use throttled + debounced async processing. The curve and
            # HSL mixer are not part of this signal's payload, so re-send
            # their currently stored params -- ThrottledDebouncer.call()
            # replaces the whole pending dict, so omitting them here would
            # revert an in-progress curve/HSL edit on the next slider move.
            self._debouncer.call({
                'exposure': exposure_params,
                'tonal': tonal_params,
                'color': color_params,
                'curve': self._curve_params,
                'wb': wb_params,
                'hsl': self._hsl_params,
                'color_grading': self._color_grading_params,
            })
            mode = "debounced-threaded"
        else:
            # Fallback to synchronous processing
            self.apply_adjustments(
                exposure_params,
                tonal_params,
                color_params,
                self._curve_params,
                wb_params,
                self._hsl_params,
                self._color_grading_params,
                add_to_history=False,
            )
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

    def on_curve_changed(self, points: List[Any]) -> None:
        """Handle tone curve changes from the tools panel.

        Mirrors :meth:`on_adjustments_changed` but for the tone curve,
        which travels on its own signal/parameter (see
        docs/planning/implementation-notes/2026-09-29-tone-curve.md).
        """
        if not self.has_image():
            return

        if self._pending_history_previous_image is None:
            current = self._image_model.get_current_image()
            if current is not None:
                self._pending_history_previous_image = current

        self._final_render_timer.stop()
        self._pending_final_request_id = -1
        if self._final_processing_worker is not None and hasattr(
            self._final_processing_worker, "cancel_pending"
        ):
            self._final_processing_worker.cancel_pending()

        normalized_points = normalize_points(points)
        self._curve_params = (
            {"points": normalized_points}
            if not is_identity_curve(normalized_points)
            else {}
        )

        if self._use_threading and self._debouncer is not None:
            self._debouncer.call({
                'exposure': self._exposure_params,
                'tonal': self._tonal_params,
                'color': self._color_params,
                'curve': self._curve_params,
                'wb': self._wb_params,
                'hsl': self._hsl_params,
                'color_grading': self._color_grading_params,
            })
        else:
            self.apply_adjustments(
                self._exposure_params,
                self._tonal_params,
                self._color_params,
                self._curve_params,
                self._wb_params,
                self._hsl_params,
                self._color_grading_params,
                add_to_history=False,
            )

    def on_hsl_changed(self, values: Dict[str, float]) -> None:
        """Handle HSL Color Mixer changes from the tools panel.

        Mirrors :meth:`on_curve_changed` but for the HSL mixer, which also
        travels on its own signal/parameter rather than the main flat
        adjustments dict (see
        docs/planning/implementation-notes/2026-09-30-hsl-color-mixer.md).
        """
        if not self.has_image():
            return

        if self._pending_history_previous_image is None:
            current = self._image_model.get_current_image()
            if current is not None:
                self._pending_history_previous_image = current

        self._final_render_timer.stop()
        self._pending_final_request_id = -1
        if self._final_processing_worker is not None and hasattr(
            self._final_processing_worker, "cancel_pending"
        ):
            self._final_processing_worker.cancel_pending()

        self._hsl_params = self._normalize_hsl_state(values)

        if self._use_threading and self._debouncer is not None:
            self._debouncer.call({
                'exposure': self._exposure_params,
                'tonal': self._tonal_params,
                'color': self._color_params,
                'curve': self._curve_params,
                'wb': self._wb_params,
                'hsl': self._hsl_params,
                'color_grading': self._color_grading_params,
            })
        else:
            self.apply_adjustments(
                self._exposure_params,
                self._tonal_params,
                self._color_params,
                self._curve_params,
                self._wb_params,
                self._hsl_params,
                self._color_grading_params,
                add_to_history=False,
            )

    def on_color_grading_changed(self, values: Dict[str, float]) -> None:
        """Handle Color Grading changes from the tools panel.

        Mirrors :meth:`on_hsl_changed` but for Color Grading, which also
        travels on its own signal/parameter rather than the main flat
        adjustments dict (see
        docs/planning/implementation-notes/2026-09-30-color-grading.md).
        """
        if not self.has_image():
            return

        if self._pending_history_previous_image is None:
            current = self._image_model.get_current_image()
            if current is not None:
                self._pending_history_previous_image = current

        self._final_render_timer.stop()
        self._pending_final_request_id = -1
        if self._final_processing_worker is not None and hasattr(
            self._final_processing_worker, "cancel_pending"
        ):
            self._final_processing_worker.cancel_pending()

        self._color_grading_params = self._normalize_color_grading_state(values)

        if self._use_threading and self._debouncer is not None:
            self._debouncer.call({
                'exposure': self._exposure_params,
                'tonal': self._tonal_params,
                'color': self._color_params,
                'curve': self._curve_params,
                'wb': self._wb_params,
                'hsl': self._hsl_params,
                'color_grading': self._color_grading_params,
            })
        else:
            self.apply_adjustments(
                self._exposure_params,
                self._tonal_params,
                self._color_params,
                self._curve_params,
                self._wb_params,
                self._hsl_params,
                self._color_grading_params,
                add_to_history=False,
            )

    def _on_throttled_adjustment(self, params: dict) -> None:
        """Handle throttled live preview updates during slider drags."""
        start = perf_counter()
        if not self.has_image() or self._processing_worker is None:
            return
        self._final_render_timer.stop()
        self._pending_final_request_id = -1

        exposure_params = params.get('exposure', {})
        tonal_params = params.get('tonal', {})
        color_params = params.get('color', {})
        curve_params = params.get('curve', {})
        wb_params = params.get('wb', {})
        hsl_params = params.get('hsl', {})
        color_grading_params = params.get('color_grading', {})
        self._latest_request_id = self._processing_worker.submit_preview_request(
            exposure_params=exposure_params,
            tonal_params=tonal_params,
            color_params=color_params,
            curve_params=curve_params,
            wb_params=wb_params,
            hsl_params=hsl_params,
            color_grading_params=color_grading_params,
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
        tonal_params = params.get('tonal', {})
        color_params = params.get('color', {})
        curve_params = params.get('curve', {})
        wb_params = params.get('wb', {})
        hsl_params = params.get('hsl', {})
        color_grading_params = params.get('color_grading', {})

        # Keep pause updates on the cheap interactive tier. Quality previews are
        # presented on release so larger frames cannot interrupt active drags.
        self._latest_request_id = self._processing_worker.submit_preview_request(
            exposure_params=exposure_params,
            tonal_params=tonal_params,
            color_params=color_params,
            curve_params=curve_params,
            wb_params=wb_params,
            hsl_params=hsl_params,
            color_grading_params=color_grading_params,
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
                tonal_params=self._tonal_params,
                color_params=self._color_params,
                curve_params=self._curve_params,
                wb_params=self._wb_params,
                hsl_params=self._hsl_params,
                color_grading_params=self._color_grading_params,
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

    def _has_pending_adjustment_changes(self) -> bool:
        """True if any current adjustment (including the tone curve) is non-default."""
        return (
            any(v != 0 for v in self._exposure_params.values()) or
            any(v != 0 for v in self._tonal_params.values()) or
            any(v != 0 for v in self._wb_params.values()) or
            any(v != 0 for v in self._color_params.values()) or
            any(v != 0 for v in self._hsl_params.values()) or
            any(
                self._color_grading_params.get(key, 0.0) != default
                for key, default in self._COLOR_GRADING_DEFAULTS.items()
            ) or
            not is_identity_curve(self._curve_params.get("points"))
        )

    def _submit_delayed_final_render(self) -> None:
        """Submit full-resolution render after the user has stayed idle."""
        start = perf_counter()
        final_worker = self._final_processing_worker or self._processing_worker
        if not self.has_image() or final_worker is None:
            return

        if not self._has_pending_adjustment_changes():
            self._pending_history_previous_image = None
            return

        self._pending_final_request_id = final_worker.submit_final_request(
            exposure_params=self._exposure_params,
            tonal_params=self._tonal_params,
            color_params=self._color_params,
            curve_params=self._curve_params,
            wb_params=self._wb_params,
            hsl_params=self._hsl_params,
            color_grading_params=self._color_grading_params,
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

        if not self._has_pending_adjustment_changes():
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
        if self._has_pending_adjustment_changes():
            command = CombinedAdjustmentCommand(
                self._image_model,
                exposure_params=self._exposure_params.copy(),
                tonal_params=self._tonal_params.copy(),
                color_params=self._color_params.copy(),
                curve_params=dict(self._curve_params),
                wb_params=self._wb_params.copy(),
                hsl_params=self._hsl_params.copy(),
                color_grading_params=self._color_grading_params.copy(),
            )
            self._history_service.execute_command(command)

    def _normalize_adjustment_state(
        self,
        adjustments: Optional[Dict[str, float]],
    ) -> Dict[str, float]:
        """Return a complete adjustment-state payload with defaulted values."""
        return self._normalize_floats(adjustments, self._ADJUSTMENT_DEFAULTS)

    def _normalize_hsl_state(
        self,
        raw_hsl: Optional[Dict[str, float]],
    ) -> Dict[str, float]:
        """Return a complete 24-key HSL Color Mixer payload, defaulted to 0."""
        return self._normalize_floats(raw_hsl, self._HSL_DEFAULTS)

    def _normalize_color_grading_state(
        self,
        raw_color_grading: Optional[Dict[str, float]],
    ) -> Dict[str, float]:
        """Return a complete 11-key Color Grading payload, defaulted to identity."""
        return self._normalize_floats(raw_color_grading, self._COLOR_GRADING_DEFAULTS)

    @staticmethod
    def _normalize_floats(
        values: Optional[Dict[str, float]],
        defaults: Dict[str, float],
    ) -> Dict[str, float]:
        """Coerce ``values`` to floats against ``defaults``, tolerating bad input.

        Shared by :meth:`_normalize_adjustment_state` and
        :meth:`_normalize_hsl_state` so the float-coercion tolerance (bad
        types/missing keys fall back to the default rather than raising)
        is defined once.
        """
        normalized = defaults.copy()
        if not values or not isinstance(values, dict):
            return normalized
        for key, default in normalized.items():
            value = values.get(key, default)
            try:
                normalized[key] = float(value)
            except (TypeError, ValueError):
                normalized[key] = default
        return normalized
