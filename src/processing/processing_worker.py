"""Background processing worker using QThread.

Operates on the canonical pipeline format
(:data:`src.utils.color_pipeline.LinearImage`). Qt signals carry the
arrays as ``object`` payloads (Qt cannot statically type ndarrays).
"""

from collections import OrderedDict
from dataclasses import dataclass
import logging
from time import perf_counter
from typing import Dict, Optional, Tuple

from PyQt6.QtCore import QMutex, QObject, QThread, QWaitCondition, pyqtSignal

from src.processing.display_frame import DisplayFrame
from src.processing.processing_queue import ProcessingQueue, ProcessingRequest
from src.processing.proxy_manager import ProxyManager
from src.processors.color_processor import ColorProcessor
from src.processors.exposure_processor import ExposureProcessor
from src.utils.color_pipeline import LinearImage


logger = logging.getLogger(__name__)


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
    error_occurred = pyqtSignal(int, str)
    
    def __init__(self, parent: Optional[QObject] = None):
        """Initialize the processing worker.
        
        Args:
            parent: Optional parent QObject
        """
        super().__init__(parent)
        
        self._queue = ProcessingQueue()
        self._proxy_manager = ProxyManager()
        self._result_cache: OrderedDict[Tuple, _CachedPreview] = OrderedDict()
        self._max_cache_entries = 16
        
        # Processors
        self._exposure_processor = ExposureProcessor()
        self._color_processor = ColorProcessor()
        
        # Thread control
        self._running = False
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

        Should be called from the main thread when a new image is loaded.
        """
        self._proxy_manager.set_image(image)
        self._result_cache.clear()
    
    def clear_image(self) -> None:
        """Clear the current image."""
        self._proxy_manager.clear()
        self._queue.clear()
        self._result_cache.clear()
    
    def submit_request(
        self,
        exposure_params: Optional[Dict[str, float]] = None,
        color_params: Optional[Dict[str, float]] = None,
        use_proxy: bool = True,
        interactive_preview: bool = True,
    ) -> int:
        """Submit a processing request.
        
        Args:
            exposure_params: Exposure adjustment parameters
            color_params: Color adjustment parameters
            use_proxy: Whether to process proxy (fast) or full image
            interactive_preview: Whether to use the lower-cost interactive proxy
            
        Returns:
            Request ID for tracking
        """
        request = self._queue.create_request(
            exposure_params=exposure_params,
            color_params=color_params,
            use_proxy=use_proxy,
            interactive_preview=interactive_preview,
        )
        self._queue.enqueue(request)
        
        # Wake up the worker thread
        self._condition.wakeOne()
        
        return request.request_id
    
    def submit_preview_request(
        self,
        exposure_params: Optional[Dict[str, float]] = None,
        color_params: Optional[Dict[str, float]] = None,
        interactive_preview: bool = True,
    ) -> int:
        """Submit a preview (proxy) processing request.
        
        Convenience method for submitting proxy requests.
        
        Args:
            exposure_params: Exposure adjustment parameters
            color_params: Color adjustment parameters
            interactive_preview: Use smaller interactive proxy for drag updates.
            
        Returns:
            Request ID
        """
        return self.submit_request(
            exposure_params,
            color_params,
            use_proxy=True,
            interactive_preview=interactive_preview,
        )
    
    def submit_final_request(
        self,
        exposure_params: Optional[Dict[str, float]] = None,
        color_params: Optional[Dict[str, float]] = None
    ) -> int:
        """Submit a full-resolution processing request.
        
        Convenience method for submitting final render requests.
        
        Args:
            exposure_params: Exposure adjustment parameters
            color_params: Color adjustment parameters
            
        Returns:
            Request ID
        """
        return self.submit_request(exposure_params, color_params, use_proxy=False)
    
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
        while self._running:
            # Get next request
            request = self._queue.get_latest()
            
            if request is None:
                # No work, wait for signal
                self._mutex.lock()
                if self._running and self._queue.is_empty():
                    self._condition.wait(self._mutex)
                self._mutex.unlock()
                continue
            
            # Skip if cancelled or stale
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
            result = self._apply_adjustments(
                source,
                request.exposure_params,
                request.color_params
            )
            apply_ms = _elapsed_ms(apply_start)

            frame = None
            display_ms = 0.0
            if request.use_proxy:
                display_start = perf_counter()
                frame = DisplayFrame.from_linear(
                    request.request_id,
                    tier,
                    self._adjustment_signature(request),
                    result,
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
            tuple(sorted(request.color_params.items())),
        )

    @staticmethod
    def _adjustment_signature(request: ProcessingRequest) -> Tuple:
        """Return a stable signature for request parameters."""
        return (
            tuple(sorted(request.exposure_params.items())),
            tuple(sorted(request.color_params.items())),
        )
    
    def _apply_adjustments(
        self,
        image: LinearImage,
        exposure_params: Dict[str, float],
        color_params: Dict[str, float],
    ) -> LinearImage:
        """Apply exposure and color adjustments to a ``LinearImage``."""
        total_start = perf_counter()
        copy_start = perf_counter()
        result = image.copy()
        copy_ms = _elapsed_ms(copy_start)
        exposure_ms = 0.0
        color_ms = 0.0

        if exposure_params and any(v != 0 for v in exposure_params.values()):
            exposure_start = perf_counter()
            result = self._exposure_processor.process(result, **exposure_params)
            exposure_ms = _elapsed_ms(exposure_start)

        if color_params and any(v != 0 for v in color_params.values()):
            color_start = perf_counter()
            result = self._color_processor.process(result, **color_params)
            color_ms = _elapsed_ms(color_start)

        logger.info(
            "PERF worker.apply shape=%s copy_ms=%.2f exposure_ms=%.2f "
            "color_ms=%.2f total_ms=%.2f",
            image.shape,
            copy_ms,
            exposure_ms,
            color_ms,
            _elapsed_ms(total_start),
        )

        return result

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
        self._current_color_params = {}
    
    def clear_image(self) -> None:
        """Clear the current image."""
        self._worker.clear_image()
    
    def update_adjustments(
        self,
        exposure_params: Optional[Dict[str, float]] = None,
        color_params: Optional[Dict[str, float]] = None
    ) -> int:
        """Update adjustments and request preview processing.
        
        Args:
            exposure_params: New exposure parameters
            color_params: New color parameters
            
        Returns:
            Request ID
        """
        if exposure_params is not None:
            self._current_exposure_params = exposure_params
        if color_params is not None:
            self._current_color_params = color_params
        
        return self._worker.submit_preview_request(
            self._current_exposure_params,
            self._current_color_params
        )
    
    def finalize_adjustments(self) -> int:
        """Request full-resolution processing with current adjustments.
        
        Returns:
            Request ID
        """
        return self._worker.submit_final_request(
            self._current_exposure_params,
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
