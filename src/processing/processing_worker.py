"""Background processing worker using QThread.

Operates on the canonical pipeline format
(:data:`src.utils.color_pipeline.LinearImage`). Qt signals carry the
arrays as ``object`` payloads (Qt cannot statically type ndarrays).
"""

from collections import OrderedDict
from dataclasses import dataclass
import logging
from time import perf_counter
from typing import Any, Dict, Optional, Tuple

from PyQt6.QtCore import QMutex, QObject, QThread, QWaitCondition, pyqtSignal

from src.processing.display_frame import DisplayFrame
from src.processing.processing_queue import ProcessingQueue, ProcessingRequest
from src.processing.pipeline import DevelopPipeline
from src.processing.proxy_manager import ProxyManager
from src.utils import pixel_kernels
from src.utils.color_pipeline import LinearImage


logger = logging.getLogger(__name__)


# Positional order of the stage keywords in submit_request.
_PARAM_ORDER = (
    "exposure_params", "tonal_params", "color_params", "curve_params",
    "wb_params", "hsl_params", "color_grading_params", "texture_params",
    "clarity_params", "dehaze_params", "vignette_params", "grain_params",
    "sharpening_params", "luminance_nr_params", "color_nr_params",
    "remove_ca_params", "defringe_params", "geometry_params",
    "straighten_params", "crop_params", "mask_params", "healing_params",
)


def _elapsed_ms(start: float) -> float:
    return (perf_counter() - start) * 1000.0


@dataclass
class _CachedPreview:
    """Cached preview image and its already-converted display buffer."""

    linear_image: LinearImage
    rgb: object


