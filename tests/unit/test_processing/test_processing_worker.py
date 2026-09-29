"""Unit tests for ProcessingWorker internals."""

import numpy as np

from src.processing.display_frame import DisplayFrame
from src.processing.processing_queue import ProcessingRequest
from src.processing.processing_worker import ProcessingWorker


def _linear_image(width: int = 1200, height: int = 800) -> np.ndarray:
    return np.full((height, width, 3), 0.25, dtype=np.float32)


class TestProcessingWorkerCache:
    """Preview render cache behavior."""

    def test_preview_request_reuses_cached_result(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        emitted = []
        worker.preview_ready.connect(
            lambda request_id, image: emitted.append((request_id, image))
        )

        calls = []

        def fake_process(image, **kwargs):
            calls.append(kwargs)
            return image + np.float32(0.1)

        monkeypatch.setattr(worker._exposure_processor, "process", fake_process)

        first = ProcessingRequest(
            request_id=1,
            exposure_params={"exposure": 1.0},
            use_proxy=True,
            interactive_preview=True,
        )
        second = ProcessingRequest(
            request_id=2,
            exposure_params={"exposure": 1.0},
            use_proxy=True,
            interactive_preview=True,
        )

        worker._process_request(first)
        worker._process_request(second)

        assert len(calls) == 1
        assert [request_id for request_id, _ in emitted] == [1, 2]
        assert all(isinstance(frame, DisplayFrame) for _, frame in emitted)
        assert all(frame.rgb.dtype == np.uint8 for _, frame in emitted)
        assert all(frame.linear_image is not None for _, frame in emitted)

    def test_full_resolution_request_is_not_cached(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        calls = []

        def fake_process(image, **kwargs):
            calls.append(kwargs)
            return image + np.float32(0.1)

        monkeypatch.setattr(worker._exposure_processor, "process", fake_process)

        first = ProcessingRequest(
            request_id=1,
            exposure_params={"exposure": 1.0},
            use_proxy=False,
        )
        second = ProcessingRequest(
            request_id=2,
            exposure_params={"exposure": 1.0},
            use_proxy=False,
        )

        worker._process_request(first)
        worker._process_request(second)

        assert len(calls) == 2

    def test_preview_request_emits_display_frame_for_quality_tier(self):
        """Preview requests should arrive ready for Qt display presentation."""
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        emitted = []
        worker.preview_ready.connect(
            lambda request_id, frame: emitted.append((request_id, frame))
        )

        request = ProcessingRequest(
            request_id=3,
            exposure_params={"exposure": 0.5},
            use_proxy=True,
            interactive_preview=False,
        )

        worker._process_request(request)

        assert len(emitted) == 1
        request_id, frame = emitted[0]
        assert request_id == 3
        assert isinstance(frame, DisplayFrame)
        assert frame.tier == "quality"
        assert frame.rgb.dtype == np.uint8
        assert frame.rgb.flags["C_CONTIGUOUS"] is True
        assert frame.linear_image is not None
