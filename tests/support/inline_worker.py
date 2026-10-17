"""A ProcessingWorker that runs the real pipeline without a thread.

``ImageController(..., worker_factory=InlineProcessingWorker)`` exercises
the production (threaded) code path -- async render requests, display
frames, settings-only history, detail renders -- deterministically: each
request is processed on the next event-loop turn, in submission order,
exactly as the worker thread would deliver it.
"""

from __future__ import annotations

from PyQt6.QtCore import QTimer

from src.processing.processing_worker import ProcessingWorker


class InlineProcessingWorker(ProcessingWorker):
    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def is_running(self) -> bool:
        # Not threaded: set_image installs the source immediately.
        return False

    def submit_request(self, *args, **kwargs) -> int:
        request_id = super().submit_request(*args, **kwargs)
        QTimer.singleShot(0, self._drain)
        return request_id

    def _drain(self) -> None:
        if not self._running:
            return
        request = self._queue.get_latest()
        if request is not None and request.should_process():
            self._process_request(request)
