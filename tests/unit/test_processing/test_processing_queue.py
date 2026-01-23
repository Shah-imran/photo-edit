"""Unit tests for ProcessingQueue."""

import pytest
import time
from src.processing.processing_queue import ProcessingRequest, ProcessingQueue


class TestProcessingRequest:
    """Test cases for ProcessingRequest class."""

    def test_request_initialization(self):
        """Test ProcessingRequest can be initialized."""
        request = ProcessingRequest(
            request_id=1,
            exposure_params={'exposure': 1.0},
            color_params={'saturation': 50.0}
        )
        
        assert request.request_id == 1
        assert request.exposure_params == {'exposure': 1.0}
        assert request.cancelled is False

    def test_request_cancel(self):
        """Test cancelling a request."""
        request = ProcessingRequest(request_id=1)
        request.cancel()
        
        assert request.cancelled is True
        assert request.should_process() is False

    def test_request_is_stale(self):
        """Test stale request detection."""
        request = ProcessingRequest(request_id=1)
        # Set timestamp to 2 seconds ago
        request.timestamp = time.time() - 2.0
        
        assert request.is_stale(max_age_seconds=1.0) is True
        assert request.should_process() is False

    def test_request_not_stale(self):
        """Test fresh request."""
        request = ProcessingRequest(request_id=1)
        
        assert request.is_stale(max_age_seconds=1.0) is False
        assert request.should_process() is True


class TestProcessingQueue:
    """Test cases for ProcessingQueue class."""

    def test_queue_initialization(self):
        """Test ProcessingQueue can be initialized."""
        queue = ProcessingQueue()
        assert queue is not None
        assert queue.is_empty() is True

    def test_create_request(self):
        """Test creating a request."""
        queue = ProcessingQueue()
        request = queue.create_request(
            exposure_params={'exposure': 1.0}
        )
        
        assert request.request_id == 0
        assert request.exposure_params == {'exposure': 1.0}

    def test_create_request_increments_id(self):
        """Test request IDs are auto-incremented."""
        queue = ProcessingQueue()
        r1 = queue.create_request()
        r2 = queue.create_request()
        r3 = queue.create_request()
        
        assert r1.request_id == 0
        assert r2.request_id == 1
        assert r3.request_id == 2

    def test_enqueue(self):
        """Test enqueueing a request."""
        queue = ProcessingQueue()
        request = queue.create_request()
        
        queue.enqueue(request)
        
        assert queue.is_empty() is False
        assert queue.pending_count() == 1

    def test_enqueue_cancels_previous(self):
        """Test enqueueing cancels previous requests."""
        queue = ProcessingQueue()
        r1 = queue.create_request()
        r2 = queue.create_request()
        
        queue.enqueue(r1)
        queue.enqueue(r2)
        
        assert r1.cancelled is True
        assert r2.cancelled is False

    def test_dequeue(self):
        """Test dequeueing a request."""
        queue = ProcessingQueue()
        request = queue.create_request()
        queue.enqueue(request)
        
        result = queue.dequeue()
        
        assert result is not None
        assert result.request_id == request.request_id
        assert queue.is_empty() is True

    def test_dequeue_empty(self):
        """Test dequeueing from empty queue."""
        queue = ProcessingQueue()
        
        result = queue.dequeue()
        
        assert result is None

    def test_dequeue_skips_cancelled(self):
        """Test dequeue skips cancelled requests."""
        queue = ProcessingQueue()
        r1 = queue.create_request()
        r2 = queue.create_request()
        
        # Manually add without auto-cancel for testing
        queue._queue.append(r1)
        r1.cancel()
        queue._queue.append(r2)
        
        result = queue.dequeue()
        
        assert result.request_id == r2.request_id

    def test_get_latest(self):
        """Test getting latest request."""
        queue = ProcessingQueue()
        r1 = queue.create_request()
        r2 = queue.create_request()
        r3 = queue.create_request()
        
        # Manually add all
        queue._queue.append(r1)
        queue._queue.append(r2)
        queue._queue.append(r3)
        
        result = queue.get_latest()
        
        assert result.request_id == r3.request_id
        assert queue.is_empty() is True

    def test_clear(self):
        """Test clearing the queue."""
        queue = ProcessingQueue()
        r1 = queue.create_request()
        queue.enqueue(r1)
        
        queue.clear()
        
        assert queue.is_empty() is True
        assert r1.cancelled is True

    def test_is_latest(self):
        """Test checking if request is latest."""
        queue = ProcessingQueue()
        r1 = queue.create_request()
        r2 = queue.create_request()
        
        queue.enqueue(r1)
        assert queue.is_latest(r1.request_id) is True
        
        queue.enqueue(r2)
        assert queue.is_latest(r1.request_id) is False
        assert queue.is_latest(r2.request_id) is True
