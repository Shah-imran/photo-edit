"""Full-resolution export work off the UI thread.

Export used to render the whole photo synchronously on the UI thread
before the Export dialog could even open (seconds at 24 MP with a few
adjustments), then encode the file on the UI thread too. A
:class:`BackgroundTask` runs such work on a thread; the dialog opens at
once and the render proceeds while the user picks settings. See
docs/planning/PERFORMANCE_OVERHAUL.md (Phase 4).
"""

from __future__ import annotations

import copy
import logging
import threading
from time import perf_counter
from typing import Any, Callable, Dict, Optional

from PyQt6.QtCore import QEventLoop, QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QProgressDialog, QWidget

from src.utils.color_pipeline import LinearImage

logger = logging.getLogger(__name__)


class BackgroundTask(QObject):
    """Run ``fn()`` on a background thread; deliver its result on the UI
    thread via ``finished`` (or ``failed`` with a message).

    The thread only emits the private ``_delivered``/``_errored`` signals,
    which reach this object (living on the UI thread) queued; the public
    signals are re-emitted from there. So every listener -- including plain
    functions and lambdas, which PyQt would otherwise call on the emitting
    thread -- runs on the UI thread.
    """

    finished = pyqtSignal(object)
    failed = pyqtSignal(str)
    _delivered = pyqtSignal(object)
    _errored = pyqtSignal(str)

    def __init__(self, fn: Callable[[], Any], name: str = "task", parent: Optional[QObject] = None):
        super().__init__(parent)
        self._fn = fn
        self._name = name
        self._done = False
        self._result: Any = None
        self._error: Optional[str] = None
        self._delivered.connect(self._mark_finished)
        self._errored.connect(self._mark_failed)

    def start(self) -> "BackgroundTask":
        threading.Thread(target=self._run, name=self._name, daemon=True).start()
        return self

    def is_done(self) -> bool:
        """True once the result (or an error) has been delivered."""
        return self._done

    @property
    def result(self) -> Any:
        return self._result

    @property
    def error(self) -> Optional[str]:
        return self._error

    def _run(self) -> None:
        start = perf_counter()
        try:
            value = self._fn()
        except Exception as exc:  # reported to the UI, never raised there
            logger.exception("Background task %s failed", self._name)
            self._errored.emit(str(exc) or type(exc).__name__)
            return
        logger.info(
            "PERF background.%s total_ms=%.0f", self._name, (perf_counter() - start) * 1000.0
        )
        self._delivered.emit(value)

    def _mark_finished(self, value: Any) -> None:
        self._result = value
        self._done = True
        self.finished.emit(value)

    def _mark_failed(self, message: str) -> None:
        self._error = message
        self._done = True
        self.failed.emit(message)

    def wait(self, parent: Optional[QWidget] = None, label: str = "Working…") -> Any:
        """Wait for the result while keeping the UI responsive.

        Spins a local event loop (the window keeps painting) and shows a
        cancellable busy dialog if the wait takes noticeable time. Returns
        the result, or None if the task failed or the user cancelled.
        """
        if not self._done:
            loop = QEventLoop()
            self.finished.connect(loop.quit)
            self.failed.connect(loop.quit)
            progress = QProgressDialog(label, "Cancel", 0, 0, parent)
            progress.setWindowTitle("Export")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(200)
            progress.canceled.connect(loop.quit)
            # Re-check once the loop runs, in case the result just landed.
            QTimer.singleShot(0, lambda: self._done and loop.quit())
            loop.exec()
            cancelled = progress.wasCanceled()
            progress.close()
            progress.deleteLater()
            if cancelled and not self._done:
                return None
        return None if self._error is not None else self._result


def start_export_render(
    original: LinearImage,
    render_kwargs: Dict[str, Any],
    apply_crop: bool = True,
    post: Optional[Callable[[LinearImage], Any]] = None,
    parent: Optional[QObject] = None,
) -> BackgroundTask:
    """Render a snapshot of an edit at full resolution on a thread.

    ``post`` (optional) runs on the same thread with the rendered image --
    e.g. encoding and writing the file -- and its return value becomes
    the task's result; without it the result is the image.
    """
    # Deep copy: the snapshot must not follow later slider moves.
    kwargs = copy.deepcopy(dict(render_kwargs))
    if not apply_crop:
        kwargs["crop_params"] = {}

    def render():
        # Imported here: processing_worker pulls in every processor.
        from src.processing.processing_worker import ProcessingWorker

        image = ProcessingWorker()._apply_adjustments(original, **kwargs)
        return post(image) if post is not None else image

    return BackgroundTask(render, name="export_render", parent=parent).start()
