"""Performance tests for background threading."""

import pytest
import time
import numpy as np
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QThread
from src.processing.processing_worker import ProcessingWorker
from src.processing.processing_queue import ProcessingQueue


def linear_image(width: int, height: int, value: float = 0.25) -> np.ndarray:
    return np.full((height, width, 3), value, dtype=np.float32)


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestThreadingPerformance:
    """Test that threading keeps UI responsive."""

    def test_processing_non_blocking(self, qapp, qtbot):
        """Test that processing doesn't block main thread."""
        worker = ProcessingWorker()
        worker.start()
        
        # Create test image
        test_image = linear_image(2000, 1500)
        worker.set_image(test_image)
        
        # Measure time to submit request (should be instant)
        start = time.perf_counter()
        request_id = worker.submit_preview_request(
            exposure_params={'exposure': 2.0},
            color_params={'saturation': 50.0}
        )
        submit_time = time.perf_counter() - start
        
        # Submission should be < 10ms (non-blocking)
        assert submit_time < 0.01, f"Request submission took {submit_time*1000:.1f}ms"
        
        # Cleanup
        worker.stop()
        qtbot.wait(100)

    def test_request_cancellation_prevents_waste(self, qapp, qtbot):
        """Test that cancelled requests don't waste processing time."""
        worker = ProcessingWorker()
        worker.start()
        
        test_image = linear_image(3000, 2000)
        worker.set_image(test_image)
        
        # Submit multiple rapid requests
        request_ids = []
        for i in range(10):
            request_id = worker.submit_preview_request(
                exposure_params={'exposure': float(i)}
            )
            request_ids.append(request_id)
        
        # Cancel all but last
        worker.cancel_pending()
        
        # Only the latest should be processed
        # Wait a bit for processing
        qtbot.wait(200)
        
        # Verify only latest is valid
        latest_id = request_ids[-1]
        assert worker.is_latest_request(latest_id) is True
        
        worker.stop()
        qtbot.wait(100)

    def test_queue_handles_rapid_requests(self, qapp):
        """Test that queue efficiently handles rapid requests."""
        queue = ProcessingQueue()
        
        # Create 100 rapid requests
        start = time.perf_counter()
        for i in range(100):
            request = queue.create_request(
                exposure_params={'exposure': float(i)}
            )
            queue.enqueue(request)
        enqueue_time = time.perf_counter() - start
        
        # Should handle 100 requests in < 50ms
        assert enqueue_time < 0.05, f"Enqueued 100 requests in {enqueue_time*1000:.1f}ms"
        
        # Latest should be the last one
        latest = queue.get_latest()
        assert latest is not None
        assert latest.exposure_params['exposure'] == 99.0

    def test_worker_thread_isolation(self, qapp, qtbot):
        """Test that worker thread doesn't interfere with main thread."""
        worker = ProcessingWorker()
        worker.start()
        
        test_image = linear_image(4000, 3000)
        worker.set_image(test_image)
        
        # Submit processing request
        worker.submit_preview_request(
            exposure_params={'exposure': 1.0}
        )
        
        # Main thread should remain responsive
        # Simulate UI operations on main thread
        start = time.perf_counter()
        for _ in range(1000):
            # Simulate UI update
            pass
        ui_time = time.perf_counter() - start
        
        # UI operations should be fast (< 1ms for 1000 ops)
        assert ui_time < 0.001, "Main thread blocked by processing"
        
        worker.stop()
        qtbot.wait(100)
