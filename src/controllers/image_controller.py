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
from src.processors.texture_processor import TextureProcessor
from src.processors.clarity_processor import ClarityProcessor
from src.processors.dehaze_processor import DehazeProcessor
from src.processors.vignette_processor import VignetteProcessor
from src.processors.grain_processor import GrainProcessor
from src.processors.sharpening_processor import SharpeningProcessor
from src.processors.luminance_noise_reduction_processor import (
    LuminanceNoiseReductionProcessor,
)
from src.processors.color_noise_reduction_processor import (
    ColorNoiseReductionProcessor,
)
from src.processors.remove_chromatic_aberration_processor import (
    RemoveChromaticAberrationProcessor,
)
from src.processors.defringe_processor import DefringeProcessor
from src.processors.geometry_processor import GeometryProcessor
from src.processors.straighten_processor import StraightenProcessor
from src.processors.crop_processor import CropProcessor
from src.processors.mask_processor import MaskProcessor
from src.processors.healing_processor import HealingProcessor
from src.commands.adjustment_commands import (
    AdjustmentStateCommand,
    CombinedAdjustmentCommand,
)
from src.processing.display_frame import DisplayFrame
from src.processing.export_render import start_export_render
from src.processing.processing_worker import ProcessingWorker
from src.utils.curve_math import DEFAULT_CURVE_POINTS, is_identity_curve, normalize_points
from src.utils.debouncer import ThrottledDebouncer
from src.utils.image_extensions import open_image_file_dialog_filter
logger = logging.getLogger(__name__)

# Private "no override passed" sentinel for get_export_image's mask_override
# parameter -- distinct from both None and {} ("no mask"), which are both
# legitimate override VALUES a caller may want to pass explicitly.
_UNSET = object()


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
            # Convert to display RGB here, not on the UI thread: a 24 MP
            # float-to-RGB pass is ~300 ms, which used to freeze every open.
            frame = DisplayFrame.from_linear(-1, "full", (), image)
            self.loaded.emit(
                self._request_id, self._file_path, LoadedImage(image, frame)
            )
        except Exception as e:
            self.failed.emit(self._request_id, self._file_path, str(e))