class ProcessingWorker(QObject):
    """Worker that processes images in a background thread.
    
    This worker runs in a separate thread and processes image adjustment
    requests without blocking the UI. Results are communicated back via
    Qt signals which are thread-safe.
    
    Signals:
        processing_started: Emitted when processing begins (request_id)
        preview_ready: Emitted when proxy preview is ready (request_id, DisplayFrame)
        processing_complete: Emitted when full processing is done (request_id, image)
        error_occurred: Emitted on processing error (request_id, error_message)
    """
    
    processing_started = pyqtSignal(int)
    preview_ready = pyqtSignal(int, object)  # request_id, DisplayFrame
    processing_complete = pyqtSignal(int, object)  # request_id, LinearImage
    # Full-resolution result with its RGB conversion already done in this
    # thread, so the UI only wraps it in a QPixmap (request_id, DisplayFrame).
    final_frame_ready = pyqtSignal(int, object)
    error_occurred = pyqtSignal(int, str)
    
    def __init__(
        self,
        parent: Optional[QObject] = None,
        proxy_max_size: Optional[int] = None,
        interactive_proxy_max_size: Optional[int] = None,
    ):
        """Initialize the processing worker.

        Args:
            parent: Optional parent QObject
            proxy_max_size: Optional override for the quality-preview
                proxy's maximum dimension (px). ``None`` (the default)
                uses ``ProxyManager.DEFAULT_PROXY_SIZE``, preserving
                today's behavior exactly.
            interactive_proxy_max_size: Optional override for the
                interactive/drag-preview proxy's maximum dimension (px).
                ``None`` (the default) uses
                ``ProxyManager.DEFAULT_INTERACTIVE_PROXY_SIZE``.
        """
        super().__init__(parent)

        self._queue = ProcessingQueue()
        self._proxy_manager = ProxyManager(
            max_size=proxy_max_size or ProxyManager.DEFAULT_PROXY_SIZE,
            interactive_max_size=(
                interactive_proxy_max_size
                or ProxyManager.DEFAULT_INTERACTIVE_PROXY_SIZE
            ),
        )
        self._result_cache: OrderedDict[Tuple, _CachedPreview] = OrderedDict()
        self._max_cache_entries = 16
        
        # One pipeline definition (src/processing/pipeline.py); the
        # per-stage attributes alias its processors for callers and tests.
        self._pipeline = DevelopPipeline()
        for _name, _processor in self._pipeline.processors.items():
            setattr(self, f"_{_name}_processor", _processor)

        # Thread control
        self._running = False
        self._pending_source: Optional[LinearImage] = None
        self._mutex = QMutex()
        self._condition = QWaitCondition()
        
        # Worker thread
        self._thread: Optional[QThread] = None
    
    @property
    def proxy_manager(self) -> ProxyManager:
        """Get the proxy manager."""
        return self._proxy_manager
    
    def start(self) -> None:
        """Start the worker thread."""
        if self._thread is not None and self._thread.isRunning():
            return
        
        self._running = True
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)
        self._thread.start()
    
    def stop(self) -> None:
        """Stop the worker thread."""
        self._mutex.lock()
        self._running = False
        self._condition.wakeAll()
        self._mutex.unlock()
        
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)  # Wait up to 5 seconds
            self._thread = None
    
    def is_running(self) -> bool:
        """Check if the worker is running.
        
        Returns:
            True if worker thread is active
        """
        return self._thread is not None and self._thread.isRunning()
    
    def set_image(self, image: LinearImage) -> None:
        """Set the source ``LinearImage`` for processing.

        Called from the UI thread when a new image is loaded. While the
        worker thread runs, this only hands the image over: proxy
        generation (copies and resizes of a 24 MP buffer) happens on the
        worker thread, and before any request submitted after this call,
        so a render requested right after loading always sees the new
        image.
        """
        if self.is_running():
            self._mutex.lock()
            self._pending_source = image
            self._condition.wakeOne()
            self._mutex.unlock()
            return
        self._install_source(image)

    def _install_source(self, image: LinearImage) -> None:
        self._proxy_manager.set_image(image)
        self._result_cache.clear()

    def _take_pending_source(self) -> Optional[LinearImage]:
        self._mutex.lock()
        image = self._pending_source
        self._pending_source = None
        self._mutex.unlock()
        return image
    
    def clear_image(self) -> None:
        """Clear the current image."""
        self._mutex.lock()
        self._pending_source = None
        self._mutex.unlock()
        self._proxy_manager.clear()
        self._queue.clear()
        self._result_cache.clear()
    
    def submit_request(
        self,
        exposure_params: Optional[Dict[str, float]] = None,
        tonal_params: Optional[Dict[str, float]] = None,
        color_params: Optional[Dict[str, float]] = None,
        curve_params: Optional[Dict[str, Any]] = None,
        wb_params: Optional[Dict[str, float]] = None,
        hsl_params: Optional[Dict[str, float]] = None,
        color_grading_params: Optional[Dict[str, float]] = None,
        texture_params: Optional[Dict[str, float]] = None,
        clarity_params: Optional[Dict[str, float]] = None,
        dehaze_params: Optional[Dict[str, float]] = None,
        vignette_params: Optional[Dict[str, float]] = None,
        grain_params: Optional[Dict[str, float]] = None,
        sharpening_params: Optional[Dict[str, float]] = None,
        luminance_nr_params: Optional[Dict[str, float]] = None,
        color_nr_params: Optional[Dict[str, float]] = None,
        remove_ca_params: Optional[Dict[str, float]] = None,
        defringe_params: Optional[Dict[str, float]] = None,
        geometry_params: Optional[Dict[str, float]] = None,
        straighten_params: Optional[Dict[str, float]] = None,
        crop_params: Optional[Dict[str, float]] = None,
        mask_params: Optional[Dict[str, Any]] = None,
        healing_params: Optional[Dict[str, Any]] = None,
        use_proxy: bool = True,
        interactive_preview: bool = True,
    ) -> int:
        """Submit a processing request.

        Args:
            exposure_params: Exposure adjustment parameters
            tonal_params: Highlights/Shadows/Whites/Blacks parameters
            color_params: Color adjustment parameters
            curve_params: Tone curve parameters
            wb_params: White balance (Temperature/Tint) parameters
            hsl_params: HSL Color Mixer parameters
            color_grading_params: Color Grading parameters
            use_proxy: Whether to process proxy (fast) or full image
            interactive_preview: Whether to use the lower-cost interactive proxy

        Returns:
            Request ID for tracking
        """
        request = self._queue.create_request(
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
            use_proxy=use_proxy,
            interactive_preview=interactive_preview,
        )
        self._queue.enqueue(request)

        # Wake up the worker thread. Holding the mutex closes the gap
        # between the worker's "queue is empty" check and its wait(), where
        # an unlocked wake could be lost and the request left waiting.
        self._mutex.lock()
        self._condition.wakeOne()
        self._mutex.unlock()

        return request.request_id

    def submit_preview_request(
        self,
        exposure_params: Optional[Dict[str, float]] = None,
        tonal_params: Optional[Dict[str, float]] = None,
        color_params: Optional[Dict[str, float]] = None,
        curve_params: Optional[Dict[str, Any]] = None,
        wb_params: Optional[Dict[str, float]] = None,
        hsl_params: Optional[Dict[str, float]] = None,
        color_grading_params: Optional[Dict[str, float]] = None,
        texture_params: Optional[Dict[str, float]] = None,
        clarity_params: Optional[Dict[str, float]] = None,
        dehaze_params: Optional[Dict[str, float]] = None,
        vignette_params: Optional[Dict[str, float]] = None,
        grain_params: Optional[Dict[str, float]] = None,
        sharpening_params: Optional[Dict[str, float]] = None,
        luminance_nr_params: Optional[Dict[str, float]] = None,
        color_nr_params: Optional[Dict[str, float]] = None,
        remove_ca_params: Optional[Dict[str, float]] = None,
        defringe_params: Optional[Dict[str, float]] = None,
        geometry_params: Optional[Dict[str, float]] = None,
        straighten_params: Optional[Dict[str, float]] = None,
        crop_params: Optional[Dict[str, float]] = None,
        mask_params: Optional[Dict[str, Any]] = None,
        healing_params: Optional[Dict[str, Any]] = None,
        interactive_preview: bool = True,
    ) -> int:
        """Submit a preview (proxy) processing request.

        Convenience method for submitting proxy requests.

        Args:
            exposure_params: Exposure adjustment parameters
            tonal_params: Highlights/Shadows/Whites/Blacks parameters
            color_params: Color adjustment parameters
            curve_params: Tone curve parameters
            wb_params: White balance (Temperature/Tint) parameters
            hsl_params: HSL Color Mixer parameters
            color_grading_params: Color Grading parameters
            interactive_preview: Use smaller interactive proxy for drag updates.

        Returns:
            Request ID
        """
        return self.submit_request(
            exposure_params,
            tonal_params,
            color_params,
            curve_params,
            wb_params,
            hsl_params,
            color_grading_params,
            texture_params,
            clarity_params,
            dehaze_params,
            vignette_params,
            grain_params,
            sharpening_params,
            luminance_nr_params,
            color_nr_params,
            remove_ca_params,
            defringe_params,
            geometry_params,
            straighten_params,
            crop_params,
            mask_params,
            healing_params,
            use_proxy=True,
            interactive_preview=interactive_preview,
        )

    def submit_final_request(
        self,
        exposure_params: Optional[Dict[str, float]] = None,
        tonal_params: Optional[Dict[str, float]] = None,
        color_params: Optional[Dict[str, float]] = None,
        curve_params: Optional[Dict[str, Any]] = None,
        wb_params: Optional[Dict[str, float]] = None,
        hsl_params: Optional[Dict[str, float]] = None,
        color_grading_params: Optional[Dict[str, float]] = None,
        texture_params: Optional[Dict[str, float]] = None,
        clarity_params: Optional[Dict[str, float]] = None,
        dehaze_params: Optional[Dict[str, float]] = None,
        vignette_params: Optional[Dict[str, float]] = None,
        grain_params: Optional[Dict[str, float]] = None,
        sharpening_params: Optional[Dict[str, float]] = None,
        luminance_nr_params: Optional[Dict[str, float]] = None,
        color_nr_params: Optional[Dict[str, float]] = None,
        remove_ca_params: Optional[Dict[str, float]] = None,
        defringe_params: Optional[Dict[str, float]] = None,
        geometry_params: Optional[Dict[str, float]] = None,
        straighten_params: Optional[Dict[str, float]] = None,
        crop_params: Optional[Dict[str, float]] = None,
        mask_params: Optional[Dict[str, Any]] = None,
        healing_params: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Submit a full-resolution processing request.

        Convenience method for submitting final render requests.

        Args:
            exposure_params: Exposure adjustment parameters
            tonal_params: Highlights/Shadows/Whites/Blacks parameters
            color_params: Color adjustment parameters
            curve_params: Tone curve parameters
            wb_params: White balance (Temperature/Tint) parameters
            hsl_params: HSL Color Mixer parameters
            color_grading_params: Color Grading parameters

        Returns:
            Request ID
        """
        return self.submit_request(
            exposure_params,
            tonal_params,
            color_params,
            curve_params,
            wb_params,
            hsl_params,
            color_grading_params,
            texture_params,
            clarity_params,
            dehaze_params,
            vignette_params,
            grain_params,
            sharpening_params,
            luminance_nr_params,
            color_nr_params,
            remove_ca_params,
            defringe_params,
            geometry_params,
            straighten_params,
            crop_params,
            mask_params,
            healing_params,
            use_proxy=False,
        )

    def cancel_pending(self) -> None:
        """Cancel all pending requests."""
        self._queue.cancel_all()
    
    def is_latest_request(self, request_id: int) -> bool:
        """Check if a request ID is still the latest.
        
        Args:
            request_id: Request ID to check
            
        Returns:
            True if this is the latest request
        """
        return self._queue.is_latest(request_id)
    
    def _run(self) -> None:
        """Main worker loop (runs in worker thread)."""
        # Compile/load the pixel kernels here, off the UI thread, so the
        # first slider move doesn't pay the one-off JIT cost.
        pixel_kernels.warm_up()
        while self._running:
            # A newly loaded image always lands before the next request.
            pending_source = self._take_pending_source()
            if pending_source is not None:
                self._install_source(pending_source)

            # Get next request
            request = self._queue.get_latest()

            if request is None:
                # No work, wait for signal
                self._mutex.lock()
                if (
                    self._running
                    and self._queue.is_empty()
                    and self._pending_source is None
                ):
                    self._condition.wait(self._mutex)
                self._mutex.unlock()
                continue
            
            # Skip if cancelled (superseded by a newer request)
            if not request.should_process():
                continue
            
            # Process the request
            self._process_request(request)
    
    def _process_request(self, request: ProcessingRequest) -> None:
        """Process a single request.
        
        Args:
            request: The request to process
        """
        total_start = perf_counter()
        tier = self._request_tier(request)
        try:
            self.processing_started.emit(request.request_id)
            
            # Get source image (proxy or full)
            source_start = perf_counter()
            if request.use_proxy:
                source = self._proxy_manager.get_proxy(
                    interactive=request.interactive_preview
                )
            else:
                source = self._proxy_manager.get_original()
            source_ms = _elapsed_ms(source_start)
            
            if source is None:
                self.error_occurred.emit(request.request_id, "No image available")
                return
            
            # Check if still valid before heavy processing
            if not request.should_process():
                return

            cache_key = self._cache_key(request, source)
            if cache_key is not None and cache_key in self._result_cache:
                cache_start = perf_counter()
                cached = self._result_cache[cache_key]
                result = cached.linear_image.copy()
                frame = DisplayFrame(
                    request_id=request.request_id,
                    tier=tier,
                    adjustment_signature=self._adjustment_signature(request),
                    rgb=cached.rgb.copy(),
                    linear_image=result,
                    source_size=self._full_size_of(result, source),
                )
                self._result_cache.move_to_end(cache_key)
                cache_ms = _elapsed_ms(cache_start)
                self.preview_ready.emit(request.request_id, frame)
                logger.info(
                    "PERF worker request=%s tier=%s cache=hit "
                    "source_ms=%.2f cache_copy_ms=%.2f total_ms=%.2f shape=%s",
                    request.request_id,
                    tier,
                    source_ms,
                    cache_ms,
                    _elapsed_ms(total_start),
                    source.shape,
                )
                return
            
            # Apply adjustments
            apply_start = perf_counter()
            original_long = max(self._proxy_manager.original_size) or max(source.shape[:2])
            result = self._apply_adjustments(
                source,
                request.exposure_params,
                request.tonal_params,
                request.color_params,
                request.curve_params,
                request.wb_params,
                request.hsl_params,
                request.color_grading_params,
                request.texture_params,
                request.clarity_params,
                request.dehaze_params,
                request.vignette_params,
                request.grain_params,
                request.sharpening_params,
                request.luminance_nr_params,
                request.color_nr_params,
                request.remove_ca_params,
                request.defringe_params,
                request.geometry_params,
                request.straighten_params,
                request.crop_params,
                request.mask_params,
                request.healing_params,
                pixel_scale=max(source.shape[:2]) / original_long,
            )
            apply_ms = _elapsed_ms(apply_start)

            frame = None
            display_ms = 0.0
            # Full renders get a display frame too: converting 24 MP to RGB
            # here keeps that ~300 ms off the UI thread.
            if request.use_proxy or self._wants_final_frames():
                display_start = perf_counter()
                frame = DisplayFrame.from_linear(
                    request.request_id,
                    tier,
                    self._adjustment_signature(request),
                    result,
                    source_size=self._full_size_of(result, source),
                )
                display_ms = _elapsed_ms(display_start)

            if cache_key is not None:
                cache_store_start = perf_counter()
                self._result_cache[cache_key] = _CachedPreview(
                    linear_image=result.copy(),
                    rgb=frame.rgb.copy() if frame is not None else None,
                )
                self._result_cache.move_to_end(cache_key)
                while len(self._result_cache) > self._max_cache_entries:
                    self._result_cache.popitem(last=False)
                cache_store_ms = _elapsed_ms(cache_store_start)
            else:
                cache_store_ms = 0.0
            
            # Check again after processing
            if not request.should_process():
                return
            
            # Emit appropriate signal
            if request.use_proxy:
                self.preview_ready.emit(request.request_id, frame)
            else:
                self.processing_complete.emit(request.request_id, result)
                if frame is not None:
                    self.final_frame_ready.emit(request.request_id, frame)

            logger.info(
                "PERF worker request=%s tier=%s cache=miss source_ms=%.2f "
                "apply_ms=%.2f display_ms=%.2f cache_store_ms=%.2f "
                "total_ms=%.2f shape=%s",
                request.request_id,
                tier,
                source_ms,
                apply_ms,
                display_ms,
                cache_store_ms,
                _elapsed_ms(total_start),
                source.shape,
            )
                
        except Exception as e:
            self.error_occurred.emit(request.request_id, str(e))

    def _cache_key(
        self, request: ProcessingRequest, source: LinearImage
    ) -> Optional[Tuple]:
        """Return a small preview-cache key, or None for full-res renders."""
        if not request.use_proxy:
            return None
        return (
            bool(request.interactive_preview),
            tuple(source.shape),
            tuple(sorted(request.exposure_params.items())),
            tuple(sorted(request.tonal_params.items())),
            tuple(sorted(request.color_params.items())),
            tuple(sorted(request.curve_params.items())),
            tuple(sorted(request.wb_params.items())),
            tuple(sorted(request.hsl_params.items())),
            tuple(sorted(request.color_grading_params.items())),
            tuple(sorted(request.texture_params.items())),
            tuple(sorted(request.clarity_params.items())),
            tuple(sorted(request.dehaze_params.items())),
            tuple(sorted(request.vignette_params.items())),
            tuple(sorted(request.grain_params.items())),
            tuple(sorted(request.sharpening_params.items())),
            tuple(sorted(request.luminance_nr_params.items())),
            tuple(sorted(request.color_nr_params.items())),
            tuple(sorted(request.remove_ca_params.items())),
            tuple(sorted(request.defringe_params.items())),
            tuple(sorted(request.geometry_params.items())),
            tuple(sorted(request.straighten_params.items())),
            tuple(sorted(request.crop_params.items())),
            tuple(sorted(request.mask_params.items())),
            self._hashable_heal_spots(request.healing_params),
        )

    @staticmethod
    def _hashable_heal_spots(healing_params: Dict[str, Any]) -> Tuple:
        """Return a hashable form of ``healing_params``'s ``heal_spots``
        list, for use inside a cache-key/signature tuple.

        ``heal_spots`` is a list of dicts (unlike every other
        ``_xxx_params`` field, which is flat and already hashable via
        ``tuple(sorted(items()))``), so it needs its own conversion: a
        tuple of per-spot ``tuple(sorted(spot.items()))`` tuples, which
        is hashable as long as every spot value is itself hashable (true
        for this schema -- floats and the ``mode`` string only).
        """
        return tuple(
            tuple(sorted(spot.items()))
            for spot in healing_params.get("heal_spots", [])
            if isinstance(spot, dict)
        )

    @staticmethod
    def _adjustment_signature(request: ProcessingRequest) -> Tuple:
        """Return a stable signature for request parameters."""
        return (
            tuple(sorted(request.exposure_params.items())),
            tuple(sorted(request.tonal_params.items())),
            tuple(sorted(request.color_params.items())),
            tuple(sorted(request.curve_params.items())),
            tuple(sorted(request.wb_params.items())),
            tuple(sorted(request.hsl_params.items())),
            tuple(sorted(request.color_grading_params.items())),
            tuple(sorted(request.texture_params.items())),
            tuple(sorted(request.clarity_params.items())),
            tuple(sorted(request.dehaze_params.items())),
            tuple(sorted(request.vignette_params.items())),
            tuple(sorted(request.grain_params.items())),
            tuple(sorted(request.sharpening_params.items())),
            tuple(sorted(request.luminance_nr_params.items())),
            tuple(sorted(request.color_nr_params.items())),
            tuple(sorted(request.remove_ca_params.items())),
            tuple(sorted(request.defringe_params.items())),
            tuple(sorted(request.geometry_params.items())),
            tuple(sorted(request.straighten_params.items())),
            tuple(sorted(request.crop_params.items())),
            tuple(sorted(request.mask_params.items())),
            ProcessingWorker._hashable_heal_spots(request.healing_params),
        )

    def _apply_adjustments(
        self, image: LinearImage, *args, pixel_scale: float = 1.0, **params
    ) -> LinearImage:
        """Run the develop pipeline (src/processing/pipeline.py) on ``image``.

        Accepts the ``<stage>_params`` keywords (positional order of
        :meth:`submit_request` is also accepted for older callers) and logs
        per-stage timings.
        """
        if args:
            params.update(zip(_PARAM_ORDER, args))
        total_start = perf_counter()
        timings: Dict[str, float] = {}
        result = self._pipeline.render(
            image, timings=timings, pixel_scale=pixel_scale, **params
        )
        logger.info(
            "PERF worker.apply shape=%s %s total_ms=%.2f",
            image.shape,
            " ".join(f"{name}_ms={ms:.2f}" for name, ms in timings.items()),
            _elapsed_ms(total_start),
        )
        return result

    def _full_size_of(
        self, result: LinearImage, source: LinearImage
    ) -> Tuple[int, int]:
        """Full-resolution ``(width, height)`` that ``result`` (rendered
        from ``source``, possibly a proxy and possibly cropped) represents."""
        original_w = self._proxy_manager.original_size[0] or source.shape[1]
        scale = original_w / float(source.shape[1])
        return (
            max(1, int(round(result.shape[1] * scale))),
            max(1, int(round(result.shape[0] * scale))),
        )

    def _wants_final_frames(self) -> bool:
        """True when something listens for ``final_frame_ready``."""
        return self.receivers(self.final_frame_ready) > 0

    @staticmethod
    def _request_tier(request: ProcessingRequest) -> str:
        if not request.use_proxy:
            return "full"
        return "interactive" if request.interactive_preview else "quality"


class ProcessingController:
    """High-level controller for the processing system.
    
    This provides a simpler interface for the image controller to use,
    managing the worker lifecycle and coordinating requests.
    """
    
    def __init__(self):
        """Initialize the processing controller."""
        self._worker = ProcessingWorker()
        self._current_exposure_params: Dict[str, float] = {}
        self._current_tonal_params: Dict[str, float] = {}
        self._current_color_params: Dict[str, float] = {}
    
    @property
    def worker(self) -> ProcessingWorker:
        """Get the processing worker."""
        return self._worker
    
    def start(self) -> None:
        """Start the processing system."""
        self._worker.start()
    
    def stop(self) -> None:
        """Stop the processing system."""
        self._worker.stop()
    
    def set_image(self, image: LinearImage) -> None:
        """Set the source ``LinearImage``."""
        self._worker.set_image(image)
        self._current_exposure_params = {}
        self._current_tonal_params = {}
        self._current_color_params = {}

    def clear_image(self) -> None:
        """Clear the current image."""
        self._worker.clear_image()

    def update_adjustments(
        self,
        exposure_params: Optional[Dict[str, float]] = None,
        tonal_params: Optional[Dict[str, float]] = None,
        color_params: Optional[Dict[str, float]] = None
    ) -> int:
        """Update adjustments and request preview processing.

        Args:
            exposure_params: New exposure parameters
            tonal_params: New Highlights/Shadows/Whites/Blacks parameters
            color_params: New color parameters

        Returns:
            Request ID
        """
        if exposure_params is not None:
            self._current_exposure_params = exposure_params
        if tonal_params is not None:
            self._current_tonal_params = tonal_params
        if color_params is not None:
            self._current_color_params = color_params

        return self._worker.submit_preview_request(
            self._current_exposure_params,
            self._current_tonal_params,
            self._current_color_params
        )

    def finalize_adjustments(self) -> int:
        """Request full-resolution processing with current adjustments.

        Returns:
            Request ID
        """
        return self._worker.submit_final_request(
            self._current_exposure_params,
            self._current_tonal_params,
            self._current_color_params
        )
    
    def connect_signals(
        self,
        on_preview: callable = None,
        on_complete: callable = None,
        on_error: callable = None
    ) -> None:
        """Connect to processing signals.
        
        Args:
            on_preview: Callback for preview ready (request_id, image)
            on_complete: Callback for processing complete (request_id, image)
            on_error: Callback for errors (request_id, error_message)
        """
        if on_preview:
            self._worker.preview_ready.connect(on_preview)
        if on_complete:
            self._worker.processing_complete.connect(on_complete)
        if on_error:
            self._worker.error_occurred.connect(on_error)
