"""Processing request queue with cancellation support."""

from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from threading import Lock
from collections import deque
import time


@dataclass
class ProcessingRequest:
    """Represents a request to process an image.
    
    Attributes:
        request_id: Unique identifier for this request
        exposure_params: Exposure adjustment parameters
        color_params: Color adjustment parameters
        use_proxy: Whether to process proxy (True) or full-res (False)
        timestamp: When the request was created
        cancelled: Whether this request has been cancelled
    """
    request_id: int
    exposure_params: Dict[str, float] = field(default_factory=dict)
    color_params: Dict[str, float] = field(default_factory=dict)
    use_proxy: bool = True
    timestamp: float = field(default_factory=time.time)
    cancelled: bool = False
    
    def cancel(self) -> None:
        """Mark this request as cancelled."""
        self.cancelled = True
    
    def is_stale(self, max_age_seconds: float = 1.0) -> bool:
        """Check if this request is too old to be relevant.
        
        Args:
            max_age_seconds: Maximum age before considered stale
            
        Returns:
            True if request is stale
        """
        return (time.time() - self.timestamp) > max_age_seconds
    
    def should_process(self) -> bool:
        """Check if this request should still be processed.
        
        Returns:
            True if request should be processed
        """
        return not self.cancelled and not self.is_stale()


class ProcessingQueue:
    """Thread-safe queue for processing requests with cancellation.
    
    This queue supports:
    - Adding new requests
    - Cancelling outdated requests
    - Getting the latest pending request
    - Auto-incrementing request IDs
    """
    
    def __init__(self, max_size: int = 100):
        """Initialize the processing queue.
        
        Args:
            max_size: Maximum queue size before dropping old requests
        """
        self._queue: deque[ProcessingRequest] = deque(maxlen=max_size)
        self._lock = Lock()
        self._next_id = 0
        self._latest_request_id = -1
    
    def create_request(
        self,
        exposure_params: Optional[Dict[str, float]] = None,
        color_params: Optional[Dict[str, float]] = None,
        use_proxy: bool = True
    ) -> ProcessingRequest:
        """Create a new processing request with auto-incremented ID.
        
        Args:
            exposure_params: Exposure adjustment parameters
            color_params: Color adjustment parameters
            use_proxy: Whether to use proxy image
            
        Returns:
            New ProcessingRequest
        """
        with self._lock:
            request = ProcessingRequest(
                request_id=self._next_id,
                exposure_params=exposure_params or {},
                color_params=color_params or {},
                use_proxy=use_proxy
            )
            self._next_id += 1
            return request
    
    def enqueue(self, request: ProcessingRequest) -> None:
        """Add a request to the queue.
        
        Also cancels any pending requests since they're now outdated.
        
        Args:
            request: The request to add
        """
        with self._lock:
            # Cancel all pending requests - only latest matters
            for pending in self._queue:
                pending.cancel()
            
            self._queue.append(request)
            self._latest_request_id = request.request_id
    
    def dequeue(self) -> Optional[ProcessingRequest]:
        """Get the next non-cancelled request.
        
        Skips cancelled requests.
        
        Returns:
            Next valid request, or None if queue is empty
        """
        with self._lock:
            while self._queue:
                request = self._queue.popleft()
                if request.should_process():
                    return request
            return None
    
    def get_latest(self) -> Optional[ProcessingRequest]:
        """Get the latest request, skipping all older ones.
        
        Returns:
            The most recent valid request, or None
        """
        with self._lock:
            latest = None
            while self._queue:
                request = self._queue.popleft()
                if request.should_process():
                    latest = request
            return latest
    
    def peek(self) -> Optional[ProcessingRequest]:
        """Peek at the next request without removing it.
        
        Returns:
            Next request, or None if empty
        """
        with self._lock:
            if self._queue:
                return self._queue[0]
            return None
    
    def clear(self) -> None:
        """Clear all pending requests."""
        with self._lock:
            for request in self._queue:
                request.cancel()
            self._queue.clear()
    
    def cancel_all(self) -> None:
        """Cancel all pending requests without removing them."""
        with self._lock:
            for request in self._queue:
                request.cancel()
    
    def is_empty(self) -> bool:
        """Check if the queue is empty.
        
        Returns:
            True if no pending requests
        """
        with self._lock:
            return len(self._queue) == 0
    
    def pending_count(self) -> int:
        """Get the count of pending (non-cancelled) requests.
        
        Returns:
            Number of pending requests
        """
        with self._lock:
            return sum(1 for r in self._queue if not r.cancelled)
    
    def is_latest(self, request_id: int) -> bool:
        """Check if a request ID is the latest one.
        
        Args:
            request_id: Request ID to check
            
        Returns:
            True if this is the latest request
        """
        with self._lock:
            return request_id == self._latest_request_id
    
    @property
    def latest_request_id(self) -> int:
        """Get the ID of the latest request."""
        with self._lock:
            return self._latest_request_id
