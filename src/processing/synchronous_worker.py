"""A ProcessingWorker that renders on the calling thread, immediately.

``ImageController(use_threading=False)`` uses it so the non-threaded mode
runs the very same code path as the app -- async-style render requests,
display frames, settings-only history, detail renders -- just without a
thread. There used to be a separate synchronous implementation of every
edit flow, which the app never ran and which had drifted (see
docs/planning/TEST_SUITE_AUDIT.md).
"""

from __future__ import annotations

from src.processing.processing_worker import ProcessingWorker


class SynchronousProcessingWorker(ProcessingWorker):
    """Processes each request inside ``submit_request``."""

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def is_running(self) -> bool:
        # Not threaded: set_image installs the source immediately.
        return False

    def submit_request(self, *args, **kwargs) -> int:
        request_id = super().submit_request(*args, **kwargs)
        request = self._queue.get_latest()
        if request is not None and request.should_process():
            self._process_request(request)
        return request_id
