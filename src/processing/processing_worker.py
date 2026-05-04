"""Background processing worker using QThread.

Operates on the canonical pipeline format
(:data:`src.utils.color_pipeline.LinearImage`). Qt signals carry the
arrays as ``object`` payloads (Qt cannot statically type ndarrays).
"""

from typing import Dict, Optional

from PyQt6.QtCore import QMutex, QObject, QThread, QWaitCondition, pyqtSignal

from src.processing.processing_queue import ProcessingQueue, ProcessingRequest
from src.processing.proxy_manager import ProxyManager
from src.processors.color_processor import ColorProcessor
from src.processors.exposure_processor import ExposureProcessor
from src.utils.color_pipeline import LinearImage


class ProcessingWorker(QObject):
    """Worker that processes images in a background thread.
    
    This worker runs in a separate thread and processes image adjustment
    requests without blocking the UI. Results are communicated back via
    Qt signals which are thread-safe.
    
    Signals:
        processing_started: Emitted when processing begins (request_id)
        preview_ready: Emitted when proxy preview is ready (request_id, image)
        processing_complete: Emitted when full processing is done (request_id, image)
        error_occurred: Emitted on processing error (request_id, error_message)
    """
    
    processing_started = pyqtSignal(int)
    preview_ready = pyqtSignal(int, object)  # request_id, LinearImage
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
    
    def clear_image(self) -> None:
        """Clear the current image."""
        self._proxy_manager.clear()
        self._queue.clear()
    
    def submit_request(
        self,
        exposure_params: Optional[Dict[str, float]] = None,
        color_params: Optional[Dict[str, float]] = None,
        use_proxy: bool = True
    ) -> int:
        """Submit a processing request.
        
        Args:
            exposure_params: Exposure adjustment parameters
            color_params: Color adjustment parameters
            use_proxy: Whether to process proxy (fast) or full image
            
        Returns:
            Request ID for tracking
        """
        request = self._queue.create_request(
            exposure_params=exposure_params,
            color_params=color_params,
            use_proxy=use_proxy
        )
        self._queue.enqueue(request)
        
        # Wake up the worker thread
        self._condition.wakeOne()
        
        return request.request_id
    
    def submit_preview_request(
        self,
        exposure_params: Optional[Dict[str, float]] = None,
        color_params: Optional[Dict[str, float]] = None
    ) -> int:
        """Submit a preview (proxy) processing request.
        
        Convenience method for submitting proxy requests.
        
        Args:
            exposure_params: Exposure adjustment parameters
            color_params: Color adjustment parameters
            
        Returns:
            Request ID
        """
        return self.submit_request(exposure_params, color_params, use_proxy=True)
    
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
        try:
            self.processing_started.emit(request.request_id)
            
            # Get source image (proxy or full)
            if request.use_proxy:
                source = self._proxy_manager.get_proxy()
            else:
                source = self._proxy_manager.get_original()
            
            if source is None:
                self.error_occurred.emit(request.request_id, "No image available")
                return
            
            # Check if still valid before heavy processing
            if not request.should_process():
                return
            
            # Apply adjustments
            result = self._apply_adjustments(
                source,
                request.exposure_params,
                request.color_params
            )
            
            # Check again after processing
            if not request.should_process():
                return
            
            # Emit appropriate signal
            if request.use_proxy:
                self.preview_ready.emit(request.request_id, result)
            else:
                self.processing_complete.emit(request.request_id, result)
                
        except Exception as e:
            self.error_occurred.emit(request.request_id, str(e))
    
    def _apply_adjustments(
        self,
        image: LinearImage,
        exposure_params: Dict[str, float],
        color_params: Dict[str, float],
    ) -> LinearImage:
        """Apply exposure and color adjustments to a ``LinearImage``."""
        result = image.copy()

        if exposure_params and any(v != 0 for v in exposure_params.values()):
            result = self._exposure_processor.process(result, **exposure_params)

        if color_params and any(v != 0 for v in color_params.values()):
            result = self._color_processor.process(result, **color_params)

        return result


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