class LoadedImage:
    """A decoded image plus its display frame, built on the load thread."""

    __slots__ = ("image", "frame")

    def __init__(self, image, frame: Optional[DisplayFrame]):
        self.image = image
        self.frame = frame


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
    # Emitted after apply_history_state() re-applies a full (image,
    # adjustment-state) snapshot -- on undo, redo, and also on an ordinary
    # adjustment commit (both paths push an AdjustmentStateCommand; see
    # docs/planning/implementation-notes/2026-10-13-state-aware-undo-redo.md).
    # Carries the same dict shape as get_adjustment_state(). MainWindow
    # listens to this to resync the ToolsPanel sliders/curve/HSL/Color
    # Grading widgets and re-persist to the library catalog.
    adjustment_state_restored = pyqtSignal(dict)
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
        "texture": 0.0,
        "clarity": 0.0,
        "dehaze": 0.0,
        "vignette": 0.0,
        "grain": 0.0,
        "sharpening": 0.0,
        "luminance_nr": 0.0,
        "color_nr": 0.0,
        "remove_ca": 0.0,
        "defringe": 0.0,
        "straighten": 0.0,
        "distortion": 0.0,
        "vertical": 0.0,
        "horizontal": 0.0,
        "scale": 100.0,
        "offset_x": 0.0,
        "offset_y": 0.0,
    }
    # Tone curve control points are not floats, so they are kept out of
    # _ADJUSTMENT_DEFAULTS (which _normalize_adjustment_state float-casts
    # every value of) and threaded as a separate, parallel parameter --
    # see docs/planning/implementation-notes/2026-09-29-tone-curve.md.
    _CURVE_DEFAULT_POINTS = DEFAULT_CURVE_POINTS
    # Per-channel curves (PDF section 12, Phase E -- see
    # docs/planning/implementation-notes/2026-10-13-per-channel-curves.md):
    # the master curve's own "points" key, above, is joined by 3 more
    # OPTIONAL keys inside the same ``_curve_params`` dict, one per
    # Red/Green/Blue channel. Like "points" itself, each is only present
    # in ``_curve_params`` when that one channel's curve is non-identity
    # (the same falsy-skip convention every ``_xxx_params`` field uses),
    # so ``CurveProcessor.process(**self._curve_params)`` only builds a
    # LUT for a channel that actually needs one.
    _CURVE_CHANNEL_KEYS = {
        "master": "points",
        "red": "red_points",
        "green": "green_points",
        "blue": "blue_points",
    }
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
    # Crop's 4 keys are also non-flat (nested under one "crop" key, same
    # reasoning as tone_curve/hsl/color_grading above), but unlike those,
    # its identity/"no crop" default is the full-frame rectangle, not all
    # zeros -- see docs/planning/implementation-notes/
    # 2026-10-13-crop-processor.md section 4.
    _CROP_DEFAULTS = {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    # Geometry's 6 keys are flat floats, same as texture/dehaze/etc., and
    # ARE part of the top-level get_adjustment_state()/_ADJUSTMENT_DEFAULTS
    # contract (unlike crop/mask/heal_spots, no separate nested key) --
    # but "scale"'s own identity value is 100.0, not 0.0, so this subset
    # is pulled out here for the several spots that need to check "is
    # geometry at its identity" without assuming every key defaults to
    # zero. See docs/planning/implementation-notes/
    # 2026-10-13-geometry-processor.md section 2.
    _GEOMETRY_DEFAULTS = {
        "distortion": 0.0,
        "vertical": 0.0,
        "horizontal": 0.0,
        "scale": 100.0,
        "offset_x": 0.0,
        "offset_y": 0.0,
    }
    # The mask's one slot (state key "mask") has no meaningful "neutral"
    # geometry the way crop's full-frame rectangle is a real, applyable
    # identity -- there is no gradient/ellipse that is simultaneously
    # valid and a no-op. So, unlike crop, "no mask" is represented
    # externally as None, not an empty-but-complete dict -- see
    # docs/planning/implementation-notes/2026-10-13-mask-processor.md.
    # Internally, self._mask_params still follows crop's own {}-sentinel
    # convention (see __init__ below); only the externally-visible
    # get_adjustment_state()["mask"] / on_mask_changed(mask) contract uses
    # None.
    _MASK_LINEAR_DEFAULTS = {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    _MASK_RADIAL_DEFAULTS = {
        "cx": 0.5,
        "cy": 0.5,
        "rx": 0.25,
        "ry": 0.25,
        "feather": 0.5,
    }
    # The one, small, fixed local-adjustment subset a mask supports (see
    # docs/planning/implementation-notes/2026-10-13-mask-processor.md for
    # the full list of deferred parameters). Ranges match each
    # underlying processor's own real valid range.
    _MASK_ADJUSTMENT_RANGES = {
        "exposure": (-5.0, 5.0),
        "contrast": (-100.0, 100.0),
        "saturation": (-100.0, 100.0),
        "clarity": (-100.0, 100.0),
    }
    _MASK_TYPES = ("linear", "radial")
    # Healing's spots are a LIST (state key "heal_spots"), not a dict --
    # unlike every other key so far, multi-spot healing is naturally a
    # list of independent spots rather than a single slot. "[]" is the
    # meaningful, falsy "no spots" default, following the same
    # falsy-skip convention every other processor in this codebase
    # already uses. See docs/planning/implementation-notes/
    # 2026-10-13-healing-processor.md.
    _HEALING_MODES = ("heal", "clone")
    _HEALING_SPOT_DEFAULTS = {
        "dst_x": 0.5,
        "dst_y": 0.5,
        "src_x": 0.5,
        "src_y": 0.5,
        "radius": 0.05,
        "feather": 0.3,
        "opacity": 1.0,
    }

    def __init__(
        self,
        image_view: ImageView,
        image_model: Optional[ImageModel] = None,
        image_service: Optional[ImageService] = None,
        history_service: Optional[HistoryService] = None,
        settings_service: Optional[SettingsService] = None,
        use_threading: bool = True,
        worker_factory=None,
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
            worker_factory: Optional ``(**proxy_kwargs) -> ProcessingWorker``
                used instead of ``ProcessingWorker``. Tests pass an inline
                worker so the production (threaded) code path runs
                deterministically without threads.
        """
        super().__init__()
        
        self._image_view = image_view
        self._image_model = image_model or ImageModel()
        self._image_service = image_service or ImageService()
        self._history_service = history_service or HistoryService()
        self._settings_service = settings_service
        self._use_threading = use_threading
        self._worker_factory = worker_factory or ProcessingWorker
        
        # Processors (for synchronous fallback / export)
        self._exposure_processor = ExposureProcessor()
        self._tonal_processor = TonalProcessor()
        self._curve_processor = CurveProcessor()
        self._wb_processor = WhiteBalanceProcessor()
        self._color_processor = ColorProcessor()
        self._hsl_processor = HslMixerProcessor()
        self._color_grading_processor = ColorGradingProcessor()
        self._texture_processor = TextureProcessor()
        self._clarity_processor = ClarityProcessor()
        self._dehaze_processor = DehazeProcessor()
        self._vignette_processor = VignetteProcessor()
        self._grain_processor = GrainProcessor()
        self._sharpening_processor = SharpeningProcessor()
        self._luminance_nr_processor = LuminanceNoiseReductionProcessor()
        self._color_nr_processor = ColorNoiseReductionProcessor()
        self._remove_ca_processor = RemoveChromaticAberrationProcessor()
        self._defringe_processor = DefringeProcessor()
        self._geometry_processor = GeometryProcessor()
        self._straighten_processor = StraightenProcessor()
        self._crop_processor = CropProcessor()
        self._mask_processor = MaskProcessor()
        self._healing_processor = HealingProcessor()

        # Current adjustment values
        self._exposure_params: Dict[str, float] = {}
        self._tonal_params: Dict[str, float] = {}
        self._color_params: Dict[str, float] = {}
        self._curve_params: Dict[str, Any] = {}
        self._wb_params: Dict[str, float] = {}
        self._hsl_params: Dict[str, float] = {}
        self._color_grading_params: Dict[str, float] = {}
        self._texture_params: Dict[str, float] = {}
        self._clarity_params: Dict[str, float] = {}
        self._dehaze_params: Dict[str, float] = {}
        self._vignette_params: Dict[str, float] = {}
        self._grain_params: Dict[str, float] = {}
        self._sharpening_params: Dict[str, float] = {}
        self._luminance_nr_params: Dict[str, float] = {}
        self._color_nr_params: Dict[str, float] = {}
        self._remove_ca_params: Dict[str, float] = {}
        self._defringe_params: Dict[str, float] = {}
        self._geometry_params: Dict[str, float] = {}
        self._straighten_params: Dict[str, float] = {}
        # Unlike every other _xxx_params field, Crop's natural "no crop"
        # default ({"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}, the full
        # frame) is a non-empty dict, so it cannot double as its own
        # falsy "not yet touched" sentinel the way the other fields'
        # all-zero defaults do. _crop_params is therefore kept at {}
        # (falsy, matching the skip-if-empty convention used everywhere
        # else) whenever there is no actual crop, and only populated
        # with the real {"x0": ..., ...} values when a non-identity crop
        # is set -- see docs/planning/implementation-notes/
        # 2026-10-13-crop-processor.md section 4.
        self._crop_params: Dict[str, float] = {}
        # Mask's single slot follows the exact same internal falsy/{}
        # "not yet touched" sentinel convention as _crop_params (see
        # above) -- {} means "no mask", a populated dict means an active
        # one. Unlike crop, this needs no identity-collapsing step: the
        # normalizer itself (_normalize_mask_state) returns {} directly
        # for "no mask" (None, or an unrecognized/missing "type"), since
        # there is no other "neutral" mask geometry to collapse from. See
        # docs/planning/implementation-notes/2026-10-13-mask-processor.md.
        self._mask_params: Dict[str, Any] = {}
        # Healing follows the exact same internal falsy/{} "not yet
        # touched" sentinel convention as _mask_params above, but wraps
        # its list value in a single-key dict ({"heal_spots": [...]}),
        # mirroring tone curve's own {"points": [...]} wrapping
        # convention (both are the one non-scalar-float VALUE kept
        # inside an otherwise-scalar _xxx_params dict) rather than
        # storing the bare list directly -- this is also exactly the
        # shape HealingProcessor.process's own ``heal_spots`` kwarg
        # expects when the dict is spread with **self._healing_params.
        self._healing_params: Dict[str, Any] = {}

        # Background processing
        self._processing_worker: Optional[ProcessingWorker] = None
        self._final_processing_worker: Optional[ProcessingWorker] = None
        self._debouncer: Optional[ThrottledDebouncer] = None
        self._latest_request_id: int = -1
        self._latest_presented_preview_id: int = -1
        self._latest_load_request_id: int = -1
        self._pending_final_request_id: int = -1
        self._pending_history_previous_image = None
        self._pending_history_previous_state: Optional[Dict[str, Any]] = None
        self._load_parent_widget: Optional[QWidget] = None
        self._load_threads: list[QThread] = []
        self._load_workers: list[_ImageLoadWorker] = []
        self._skip_intermediate_preview_request_ids: set[int] = set()
        self._pending_preview: Optional[tuple[int, DisplayFrame]] = None
        self._preview_present_timer = QTimer(self)
        self._preview_present_timer.setSingleShot(True)
        self._preview_present_timer.setInterval(16)  # Cap UI presents ~60 FPS
        self._preview_present_timer.timeout.connect(self._present_pending_preview)
        # Full-resolution renders are only for detail: they run when the
        # view is zoomed past what the quality preview can show, shortly
        # after the user stops interacting. History never waits on them.
        self._final_render_timer = QTimer(self)
        self._final_render_timer.setSingleShot(True)
        self._final_render_timer.setInterval(400)
        self._final_render_timer.timeout.connect(self._submit_delayed_final_render)
        # Requests whose frames are display-only (uncommitted tool previews,
        # e.g. a mask mid-drag) must not replace image_model.current_image.
        self._display_only_request_ids: set[int] = set()
        # Mask/heal/crop previews: cheap interactive frames while the tool
        # is being dragged, one quality frame once it settles.
        self._pending_tool_overrides: Optional[Dict[str, Any]] = None
        self._tool_preview_timer = QTimer(self)
        self._tool_preview_timer.setSingleShot(True)
        self._tool_preview_timer.setInterval(120)
        self._tool_preview_timer.timeout.connect(self._submit_tool_quality_preview)
        self._image_view.zoom_changed.connect(self._on_view_zoom_changed)

        if use_threading:
            self._setup_async_processing()
        
        # Connect signals
        self._connect_signals()

    def _setup_async_processing(self) -> None:
        """Set up asynchronous processing components.

        When a ``SettingsService`` is present and has stored proxy-size
        preferences (see Preferences > Performance), they are passed to
        both proxy-generating workers here, at construction time. This is
        NOT live-reloaded: changing the preference while PhotoEdit is
        running has no effect on the already-running workers (invalidating
        in-flight caches/proxy state is out of scope for this slice) --
        the new size takes effect on the next app launch. See
        docs/planning/implementation-notes/2026-10-13-preferences-ui.md.
        """
        proxy_max_size = None
        interactive_proxy_max_size = None
        if self._settings_service is not None:
            proxy_max_size = self._settings_service.get_proxy_max_size()
            interactive_proxy_max_size = (
                self._settings_service.get_interactive_proxy_max_size()
            )

        # Create and start processing worker
        self._processing_worker = self._worker_factory(
            proxy_max_size=proxy_max_size,
            interactive_proxy_max_size=interactive_proxy_max_size,
        )
        self._processing_worker.preview_ready.connect(self._on_preview_ready)
        self._processing_worker.error_occurred.connect(self._on_processing_error)
        self._final_processing_worker = self._worker_factory(
            proxy_max_size=proxy_max_size,
            interactive_proxy_max_size=interactive_proxy_max_size,
        )
        self._final_processing_worker.final_frame_ready.connect(
            self._on_processing_complete
        )
        self._final_processing_worker.error_occurred.connect(
            self._on_processing_error
        )
        # Images reach the workers through ProcessingWorker.set_image, which
        # defers proxy generation to the worker thread. (A queued signal to
        # the worker ran it on the UI thread instead: the worker thread's
        # event loop is never spun while _run() loops.)
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
        # Timers would otherwise fire into an already-destroyed view.
        self._final_render_timer.stop()
        self._tool_preview_timer.stop()
        self._preview_present_timer.stop()
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

    def clear_image(self) -> None:
        """Reset to the "no image loaded" state.

        Used when the currently-open image's library entry is removed
        or deleted from disk (see ``MainWindow._on_remove_entry_requested``/
        ``_on_remove_entries_requested``) -- there is no sensible image
        left to keep showing once its own catalog entry (and, for
        "Delete from Disk", the file itself) is gone. Rather than
        inventing a new empty-state UI, this reuses the exact state the
        app is already in right after startup with an empty library,
        before any ``load_image``/``load_image_async`` call has ever
        been made: ``ImageModel.clear()`` resets ``image_model`` to its
        pre-load defaults and ``ImageView.clear()`` resets the canvas to
        its own default "No image loaded" placeholder. Also clears
        undo/redo history, since there is no image left for it to apply
        to -- mirrors ``_apply_loaded_image``'s own history-clearing on
        every image switch. See
        docs/planning/implementation-notes/2026-10-13-remove-delete-photo.md.
        """
        self._image_model.clear()
        self._image_view.clear()
        self._history_service.clear_history()

    def _apply_loaded_image(
        self, file_path: str, image, frame: Optional[DisplayFrame] = None
    ) -> None:
        """Apply a decoded image to model/view state on the UI thread.

        ``frame`` is the display conversion the load thread already made;
        when present the UI thread only wraps it in a pixmap.
        """
        self._image_model.file_path = file_path
        self._image_model.set_original_image(image)
        if frame is not None:
            self._image_view.set_display_frame(
                frame, emit_loaded=True, preserve_view_scale=False
            )
        else:
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
        self._texture_params = {}
        self._clarity_params = {}
        self._dehaze_params = {}
        self._vignette_params = {}
        self._grain_params = {}
        self._sharpening_params = {}
        self._luminance_nr_params = {}
        self._color_nr_params = {}
        self._remove_ca_params = {}
        self._defringe_params = {}
        self._geometry_params = {}
        self._straighten_params = {}
        self._crop_params = {}
        self._mask_params = {}
        self._healing_params = {}
        self._pending_final_request_id = -1
        self._pending_history_previous_image = None
        self._pending_history_previous_state = None
        self._final_render_timer.stop()

        # Hand the image to both workers. set_image only queues it; proxy
        # generation runs on each worker thread before its next request.
        for worker in (self._processing_worker, self._final_processing_worker):
            if worker is not None and hasattr(worker, "set_image"):
                worker.set_image(image)

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
        frame = None
        if isinstance(image, LoadedImage):
            image, frame = image.image, image.frame
        self._apply_loaded_image(file_path, image, frame)
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

    def get_export_image(
        self,
        apply_crop: bool = True,
        mask_override: Any = _UNSET,
        heal_spots_override: Any = _UNSET,
    ):
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

        Args:
            apply_crop: When False, skips the final ``CropProcessor`` call,
                returning the full, uncropped-but-otherwise-fully-adjusted
                image. Used by the interactive crop overlay (slice 2 of the
                Crop tool), which needs to display the full frame under the
                drag handles even when a crop was previously committed, so
                the user can see and adjust the whole image while editing.
                Defaults to True, matching every existing call site.
            mask_override: When passed (including explicitly ``{}``/``None``
                for "no mask"), used IN PLACE OF ``self._mask_params`` for
                this one recompute only -- ``self._mask_params`` itself is
                left completely untouched. This is what lets
                :meth:`preview_mask` show an in-progress, uncommitted mask
                candidate (geometry mid-drag, a slider mid-tick) without
                mutating any committed engine state or touching history.
                Left at the private ``_UNSET`` sentinel by every other call
                site, which keeps today's "use whatever mask is actually
                committed" behavior.
            heal_spots_override: Mirrors ``mask_override``'s exact pattern,
                for the healing tool UI's own live-preview mechanism
                (:meth:`preview_heal_spots`). When passed (including
                explicitly ``[]``), a LIST of heal-spot dicts used IN
                PLACE OF ``self._healing_params`` for this one recompute
                only -- ``self._healing_params`` itself is left completely
                untouched. Left at the private ``_UNSET`` sentinel by
                every other call site. See docs/planning/
                implementation-notes/2026-10-13-healing-tool-ui.md.

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
        # Healing runs FIRST, before every other adjustment (including
        # Exposure) -- it is a repair operation on the as-shot pixels, not
        # a creative adjustment. See docs/planning/implementation-notes/
        # 2026-10-13-healing-processor.md.
        healing_params = (
            self._healing_params
            if heal_spots_override is _UNSET
            else ({"heal_spots": heal_spots_override} if heal_spots_override else {})
        )
        if healing_params:
            result = self._healing_processor.process(result, **healing_params)
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
        if self._texture_params:
            result = self._texture_processor.process(result, **self._texture_params)
        if self._clarity_params:
            result = self._clarity_processor.process(result, **self._clarity_params)
        if self._dehaze_params:
            result = self._dehaze_processor.process(result, **self._dehaze_params)
        if self._vignette_params:
            result = self._vignette_processor.process(result, **self._vignette_params)
        if self._grain_params:
            result = self._grain_processor.process(result, **self._grain_params)
        if self._sharpening_params:
            result = self._sharpening_processor.process(
                result, **self._sharpening_params
            )
        if self._luminance_nr_params:
            result = self._luminance_nr_processor.process(
                result, **self._luminance_nr_params
            )
        if self._color_nr_params:
            result = self._color_nr_processor.process(
                result, **self._color_nr_params
            )
        if self._remove_ca_params:
            result = self._remove_ca_processor.process(
                result, **self._remove_ca_params
            )
        if self._defringe_params:
            result = self._defringe_processor.process(
                result, **self._defringe_params
            )
        # Geometry (Distortion/Vertical/Horizontal/Scale/Offset) runs
        # immediately BEFORE Straighten -- it corrects as-shot lens/
        # perspective distortion, which should be undone before the
        # user's own final small-angle Straighten tweak is applied on
        # top of the now-rectified frame. See docs/planning/
        # implementation-notes/2026-10-13-geometry-processor.md section 2.
        if self._geometry_params:
            result = self._geometry_processor.process(
                result, **self._geometry_params
            )
        if self._straighten_params:
            result = self._straighten_processor.process(
                result, **self._straighten_params
            )
        # Mask is applied after every other adjustment (including
        # Straighten) and strictly BEFORE Crop -- it blends pixel values
        # only, never changes shape, so its geometry is always expressed
        # in the full, pre-crop frame's own normalized coordinates. See
        # docs/planning/implementation-notes/2026-10-13-mask-processor.md.
        mask_params = self._mask_params if mask_override is _UNSET else mask_override
        if mask_params:
            result = self._mask_processor.process(result, mask=mask_params)
        # Crop is applied strictly LAST, after every other processor
        # (including Straighten and Mask) -- see CropProcessor's module
        # docstring and docs/planning/implementation-notes/
        # 2026-10-13-crop-processor.md section 1 for why.
        if apply_crop and self._crop_params:
            result = self._crop_processor.process(result, **self._crop_params)
        return result

    def start_export_render(self, post=None, apply_crop: bool = True):
        """Start a full-resolution render of the current edit on a
        background thread and return its ``BackgroundTask`` (or None
        without an image).

        The edit is snapshotted now, so later slider moves don't change
        what gets exported. Produces the same pixels as
        :meth:`get_export_image`, without blocking the UI thread.
        """
        original = self._image_model.get_original_image()
        if not self.has_image() or original is None:
            return None
        return start_export_render(
            original, self._render_kwargs(), apply_crop=apply_crop, post=post,
            parent=self,
        )

    def refresh_view(self) -> None:
        """Show the committed adjustment state.

        With background processing this asks the worker for a quality
        render (usually a preview-cache hit) instead of converting a
        full-size float image on the UI thread.
        """
        if self._renders_async() and self.has_image():
            self._tool_preview_timer.stop()
            self._pending_tool_overrides = None
            self._request_render(interactive=False)
            self._schedule_detail_render()
            return
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

        Includes four non-flat keys alongside the flat float keys:
        ``"tone_curve"`` (a JSON-plain list of ``[x, y]`` control points --
        see docs/planning/implementation-notes/2026-09-29-tone-curve.md
        section 4; joined by ``"tone_curve_red"``/``"tone_curve_green"``/
        ``"tone_curve_blue"``, the same JSON-plain shape, one per
        per-channel curve -- see docs/planning/implementation-notes/
        2026-10-13-per-channel-curves.md section 4), ``"hsl"`` (a flat
        24-key dict for the Color Mixer --
        see docs/planning/implementation-notes/2026-09-30-hsl-color-mixer.md
        section 4), ``"color_grading"`` (a flat 11-key dict -- see
        docs/planning/implementation-notes/2026-09-30-color-grading.md
        section 4), and ``"crop"`` (a 4-key ``{"x0", "y0", "x1", "y1"}``
        dict of normalized fractions, defaulting to the full-frame
        rectangle -- see docs/planning/implementation-notes/
        2026-10-13-crop-processor.md section 4), and ``"mask"`` (the
        single active local-adjustment mask -- ``None`` when absent, or
        a dict shaped per
        docs/planning/implementation-notes/2026-10-13-mask-processor.md
        section 4; unlike every other non-flat key, its "no mask"
        default is ``None``, not an empty/identity dict, since there is
        no neutral mask geometry), and ``"heal_spots"`` (a list of
        independent clone/heal spot dicts, ``[]`` by default -- see
        docs/planning/implementation-notes/2026-10-13-healing-processor.md
        section 4; always a list, never ``None``, following the same
        falsy-skip convention every other processor uses).
        """
        state: Dict[str, Any] = self._ADJUSTMENT_DEFAULTS.copy()
        state.update(self._exposure_params)
        state.update(self._tonal_params)
        state.update(self._wb_params)
        state.update(self._color_params)
        curve_points = self._curve_params.get("points", self._CURVE_DEFAULT_POINTS)
        state["tone_curve"] = [list(point) for point in curve_points]
        red_curve_points = self._curve_params.get(
            "red_points", self._CURVE_DEFAULT_POINTS
        )
        state["tone_curve_red"] = [list(point) for point in red_curve_points]
        green_curve_points = self._curve_params.get(
            "green_points", self._CURVE_DEFAULT_POINTS
        )
        state["tone_curve_green"] = [list(point) for point in green_curve_points]
        blue_curve_points = self._curve_params.get(
            "blue_points", self._CURVE_DEFAULT_POINTS
        )
        state["tone_curve_blue"] = [list(point) for point in blue_curve_points]
        state["hsl"] = {**self._HSL_DEFAULTS, **self._hsl_params}
        state["color_grading"] = {
            **self._COLOR_GRADING_DEFAULTS,
            **self._color_grading_params,
        }
        state.update(self._texture_params)
        state.update(self._clarity_params)
        state.update(self._dehaze_params)
        state.update(self._vignette_params)
        state.update(self._grain_params)
        state.update(self._sharpening_params)
        state.update(self._luminance_nr_params)
        state.update(self._color_nr_params)
        state.update(self._remove_ca_params)
        state.update(self._defringe_params)
        state.update(self._geometry_params)
        state.update(self._straighten_params)
        state["crop"] = {**self._CROP_DEFAULTS, **self._crop_params}
        state["mask"] = self._mask_params.copy() if self._mask_params else None
        state["heal_spots"] = [
            dict(spot) for spot in self._healing_params.get("heal_spots", [])
        ]
        return state

    def _apply_state_params(
        self, adjustments: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Set every internal ``_xxx_params`` field from a full
        adjustment-state dict (the same shape ``get_adjustment_state()``
        returns), normalizing defensively.

        Pure bookkeeping -- does not touch ``image_model``, history, or
        pending processing state; callers (``restore_adjustment_state`` and
        ``apply_history_state``) handle those themselves, since their needs
        differ.

        Returns:
            A dict with the normalized pieces actually applied --
            ``"normalized"`` (the flat float dict), ``"curve_points"``,
            ``"hsl_values"``, ``"color_grading_values"``, ``"crop_values"``
            and ``"mask_values"`` -- so callers that need to reason about
            "are there any non-default changes" (as
            ``restore_adjustment_state`` does) don't have to recompute them.
        """
        normalized = self._normalize_adjustment_state(adjustments)
        curve_points = normalize_points(
            adjustments.get("tone_curve") if adjustments else None
        )
        red_curve_points = normalize_points(
            adjustments.get("tone_curve_red") if adjustments else None
        )
        green_curve_points = normalize_points(
            adjustments.get("tone_curve_green") if adjustments else None
        )
        blue_curve_points = normalize_points(
            adjustments.get("tone_curve_blue") if adjustments else None
        )
        hsl_values = self._normalize_hsl_state(
            adjustments.get("hsl") if adjustments else None
        )
        color_grading_values = self._normalize_color_grading_state(
            adjustments.get("color_grading") if adjustments else None
        )
        crop_values = self._normalize_crop_state(
            adjustments.get("crop") if adjustments else None
        )
        mask_values = self._normalize_mask_state(
            adjustments.get("mask") if adjustments else None
        )
        heal_spots_values = self._normalize_heal_spots_state(
            adjustments.get("heal_spots") if adjustments else None
        )

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
        curve_params: Dict[str, Any] = {}
        if not is_identity_curve(curve_points):
            curve_params["points"] = curve_points
        if not is_identity_curve(red_curve_points):
            curve_params["red_points"] = red_curve_points
        if not is_identity_curve(green_curve_points):
            curve_params["green_points"] = green_curve_points
        if not is_identity_curve(blue_curve_points):
            curve_params["blue_points"] = blue_curve_points
        self._curve_params = curve_params
        self._hsl_params = hsl_values
        self._color_grading_params = color_grading_values
        self._texture_params = {"texture": normalized["texture"]}
        self._clarity_params = {"clarity": normalized["clarity"]}
        self._dehaze_params = {"dehaze": normalized["dehaze"]}
        self._vignette_params = {"vignette": normalized["vignette"]}
        self._grain_params = {"grain": normalized["grain"]}
        self._sharpening_params = {"sharpening": normalized["sharpening"]}
        self._luminance_nr_params = {"luminance_nr": normalized["luminance_nr"]}
        self._color_nr_params = {"color_nr": normalized["color_nr"]}
        self._remove_ca_params = {"remove_ca": normalized["remove_ca"]}
        self._defringe_params = {"defringe": normalized["defringe"]}
        self._geometry_params = {
            "distortion": normalized["distortion"],
            "vertical": normalized["vertical"],
            "horizontal": normalized["horizontal"],
            "scale": normalized["scale"],
            "offset_x": normalized["offset_x"],
            "offset_y": normalized["offset_y"],
        }
        self._straighten_params = {"straighten": normalized["straighten"]}
        self._crop_params = (
            {} if self._is_identity_crop(crop_values) else crop_values
        )
        self._mask_params = mask_values
        self._healing_params = (
            {"heal_spots": heal_spots_values} if heal_spots_values else {}
        )

        return {
            "normalized": normalized,
            "curve_points": curve_points,
            "red_curve_points": red_curve_points,
            "green_curve_points": green_curve_points,
            "blue_curve_points": blue_curve_points,
            "hsl_values": hsl_values,
            "color_grading_values": color_grading_values,
            "crop_values": crop_values,
            "mask_values": mask_values,
            "heal_spots_values": heal_spots_values,
        }

    def restore_adjustment_state(self, adjustments: Optional[Dict[str, Any]]) -> None:
        """Apply a saved adjustment payload without creating undo history."""
        self._history_service.clear_history()
        self._pending_history_previous_image = None
        self._pending_history_previous_state = None
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

        applied = self._apply_state_params(adjustments)
        normalized = applied["normalized"]
        curve_points = applied["curve_points"]
        red_curve_points = applied["red_curve_points"]
        green_curve_points = applied["green_curve_points"]
        blue_curve_points = applied["blue_curve_points"]
        hsl_values = applied["hsl_values"]
        color_grading_values = applied["color_grading_values"]
        crop_values = applied["crop_values"]
        mask_values = applied["mask_values"]
        heal_spots_values = applied["heal_spots_values"]

        if not self.has_image():
            return

        if self._renders_async():
            # Render in the background; the synchronous full-size render
            # below froze the window for seconds on every photo switch.
            self._image_model.reset_to_original()
            self.refresh_view()
            return

        has_changes = (
            # Compared against each key's own default (not a bare 0.0)
            # because "scale" (Geometry) defaults to 100.0, not 0.0 --
            # see docs/planning/implementation-notes/
            # 2026-10-13-geometry-processor.md section 2.
            any(
                normalized[key] != default
                for key, default in self._ADJUSTMENT_DEFAULTS.items()
            )
            or not is_identity_curve(curve_points)
            or not is_identity_curve(red_curve_points)
            or not is_identity_curve(green_curve_points)
            or not is_identity_curve(blue_curve_points)
            or any(value != 0.0 for value in hsl_values.values())
            or any(
                color_grading_values.get(key, 0.0) != default
                for key, default in self._COLOR_GRADING_DEFAULTS.items()
            )
            or not self._is_identity_crop(crop_values)
            or bool(mask_values)
            or bool(heal_spots_values)
        )
        if not has_changes:
            self._image_model.reset_to_original()
            self.refresh_view()
            return

        original = self._image_model.get_original_image()
        if original is None:
            return

        result = original.copy()
        if self._healing_params:
            result = self._healing_processor.process(result, **self._healing_params)
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
        result = self._texture_processor.process(result, **self._texture_params)
        result = self._clarity_processor.process(result, **self._clarity_params)
        result = self._dehaze_processor.process(result, **self._dehaze_params)
        result = self._vignette_processor.process(result, **self._vignette_params)
        result = self._grain_processor.process(result, **self._grain_params)
        result = self._sharpening_processor.process(
            result, **self._sharpening_params
        )
        result = self._luminance_nr_processor.process(
            result, **self._luminance_nr_params
        )
        result = self._color_nr_processor.process(
            result, **self._color_nr_params
        )
        result = self._remove_ca_processor.process(
            result, **self._remove_ca_params
        )
        result = self._defringe_processor.process(
            result, **self._defringe_params
        )
        result = self._geometry_processor.process(
            result, **self._geometry_params
        )
        result = self._straighten_processor.process(
            result, **self._straighten_params
        )
        if self._mask_params:
            result = self._mask_processor.process(result, mask=self._mask_params)
        if self._crop_params:
            result = self._crop_processor.process(result, **self._crop_params)
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
        self._texture_params = {}
        self._clarity_params = {}
        self._dehaze_params = {}
        self._vignette_params = {}
        self._grain_params = {}
        self._sharpening_params = {}
        self._luminance_nr_params = {}
        self._color_nr_params = {}
        self._remove_ca_params = {}
        self._defringe_params = {}
        self._geometry_params = {}
        self._straighten_params = {}
        self._crop_params = {}
        self._mask_params = {}
        self._healing_params = {}
        self._pending_final_request_id = -1
        self._pending_history_previous_image = None
        self._pending_history_previous_state = None
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

    def apply_history_state(self, image, state: Dict[str, Any]) -> None:
        """Re-apply a full (image, adjustment-state) snapshot during
        undo/redo (and on an ordinary adjustment commit, via the same
        ``AdjustmentStateCommand``).

        Unlike :meth:`restore_adjustment_state` (used for switching images,
        Paste Edit Settings, Profile apply, preset import -- all of which
        clear history and may recompute from the original image), this
        method keeps history intact, reuses an ALREADY-RENDERED image
        buffer (no reprocessing -- undo/redo must stay cheap), and is the
        only place that emits :attr:`adjustment_state_restored` so the UI
        and persisted catalog state resync.

        Deliberately does not call :meth:`refresh_view` itself: ``undo()``/
        ``redo()`` above already repaint the canvas once the command has
        run, and the normal (non-undo) commit path that also calls this
        method via ``AdjustmentStateCommand.execute()`` relies on there
        being no extra repaint here (see
        ``_commit_rendered_adjustment``/``_on_processing_complete``, and the
        "pending final render does not refresh full-res view" test). A
        caller that needs the view repainted immediately must call
        :meth:`refresh_view` itself afterward.

        Intended to be called ONLY by ``AdjustmentStateCommand``'s
        ``execute()``/``undo()`` (src/commands/adjustment_commands.py) --
        it is not part of the normal live-editing flow, which is why it is
        not prefixed with an underscore despite being an internal API: a
        different module needs to call it.
        """
        if image is not None:
            self._image_model.current_image = image
        self._apply_state_params(state)
        self.adjustment_state_restored.emit(self.get_adjustment_state())

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

    def _capture_pending_history_state(self) -> None:
        """Snapshot the image + full adjustment state at the start of an
        edit gesture, once, so undo/redo can restore both atomically later.

        Called from every entry point that begins a new edit gesture
        (``apply_adjustments``, ``on_adjustments_changed``,
        ``on_curve_changed``, ``on_hsl_changed``,
        ``on_color_grading_changed``) -- always BEFORE that method's own
        param-storing code runs, so ``get_adjustment_state()`` here
        reflects the state as it was immediately before this gesture.
        """
        if self._pending_history_previous_image is None:
            current = self._image_model.get_current_image()
            if current is not None:
                # LinearImage instances are treated as immutable in the
                # pipeline. Keep the reference instead of copying a full-res
                # buffer on the UI thread.
                self._pending_history_previous_image = current
                self._pending_history_previous_state = self.get_adjustment_state()

    def apply_adjustments(
        self,
        exposure_params: Dict[str, float] = None,
        tonal_params: Dict[str, float] = None,
        color_params: Dict[str, float] = None,
        curve_params: Dict[str, Any] = None,
        wb_params: Dict[str, float] = None,
        hsl_params: Dict[str, float] = None,
        color_grading_params: Dict[str, float] = None,
        texture_params: Dict[str, float] = None,
        clarity_params: Dict[str, float] = None,
        dehaze_params: Dict[str, float] = None,
        vignette_params: Dict[str, float] = None,
        grain_params: Dict[str, float] = None,
        sharpening_params: Dict[str, float] = None,
        luminance_nr_params: Dict[str, float] = None,
        color_nr_params: Dict[str, float] = None,
        remove_ca_params: Dict[str, float] = None,
        defringe_params: Dict[str, float] = None,
        geometry_params: Dict[str, float] = None,
        straighten_params: Dict[str, float] = None,
        crop_params: Dict[str, float] = None,
        mask_params: Dict[str, Any] = None,
        healing_params: Dict[str, Any] = None,
        add_to_history: bool = False
    ) -> None:
        """Apply adjustments to the image (synchronous).

        Args:
            exposure_params: Exposure adjustment parameters
            tonal_params: Highlights/Shadows/Whites/Blacks parameters
            color_params: Color adjustment parameters
            curve_params: Tone curve parameters -- ``{"points": [...]}``
                for the master curve, optionally joined by
                ``"red_points"``/``"green_points"``/``"blue_points"`` for
                the 3 per-channel curves (any channel omitted defaults
                to identity)
            wb_params: White balance (Temperature/Tint) parameters
            hsl_params: HSL Color Mixer parameters (24-key flat dict)
            color_grading_params: Color Grading parameters (11-key flat dict)
            add_to_history: If True, add command to history for undo
        """
        if not self.has_image():
            return

        self._final_render_timer.stop()
        self._pending_final_request_id = -1

        self._capture_pending_history_state()

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
        if texture_params:
            self._texture_params = texture_params
        if clarity_params:
            self._clarity_params = clarity_params
        if dehaze_params:
            self._dehaze_params = dehaze_params
        if vignette_params:
            self._vignette_params = vignette_params
        if grain_params:
            self._grain_params = grain_params
        if sharpening_params:
            self._sharpening_params = sharpening_params
        if luminance_nr_params:
            self._luminance_nr_params = luminance_nr_params
        if color_nr_params:
            self._color_nr_params = color_nr_params
        if remove_ca_params:
            self._remove_ca_params = remove_ca_params
        if defringe_params:
            self._defringe_params = defringe_params
        if geometry_params:
            self._geometry_params = geometry_params
        if straighten_params:
            self._straighten_params = straighten_params
        if crop_params is not None:
            # Like curve_params (and unlike every other _xxx_params
            # field), {} is a legitimate, meaningful value here -- it is
            # Crop's own "identity/no crop" sentinel (see _CROP_DEFAULTS'
            # docstring) -- so the guard checks "is not None", not
            # truthiness, to allow a caller to explicitly reset it.
            self._crop_params = crop_params
        if mask_params is not None:
            # Like crop_params, {} is a legitimate, meaningful value here
            # -- it is mask's own internal "no mask" sentinel (see
            # _MASK_TYPES' usage in _normalize_mask_state) -- so the guard
            # checks "is not None", not truthiness, to allow a caller
            # (including on_mask_changed) to explicitly clear it.
            self._mask_params = mask_params
        if healing_params is not None:
            # Like crop_params/mask_params, {} is a legitimate, meaningful
            # value here -- it is healing's own internal "no spots"
            # sentinel -- so the guard checks "is not None", not
            # truthiness, to allow a caller (including
            # on_heal_spots_changed) to explicitly clear it.
            self._healing_params = healing_params

        if self._use_threading and self._processing_worker is not None:
            self._pending_final_request_id = -1
            if add_to_history:
                # A discrete edit (crop/mask/heal Apply, a preset): show the
                # quality preview and record a settings-only undo step now.
                self._tool_preview_timer.stop()
                self._pending_tool_overrides = None
                self._request_render(interactive=False)
                self._commit_pending_history()
                self._schedule_detail_render()
            else:
                self._request_render(interactive=True)
            return

        if add_to_history:
            # Reuse CombinedAdjustmentCommand's existing pixel-computation
            # chain to compute the new image, but run it directly (NOT via
            # history_service.execute_command) so it never itself lands on
            # the undo/redo stack -- only the state-aware
            # AdjustmentStateCommand built below does. This avoids
            # double-computing pixels (the expensive part) while still
            # getting a state-aware command onto the real stack. See
            # docs/planning/implementation-notes/
            # 2026-10-13-state-aware-undo-redo.md.
            command = CombinedAdjustmentCommand(
                self._image_model,
                exposure_params=self._exposure_params,
                tonal_params=self._tonal_params,
                color_params=self._color_params,
                curve_params=self._curve_params,
                wb_params=self._wb_params,
                hsl_params=self._hsl_params,
                color_grading_params=self._color_grading_params,
                texture_params=self._texture_params,
                clarity_params=self._clarity_params,
                dehaze_params=self._dehaze_params,
                vignette_params=self._vignette_params,
                grain_params=self._grain_params,
                sharpening_params=self._sharpening_params,
                luminance_nr_params=self._luminance_nr_params,
                color_nr_params=self._color_nr_params,
                remove_ca_params=self._remove_ca_params,
                defringe_params=self._defringe_params,
                geometry_params=self._geometry_params,
                straighten_params=self._straighten_params,
                crop_params=self._crop_params,
                mask_params=self._mask_params,
                healing_params=self._healing_params,
            )
            command.execute()

            previous_image = self._pending_history_previous_image
            previous_state = self._pending_history_previous_state
            self._pending_history_previous_image = None
            self._pending_history_previous_state = None
            if previous_image is not None and previous_state is not None:
                state_command = AdjustmentStateCommand(
                    controller=self,
                    previous_image=previous_image,
                    previous_state=previous_state,
                    new_image=self._image_model.current_image,
                    new_state=self.get_adjustment_state(),
                )
                self._history_service.execute_command(state_command)
        else:
            # Apply directly without history (for live preview)
            original = self._image_model.get_original_image()
            if original is None:
                return

            result = original.copy()

            # Healing runs FIRST, before every other adjustment -- see
            # docs/planning/implementation-notes/
            # 2026-10-13-healing-processor.md.
            if self._healing_params:
                result = self._healing_processor.process(
                    result, **self._healing_params
                )

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
            if self._texture_params:
                result = self._texture_processor.process(result, **self._texture_params)

            if self._clarity_params:
                result = self._clarity_processor.process(result, **self._clarity_params)

            if self._dehaze_params:
                result = self._dehaze_processor.process(result, **self._dehaze_params)

            if self._vignette_params:
                result = self._vignette_processor.process(result, **self._vignette_params)

            if self._grain_params:
                result = self._grain_processor.process(result, **self._grain_params)

            if self._sharpening_params:
                result = self._sharpening_processor.process(
                    result, **self._sharpening_params
                )

            if self._luminance_nr_params:
                result = self._luminance_nr_processor.process(
                    result, **self._luminance_nr_params
                )

            if self._color_nr_params:
                result = self._color_nr_processor.process(
                    result, **self._color_nr_params
                )

            if self._remove_ca_params:
                result = self._remove_ca_processor.process(
                    result, **self._remove_ca_params
                )

            if self._defringe_params:
                result = self._defringe_processor.process(
                    result, **self._defringe_params
                )

            if self._geometry_params:
                result = self._geometry_processor.process(
                    result, **self._geometry_params
                )

            if self._straighten_params:
                result = self._straighten_processor.process(
                    result, **self._straighten_params
                )

            if self._mask_params:
                result = self._mask_processor.process(
                    result, **self._mask_params
                )

            if self._crop_params:
                result = self._crop_processor.process(
                    result, **self._crop_params
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
        self._capture_pending_history_state()

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
        texture_params = {"texture": adjustments.get("texture", 0.0)}
        clarity_params = {"clarity": adjustments.get("clarity", 0.0)}
        dehaze_params = {"dehaze": adjustments.get("dehaze", 0.0)}
        vignette_params = {"vignette": adjustments.get("vignette", 0.0)}
        grain_params = {"grain": adjustments.get("grain", 0.0)}
        sharpening_params = {"sharpening": adjustments.get("sharpening", 0.0)}
        luminance_nr_params = {
            "luminance_nr": adjustments.get("luminance_nr", 0.0)
        }
        color_nr_params = {
            "color_nr": adjustments.get("color_nr", 0.0)
        }
        remove_ca_params = {
            "remove_ca": adjustments.get("remove_ca", 0.0)
        }
        defringe_params = {
            "defringe": adjustments.get("defringe", 0.0)
        }
        geometry_params = {
            "distortion": adjustments.get("distortion", 0.0),
            "vertical": adjustments.get("vertical", 0.0),
            "horizontal": adjustments.get("horizontal", 0.0),
            "scale": adjustments.get("scale", 100.0),
            "offset_x": adjustments.get("offset_x", 0.0),
            "offset_y": adjustments.get("offset_y", 0.0),
        }
        straighten_params = {
            "straighten": adjustments.get("straighten", 0.0)
        }

        # Store params
        self._exposure_params = exposure_params
        self._tonal_params = tonal_params
        self._wb_params = wb_params
        self._color_params = color_params
        self._texture_params = texture_params
        self._clarity_params = clarity_params
        self._dehaze_params = dehaze_params
        self._vignette_params = vignette_params
        self._grain_params = grain_params
        self._sharpening_params = sharpening_params
        self._luminance_nr_params = luminance_nr_params
        self._color_nr_params = color_nr_params
        self._remove_ca_params = remove_ca_params
        self._defringe_params = defringe_params
        self._geometry_params = geometry_params
        self._straighten_params = straighten_params

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
                'texture': self._texture_params,
                'clarity': self._clarity_params,
                'dehaze': self._dehaze_params,
                'vignette': self._vignette_params,
                'grain': self._grain_params,
                'sharpening': self._sharpening_params,
                'luminance_nr': self._luminance_nr_params,
                'color_nr': self._color_nr_params,
                'remove_ca': self._remove_ca_params,
                'defringe': self._defringe_params,
                'geometry': self._geometry_params,
                'straighten': self._straighten_params,
                'crop': self._crop_params,
                'mask': self._mask_params,
                'healing': self._healing_params,
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
                self._texture_params,
                self._clarity_params,
                self._dehaze_params,
                self._vignette_params,
                self._grain_params,
                self._sharpening_params,
                self._luminance_nr_params,
                self._color_nr_params,
                self._remove_ca_params,
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

    def on_curve_changed(self, points: List[Any], channel: str = "master") -> None:
        """Handle tone curve changes from the tools panel.

        Mirrors :meth:`on_adjustments_changed` but for the tone curve,
        which travels on its own signal/parameter (see
        docs/planning/implementation-notes/2026-09-29-tone-curve.md).

        Args:
            points: The changed channel's new control points.
            channel: Which of the 4 curves changed -- ``"master"``
                (default, for backward compatibility with every existing
                caller that only ever edited the one master curve),
                ``"red"``, ``"green"``, or ``"blue"``. Only this one
                channel's entry in ``self._curve_params`` is touched;
                every other channel's curve is left exactly as it was.
                See docs/planning/implementation-notes/
                2026-10-13-per-channel-curves.md section 4.
        """
        if not self.has_image():
            return

        self._capture_pending_history_state()

        self._final_render_timer.stop()
        self._pending_final_request_id = -1
        if self._final_processing_worker is not None and hasattr(
            self._final_processing_worker, "cancel_pending"
        ):
            self._final_processing_worker.cancel_pending()

        normalized_points = normalize_points(points)
        key = self._CURVE_CHANNEL_KEYS.get(channel, "points")
        updated_curve_params = dict(self._curve_params)
        if is_identity_curve(normalized_points):
            updated_curve_params.pop(key, None)
        else:
            updated_curve_params[key] = normalized_points
        self._curve_params = updated_curve_params

        if self._use_threading and self._debouncer is not None:
            self._debouncer.call({
                'exposure': self._exposure_params,
                'tonal': self._tonal_params,
                'color': self._color_params,
                'curve': self._curve_params,
                'wb': self._wb_params,
                'hsl': self._hsl_params,
                'color_grading': self._color_grading_params,
                'texture': self._texture_params,
                'clarity': self._clarity_params,
                'dehaze': self._dehaze_params,
                'vignette': self._vignette_params,
                'grain': self._grain_params,
                'sharpening': self._sharpening_params,
                'luminance_nr': self._luminance_nr_params,
                'color_nr': self._color_nr_params,
                'remove_ca': self._remove_ca_params,
                'defringe': self._defringe_params,
                'geometry': self._geometry_params,
                'straighten': self._straighten_params,
                'crop': self._crop_params,
                'mask': self._mask_params,
                'healing': self._healing_params,
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

        self._capture_pending_history_state()

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
                'texture': self._texture_params,
                'clarity': self._clarity_params,
                'dehaze': self._dehaze_params,
                'vignette': self._vignette_params,
                'grain': self._grain_params,
                'sharpening': self._sharpening_params,
                'luminance_nr': self._luminance_nr_params,
                'color_nr': self._color_nr_params,
                'remove_ca': self._remove_ca_params,
                'defringe': self._defringe_params,
                'geometry': self._geometry_params,
                'straighten': self._straighten_params,
                'crop': self._crop_params,
                'mask': self._mask_params,
                'healing': self._healing_params,
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

        self._capture_pending_history_state()

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
                'texture': self._texture_params,
                'clarity': self._clarity_params,
                'dehaze': self._dehaze_params,
                'vignette': self._vignette_params,
                'grain': self._grain_params,
                'sharpening': self._sharpening_params,
                'luminance_nr': self._luminance_nr_params,
                'color_nr': self._color_nr_params,
                'remove_ca': self._remove_ca_params,
                'defringe': self._defringe_params,
                'geometry': self._geometry_params,
                'straighten': self._straighten_params,
                'crop': self._crop_params,
                'mask': self._mask_params,
                'healing': self._healing_params,
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

    def on_crop_changed(self, crop: Dict[str, float]) -> None:
        """Handle a crop-rectangle change.

        Set programmatically for now -- slice 2 (a later, separate
        change) wires this to interactive drag-handle UI; this method is
        this slice's entire "UI surface" and is meant to be called
        directly, not through any slider/mouse interaction yet. Mirrors
        :meth:`on_curve_changed`/:meth:`on_hsl_changed`'s pattern: it
        captures the pre-gesture state via
        :meth:`_capture_pending_history_state`, normalizes/clamps the
        incoming rectangle the same defensive way
        :class:`~src.processors.crop_processor.CropProcessor` itself
        does (never trusting the caller), and stores the result.

        Unlike a slider drag, a crop change from the later UI slice will
        most likely be a single discrete "Apply" action rather than a
        continuous stream of in-flight values -- there is no interactive
        preview/debounce dance here. The new rectangle is routed
        directly through :meth:`apply_adjustments` with
        ``add_to_history=True``, so it participates fully in the
        state-aware undo/redo system (see
        docs/planning/implementation-notes/
        2026-10-13-state-aware-undo-redo.md) in a single step.
        """
        if not self.has_image():
            return

        self._capture_pending_history_state()

        normalized = self._normalize_crop_state(crop)
        crop_params = {} if self._is_identity_crop(normalized) else normalized

        self.apply_adjustments(crop_params=crop_params, add_to_history=True)

    def on_mask_changed(self, mask: Optional[Dict[str, Any]]) -> None:
        """Set (or clear, with ``None``) the single active local-adjustment
        mask.

        Set programmatically for now -- a later, separate slice wires
        this to interactive drag UI (a draggable gradient line for
        linear, a draggable ellipse for radial, reusing ``CropOverlay``'s
        established coordinate-math approach) plus a small panel of the
        mask's own Exposure/Contrast/Saturation/Clarity sliders. Mirrors
        :meth:`on_crop_changed`'s pattern exactly: captures the
        pre-gesture state via :meth:`_capture_pending_history_state`,
        normalizes/validates the incoming dict defensively (never
        trusting the caller -- the dict may come from an old catalog
        entry, a malformed imported preset, or interactive UI input in
        the later slice), and commits via
        ``apply_adjustments(..., add_to_history=True)`` as a single
        discrete step, participating fully in the state-aware undo/redo
        system (see docs/planning/implementation-notes/
        2026-10-13-state-aware-undo-redo.md).

        Args:
            mask: ``None`` to clear the active mask, or a dict shaped per
                the module-level state contract (see
                docs/planning/implementation-notes/
                2026-10-13-mask-processor.md section 4). An unrecognized
                ``"type"`` (or a missing one) is treated the same as
                ``None``.
        """
        if not self.has_image():
            return

        self._capture_pending_history_state()

        normalized = self._normalize_mask_state(mask)

        self.apply_adjustments(mask_params=normalized, add_to_history=True)

    def on_heal_spots_changed(self, heal_spots: list) -> None:
        """Set the complete list of heal spots (replaces, not appends).

        Set programmatically for now -- a later, separate slice wires
        this to the interactive click-to-heal UI (placing spots with the
        mouse, dragging a second point to pick the source). Mirrors
        :meth:`on_crop_changed`/:meth:`on_mask_changed`'s pattern exactly:
        captures the pre-gesture state via
        :meth:`_capture_pending_history_state`, normalizes/validates
        every spot in the incoming list defensively (never trusting the
        caller -- the list may come from an old catalog entry, a
        malformed imported preset, or interactive UI input in the later
        slice), and commits via ``apply_adjustments(...,
        add_to_history=True)`` as a single discrete step, participating
        fully in the state-aware undo/redo system (see
        docs/planning/implementation-notes/
        2026-10-13-state-aware-undo-redo.md).

        The caller (the later UI slice) is responsible for assembling
        the full list -- e.g. appending a newly-placed spot to the
        existing list (read via ``get_adjustment_state()["heal_spots"]``),
        or removing one -- before calling this. This method always
        REPLACES the whole list; it does not provide add/remove
        primitives of its own.

        Args:
            heal_spots: The complete list of heal-spot dicts (see
                docs/planning/implementation-notes/
                2026-10-13-healing-processor.md section 4 for the shape).
                ``[]`` clears every spot. Malformed entries (a non-dict,
                or an unrecognized/missing ``"mode"``) are skipped rather
                than crashing; every other field is defensively clamped.
        """
        if not self.has_image():
            return

        self._capture_pending_history_state()

        normalized = self._normalize_heal_spots_state(heal_spots)
        healing_params = {"heal_spots": normalized} if normalized else {}

        self.apply_adjustments(healing_params=healing_params, add_to_history=True)

    def preview_mask(self, mask: Optional[Dict[str, Any]]) -> None:
        """Display an in-progress, UNCOMMITTED mask candidate, live.

        This is the mask-tool-UI slice's live-preview mechanism, used
        while a mask's geometry is being dragged or its 4 local-adjustment
        sliders are being moved, BEFORE the user clicks Apply. See
        docs/planning/implementation-notes/2026-10-13-mask-tool-ui.md
        section 3.5 for the full design rationale (reusing
        ``get_export_image``'s own ``mask_override`` parameter rather than
        ``on_mask_changed``/``apply_adjustments``) -- in short:

        - It recomputes a FULL preview image, correctly, via
          ``get_export_image(mask_override=normalized)``, the same
          always-synchronous-and-correct recompute path export already
          uses (unaffected by ``self._use_threading`` or the documented
          gap where the non-threaded ``apply_adjustments`` live-preview
          fallback branch skips the mask processor entirely).
        - It does NOT touch ``self._mask_params`` (the committed mask),
          ``self._image_model.current_image``, or the history stack in
          any way -- a call here can never be mistaken for, or leave a
          stray trace in, a real edit. Calling this any number of times
          (every drag frame, every slider tick) is always safe.
        - It displays the result via ``ImageView.set_image`` directly
          (mirroring ``_enter_crop_mode``'s own use of that call for a
          non-"current adjustment state" preview image).

        Args:
            mask: ``None``, or a (possibly still-rough/mid-drag) mask dict
                shaped per the module-level state contract. Defensively
                normalized/clamped exactly like ``on_mask_changed`` does,
                so a mid-drag geometry value briefly outside ``[0, 1]``
                can never reach the processor un-clamped.
        """
        if not self.has_image():
            return
        normalized = self._normalize_mask_state(mask)
        if self._renders_async():
            # Off the UI thread, on the preview proxy: a synchronous 24 MP
            # render per mouse move made mask dragging unusable.
            self._preview_tool_candidate(mask_params=normalized)
            return
        preview = self.get_export_image(mask_override=normalized)
        if preview is not None:
            self._image_view.set_image(
                preview, emit_loaded=False, preserve_view_scale=True
            )

    def preview_heal_spots(self, heal_spots: list) -> None:
        """Display an in-progress, UNCOMMITTED heal-spot list, live.

        This is the healing-tool-UI slice's live-preview mechanism, used
        while spots are being placed/removed on the overlay, BEFORE the
        user clicks Apply. Mirrors :meth:`preview_mask`'s exact pattern
        and rationale (see docs/planning/implementation-notes/
        2026-10-13-mask-tool-ui.md section 3.5 and
        2026-10-13-healing-tool-ui.md) -- in short:

        - It recomputes a FULL preview image via
          ``get_export_image(heal_spots_override=normalized)``, the same
          always-synchronous-and-correct recompute path export already
          uses (unaffected by ``self._use_threading`` or the documented
          gap where the non-threaded ``apply_adjustments`` live-preview
          fallback branch doesn't reach every processor).
        - It does NOT touch ``self._healing_params`` (the committed heal
          spots), ``self._image_model.current_image``, or the history
          stack in any way -- a call here can never be mistaken for, or
          leave a stray trace in, a real edit. Safe to call any number of
          times (every drag frame).
        - It displays the result via ``ImageView.set_image`` directly,
          exactly like ``preview_mask``.

        Args:
            heal_spots: The in-progress, possibly still mid-drag, list of
                heal-spot dicts. Defensively normalized/clamped via
                :meth:`_normalize_heal_spots_state`, exactly like
                ``on_heal_spots_changed`` does, so a mid-drag value
                briefly outside ``[0, 1]`` can never reach the processor
                un-clamped.
        """
        if not self.has_image():
            return
        normalized = self._normalize_heal_spots_state(heal_spots)
        if self._renders_async():
            self._preview_tool_candidate(
                healing_params={"heal_spots": normalized} if normalized else {}
            )
            return
        preview = self.get_export_image(heal_spots_override=normalized)
        if preview is not None:
            self._image_view.set_image(
                preview, emit_loaded=False, preserve_view_scale=True
            )

    def preview_uncropped(self) -> Optional[tuple[int, int]]:
        """Show the full frame (every adjustment except crop) for crop
        editing, and return its ``(width, height)`` at full resolution.

        With background processing the frame is a quality preview rendered
        off the UI thread; it stays display-only until the crop is applied
        or cancelled (both of which re-render the committed state).
        """
        if not self.has_image():
            return None
        if self._renders_async():
            original = self._image_model.get_original_image()
            self._final_render_timer.stop()
            self._tool_preview_timer.stop()
            self._pending_tool_overrides = {"crop_params": {}}
            self._request_render(interactive=False, display_only=True, crop_params={})
            return original.shape[1], original.shape[0]
        uncropped = self.get_export_image(apply_crop=False)
        if uncropped is None:
            return None
        self._image_view.set_image(
            uncropped, emit_loaded=False, preserve_view_scale=True
        )
        return uncropped.shape[1], uncropped.shape[0]

    # -- Background render requests ---------------------------------------

    def _render_kwargs(self, **overrides: Any) -> Dict[str, Any]:
        """Every committed ``_xxx_params`` dict, keyed by the
        ``ProcessingWorker.submit_request`` argument names, with
        ``overrides`` (same names) replacing individual entries."""
        kwargs: Dict[str, Any] = {
            "exposure_params": self._exposure_params,
            "tonal_params": self._tonal_params,
            "color_params": self._color_params,
            "curve_params": self._curve_params,
            "wb_params": self._wb_params,
            "hsl_params": self._hsl_params,
            "color_grading_params": self._color_grading_params,
            "texture_params": self._texture_params,
            "clarity_params": self._clarity_params,
            "dehaze_params": self._dehaze_params,
            "vignette_params": self._vignette_params,
            "grain_params": self._grain_params,
            "sharpening_params": self._sharpening_params,
            "luminance_nr_params": self._luminance_nr_params,
            "color_nr_params": self._color_nr_params,
            "remove_ca_params": self._remove_ca_params,
            "defringe_params": self._defringe_params,
            "geometry_params": self._geometry_params,
            "straighten_params": self._straighten_params,
            "crop_params": self._crop_params,
            "mask_params": self._mask_params,
            "healing_params": self._healing_params,
        }
        kwargs.update(overrides)
        return kwargs

    def _renders_async(self) -> bool:
        """True when renders go through the background preview worker."""
        return (
            self._use_threading
            and self._processing_worker is not None
            and hasattr(self._processing_worker, "submit_preview_request")
        )

    def _request_render(
        self,
        interactive: bool = False,
        display_only: bool = False,
        **overrides: Any,
    ) -> int:
        """Queue a preview render of the committed state (plus overrides).

        ``display_only`` frames are shown but never become
        ``image_model.current_image`` -- used for uncommitted tool previews.
        """
        request_id = self._processing_worker.submit_preview_request(
            **self._render_kwargs(**overrides),
            interactive_preview=interactive,
        )
        self._latest_request_id = request_id
        if display_only:
            self._display_only_request_ids.add(request_id)
        return request_id

    def _preview_tool_candidate(self, **overrides: Any) -> None:
        """Show an uncommitted tool edit (mask, heal spots, uncropped frame):
        a cheap interactive frame now, a quality frame once input settles."""
        self._final_render_timer.stop()
        self._pending_tool_overrides = overrides
        self._request_render(interactive=True, display_only=True, **overrides)
        self._tool_preview_timer.start()

    def _submit_tool_quality_preview(self) -> None:
        overrides = self._pending_tool_overrides
        if overrides is None or not self.has_image() or not self._renders_async():
            return
        self._request_render(interactive=False, display_only=True, **overrides)

    def _commit_pending_history(self) -> None:
        """Push one settings-only undo step for the gesture that just ended.

        History stores adjustment-state dicts, never pixels: undo re-renders
        through the worker (usually a preview-cache hit), so a step costs a
        few KB instead of two full-resolution float buffers.
        """
        previous_state = self._pending_history_previous_state
        self._pending_history_previous_image = None
        self._pending_history_previous_state = None
        if previous_state is None:
            return
        new_state = self.get_adjustment_state()
        if new_state == previous_state:
            return
        self._history_service.execute_command(
            AdjustmentStateCommand(
                controller=self,
                previous_image=None,
                previous_state=previous_state,
                new_image=None,
                new_state=new_state,
            )
        )

    def get_output_size(self) -> Optional[tuple[int, int]]:
        """``(width, height)`` of the fully adjusted full-resolution output."""
        original = self._image_model.get_original_image()
        if original is None:
            return None
        height, width = original.shape[0], original.shape[1]
        if self._crop_params:
            x0 = self._crop_params.get("x0", 0.0)
            x1 = self._crop_params.get("x1", 1.0)
            y0 = self._crop_params.get("y0", 0.0)
            y1 = self._crop_params.get("y1", 1.0)
            width = max(1, int(round(width * (x1 - x0))))
            height = max(1, int(round(height * (y1 - y0))))
        return width, height

    def _view_needs_detail(self) -> bool:
        """True when the view magnifies a preview that has fewer pixels than
        the full-resolution output, so a full render would add detail."""
        pixmap_size = self._image_view.get_pixmap_size()
        output_size = self.get_output_size()
        if pixmap_size is None or output_size is None:
            return False
        if pixmap_size[0] >= output_size[0] * 0.98:
            return False
        return self._image_view.display_scale() > 1.05

    def _schedule_detail_render(self) -> None:
        """Start the idle timer for a full-resolution detail render; the
        timer re-checks :meth:`_view_needs_detail` when it fires."""
        if self._final_processing_worker is None and self._processing_worker is None:
            return
        self._final_render_timer.start()

    def _on_view_zoom_changed(self, _zoom: float) -> None:
        if self._renders_async() and self.has_image() and self._view_needs_detail():
            self._schedule_detail_render()

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
        texture_params = params.get('texture', {})
        clarity_params = params.get('clarity', {})
        dehaze_params = params.get('dehaze', {})
        vignette_params = params.get('vignette', {})
        grain_params = params.get('grain', {})
        sharpening_params = params.get('sharpening', {})
        luminance_nr_params = params.get('luminance_nr', {})
        color_nr_params = params.get('color_nr', {})
        remove_ca_params = params.get('remove_ca', {})
        defringe_params = params.get('defringe', {})
        geometry_params = params.get('geometry', {})
        straighten_params = params.get('straighten', {})
        crop_params = params.get('crop', {})
        mask_params = params.get('mask', {})
        healing_params = params.get('healing', {})
        self._latest_request_id = self._processing_worker.submit_preview_request(
            exposure_params=exposure_params,
            tonal_params=tonal_params,
            color_params=color_params,
            curve_params=curve_params,
            wb_params=wb_params,
            hsl_params=hsl_params,
            color_grading_params=color_grading_params,
            texture_params=texture_params,
            clarity_params=clarity_params,
            dehaze_params=dehaze_params,
            vignette_params=vignette_params,
            grain_params=grain_params,
            sharpening_params=sharpening_params,
            luminance_nr_params=luminance_nr_params,
            color_nr_params=color_nr_params,
            remove_ca_params=remove_ca_params,
            defringe_params=defringe_params,
            geometry_params=geometry_params,
            straighten_params=straighten_params,
            crop_params=crop_params,
            mask_params=mask_params,
            healing_params=healing_params,
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
        texture_params = params.get('texture', {})
        clarity_params = params.get('clarity', {})
        dehaze_params = params.get('dehaze', {})
        vignette_params = params.get('vignette', {})
        grain_params = params.get('grain', {})
        sharpening_params = params.get('sharpening', {})
        luminance_nr_params = params.get('luminance_nr', {})
        color_nr_params = params.get('color_nr', {})
        remove_ca_params = params.get('remove_ca', {})
        defringe_params = params.get('defringe', {})
        geometry_params = params.get('geometry', {})
        straighten_params = params.get('straighten', {})
        crop_params = params.get('crop', {})
        mask_params = params.get('mask', {})
        healing_params = params.get('healing', {})

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
            texture_params=texture_params,
            clarity_params=clarity_params,
            dehaze_params=dehaze_params,
            vignette_params=vignette_params,
            grain_params=grain_params,
            sharpening_params=sharpening_params,
            luminance_nr_params=luminance_nr_params,
            color_nr_params=color_nr_params,
            remove_ca_params=remove_ca_params,
            defringe_params=defringe_params,
            geometry_params=geometry_params,
            straighten_params=straighten_params,
            crop_params=crop_params,
            mask_params=mask_params,
            healing_params=healing_params,
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
        display_only = request_id in self._display_only_request_ids
        if self._display_only_request_ids:
            self._display_only_request_ids = {
                rid for rid in self._display_only_request_ids if rid > request_id
            }
        if frame.linear_image is not None and not display_only:
            self._image_model.current_image = frame.linear_image
        self._image_view.set_display_frame(frame, preserve_view_scale=True)
        logger.info(
            "PERF controller.present_preview request=%s shape=%s total_ms=%.2f",
            request_id,
            frame.shape,
            _elapsed_ms(start),
        )

    def _on_processing_complete(self, request_id: int, payload) -> None:
        """Present a full-resolution detail render from the final worker.

        ``payload`` is normally a :class:`DisplayFrame` whose RGB
        conversion already happened in the worker; a bare ``LinearImage``
        is accepted for callers without one. History is not touched here:
        it is committed (settings only) when the gesture ends.
        """
        final_worker = self._final_processing_worker or self._processing_worker
        if final_worker is not None and \
           not final_worker.is_latest_request(request_id):
            return
        if request_id != self._pending_final_request_id:
            return
        self._pending_final_request_id = -1

        frame = payload
        if not isinstance(frame, DisplayFrame):
            frame = DisplayFrame.from_linear(request_id, "full", (), payload)

        # Final frame should supersede queued previews immediately.
        self._pending_preview = None
        self._preview_present_timer.stop()
        if frame.linear_image is not None:
            self._image_model.current_image = frame.linear_image
        self._image_view.set_display_frame(frame, preserve_view_scale=True)

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

            # Show the quality preview and record the undo step right away
            # (settings only). A full-resolution render follows only if the
            # view is zoomed in far enough to need it; grabbing a slider
            # again cancels that timer before it can occupy a worker.
            self._request_render(interactive=False)
            self._commit_pending_history()
            self._schedule_detail_render()
            logger.info(
                "PERF controller.slider_released quality_request=%s "
                "detail_idle_delay_ms=%s schedule_ms=%.2f",
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
            any(v != 0 for v in self._texture_params.values()) or
            any(v != 0 for v in self._clarity_params.values()) or
            any(v != 0 for v in self._dehaze_params.values()) or
            any(v != 0 for v in self._vignette_params.values()) or
            any(v != 0 for v in self._grain_params.values()) or
            any(v != 0 for v in self._sharpening_params.values()) or
            any(v != 0 for v in self._luminance_nr_params.values()) or
            any(v != 0 for v in self._color_nr_params.values()) or
            any(v != 0 for v in self._remove_ca_params.values()) or
            any(v != 0 for v in self._defringe_params.values()) or
            any(
                self._geometry_params.get(key, default) != default
                for key, default in self._GEOMETRY_DEFAULTS.items()
            ) or
            any(v != 0 for v in self._straighten_params.values()) or
            not is_identity_curve(self._curve_params.get("points")) or
            not is_identity_curve(self._curve_params.get("red_points")) or
            not is_identity_curve(self._curve_params.get("green_points")) or
            not is_identity_curve(self._curve_params.get("blue_points")) or
            bool(self._crop_params) or
            bool(self._mask_params) or
            bool(self._healing_params)
        )

    def _submit_delayed_final_render(self) -> None:
        """Submit a full-resolution detail render after the user went idle,
        but only when the view actually shows more pixels than the
        quality preview has (zoomed in); a fitted view never needs it."""
        start = perf_counter()
        final_worker = self._final_processing_worker or self._processing_worker
        if not self.has_image() or final_worker is None:
            return
        if self._pending_tool_overrides is not None:
            return  # a tool preview is on screen; don't replace it
        if not self._view_needs_detail():
            return

        self._pending_final_request_id = final_worker.submit_final_request(
            **self._render_kwargs()
        )
        logger.info(
            "PERF controller.submit_full request=%s schedule_ms=%.2f",
            self._pending_final_request_id,
            _elapsed_ms(start),
        )

    def commit_adjustments(self) -> None:
        """Commit current adjustments to history.

        Call this when user finishes adjusting (e.g., releases slider).

        This is a third history-push site beyond the two the original
        state-aware undo/redo design called out (the threaded
        ``_commit_rendered_adjustment`` path and the synchronous fallback
        inside ``apply_adjustments``) -- it is ``on_slider_released``'s own
        synchronous fallback for non-threaded callers/tests. It is
        converted to push a state-aware ``AdjustmentStateCommand`` the same
        way, for the same reason: without this, undo through this path
        would still only swap the pixel buffer. See
        docs/planning/implementation-notes/
        2026-10-13-state-aware-undo-redo.md.
        """
        if not self.has_image():
            return

        # Only commit if there are actual changes
        if self._has_pending_adjustment_changes():
            # Idempotent: a no-op if on_adjustments_changed/on_curve_changed/
            # on_hsl_changed/on_color_grading_changed already captured the
            # pre-gesture snapshot (the normal case); captures it here
            # otherwise, so a direct call to commit_adjustments() still
            # gets a correct "previous" pair.
            self._capture_pending_history_state()

            command = CombinedAdjustmentCommand(
                self._image_model,
                exposure_params=self._exposure_params.copy(),
                tonal_params=self._tonal_params.copy(),
                color_params=self._color_params.copy(),
                curve_params=dict(self._curve_params),
                wb_params=self._wb_params.copy(),
                hsl_params=self._hsl_params.copy(),
                color_grading_params=self._color_grading_params.copy(),
                texture_params=self._texture_params.copy(),
                clarity_params=self._clarity_params.copy(),
                dehaze_params=self._dehaze_params.copy(),
                vignette_params=self._vignette_params.copy(),
                grain_params=self._grain_params.copy(),
                sharpening_params=self._sharpening_params.copy(),
                luminance_nr_params=self._luminance_nr_params.copy(),
                color_nr_params=self._color_nr_params.copy(),
                remove_ca_params=self._remove_ca_params.copy(),
                defringe_params=self._defringe_params.copy(),
                geometry_params=self._geometry_params.copy(),
                straighten_params=self._straighten_params.copy(),
                crop_params=self._crop_params.copy(),
                mask_params=self._mask_params.copy(),
                healing_params=self._healing_params.copy(),
            )
            command.execute()

            previous_image = self._pending_history_previous_image
            previous_state = self._pending_history_previous_state
            self._pending_history_previous_image = None
            self._pending_history_previous_state = None
            if previous_image is not None and previous_state is not None:
                state_command = AdjustmentStateCommand(
                    controller=self,
                    previous_image=previous_image,
                    previous_state=previous_state,
                    new_image=self._image_model.current_image,
                    new_state=self.get_adjustment_state(),
                )
                self._history_service.execute_command(state_command)

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

    def _normalize_crop_state(
        self,
        raw_crop: Optional[Dict[str, float]],
    ) -> Dict[str, float]:
        """Return a complete 4-key ``{"x0", "y0", "x1", "y1"}`` crop
        rectangle, defaulted to the full frame and defensively clamped.

        Unlike :meth:`_normalize_floats` (reused by the other three
        non-flat categories), this cannot just float-coerce each key
        against a default: the 4 values are mutually constrained (each
        in ``[0.0, 1.0]``, and ``x1``/``y1`` must not be below
        ``x0``/``y0``). The exact same clamp/swap logic
        :class:`~src.processors.crop_processor.CropProcessor` itself
        applies is mirrored here so a malformed/out-of-range persisted
        rectangle (an old catalog entry, a malformed imported preset) is
        never trusted blindly, consistent with how the processor treats
        its own input.
        """
        normalized = self._normalize_floats(raw_crop, self._CROP_DEFAULTS)
        x0, y0, x1, y1 = (
            normalized["x0"],
            normalized["y0"],
            normalized["x1"],
            normalized["y1"],
        )
        x0 = max(0.0, min(1.0, x0))
        x1 = max(0.0, min(1.0, x1))
        y0 = max(0.0, min(1.0, y0))
        y1 = max(0.0, min(1.0, y1))
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}

    @staticmethod
    def _is_identity_crop(crop_values: Dict[str, float]) -> bool:
        """True if ``crop_values`` is the full-frame (no-op) rectangle."""
        return (
            crop_values.get("x0", 0.0) <= 0.0
            and crop_values.get("y0", 0.0) <= 0.0
            and crop_values.get("x1", 1.0) >= 1.0
            and crop_values.get("y1", 1.0) >= 1.0
        )

    def _normalize_mask_state(
        self,
        raw_mask: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Return the internal mask-params dict: ``{}`` ("no mask") for
        ``None``/malformed input or an unrecognized/missing ``"type"``,
        otherwise a fully-populated, defensively-clamped dict.

        Mirrors :meth:`_normalize_crop_state`'s "never trust the caller"
        reasoning (the dict may come from an old catalog entry, a
        malformed imported preset, or interactive UI input in a later
        slice) but, unlike crop, there is no separate "collapse to the
        identity sentinel" step: an unrecognized/missing ``"type"`` IS
        the identity signal here, so it returns ``{}`` directly. See
        docs/planning/implementation-notes/2026-10-13-mask-processor.md
        section 4 for the full state-shape contract.
        """
        if not raw_mask or not isinstance(raw_mask, dict):
            return {}
        mask_type = raw_mask.get("type")
        if mask_type not in self._MASK_TYPES:
            return {}

        result: Dict[str, Any] = {
            "type": mask_type,
            "invert": bool(raw_mask.get("invert", False)),
        }

        if mask_type == "linear":
            for key, default in self._MASK_LINEAR_DEFAULTS.items():
                value = self._safe_float(raw_mask.get(key, default), default)
                result[key] = max(0.0, min(1.0, value))
        else:  # "radial"
            for key, default in self._MASK_RADIAL_DEFAULTS.items():
                value = self._safe_float(raw_mask.get(key, default), default)
                if key in ("cx", "cy"):
                    value = max(0.0, min(1.0, value))
                elif key in ("rx", "ry"):
                    value = max(1e-4, min(1.0, value))
                else:  # "feather"
                    value = max(0.0, min(1.0, value))
                result[key] = value

        for key, (low, high) in self._MASK_ADJUSTMENT_RANGES.items():
            value = self._safe_float(raw_mask.get(key, 0.0), 0.0)
            result[key] = max(low, min(high, value))

        return result

    def _normalize_heal_spots_state(
        self,
        raw_heal_spots: Optional[list],
    ) -> list:
        """Return a fully-clamped list of heal-spot dicts, skipping any
        malformed entry.

        Unlike :meth:`_normalize_mask_state` (a single dict, or ``{}``
        for "no mask"), healing's state is naturally a LIST of
        independent spots -- ``[]``/``None``/non-list input all return
        ``[]`` directly (the meaningful "no spots" default). Each
        remaining entry is validated the same "never trust the caller"
        way every other normalizer in this class already is: a non-dict
        entry or one with an unrecognized/missing ``"mode"`` is skipped
        entirely (there is no sensible default mode to substitute),
        while every other field is defensively clamped rather than
        rejected. Mirrors
        :meth:`~src.processors.healing_processor.HealingProcessor._normalize_spot`'s
        own clamping exactly, since both layers apply the same
        "never trust the caller" discipline independently (the same
        established precedent as crop/mask's own processor+controller
        double-validation). See docs/planning/implementation-notes/
        2026-10-13-healing-processor.md section 4.
        """
        if not raw_heal_spots or not isinstance(raw_heal_spots, list):
            return []

        normalized: list = []
        for raw_spot in raw_heal_spots:
            if not isinstance(raw_spot, dict):
                continue
            mode = raw_spot.get("mode")
            if mode not in self._HEALING_MODES:
                continue

            spot: Dict[str, Any] = {"mode": mode}
            for key in ("dst_x", "dst_y", "src_x", "src_y"):
                default = self._HEALING_SPOT_DEFAULTS[key]
                value = self._safe_float(raw_spot.get(key, default), default)
                spot[key] = max(0.0, min(1.0, value))

            radius_default = self._HEALING_SPOT_DEFAULTS["radius"]
            radius = self._safe_float(
                raw_spot.get("radius", radius_default), radius_default
            )
            spot["radius"] = max(1e-4, min(1.0, radius))

            feather_default = self._HEALING_SPOT_DEFAULTS["feather"]
            feather = self._safe_float(
                raw_spot.get("feather", feather_default), feather_default
            )
            spot["feather"] = max(0.0, min(1.0, feather))

            opacity_default = self._HEALING_SPOT_DEFAULTS["opacity"]
            opacity = self._safe_float(
                raw_spot.get("opacity", opacity_default), opacity_default
            )
            spot["opacity"] = max(0.0, min(1.0, opacity))

            normalized.append(spot)

        return normalized

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        """Coerce ``value`` to a float, tolerating bad types/values."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

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
