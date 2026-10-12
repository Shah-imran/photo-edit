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


class TestProcessingWorkerCurve:
    """Tone curve threading through the worker's apply/cache-key paths."""

    def test_curve_params_reach_curve_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        calls = []

        def fake_process(image, **kwargs):
            calls.append(kwargs)
            return image

        monkeypatch.setattr(worker._curve_processor, "process", fake_process)

        request = ProcessingRequest(
            request_id=1,
            curve_params={"points": ((0.0, 0.0), (0.5, 0.7), (1.0, 1.0))},
            use_proxy=False,
        )
        worker._process_request(request)

        assert calls == [{"points": ((0.0, 0.0), (0.5, 0.7), (1.0, 1.0))}]

    def test_empty_curve_params_skip_curve_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        calls = []
        monkeypatch.setattr(
            worker._curve_processor, "process", lambda image, **kw: calls.append(kw)
        )

        request = ProcessingRequest(request_id=1, use_proxy=False)
        worker._process_request(request)

        assert calls == []

    def test_different_curve_params_produce_different_cache_keys(self):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        request_a = ProcessingRequest(
            request_id=1,
            curve_params={"points": ((0.0, 0.0), (1.0, 1.0))},
            use_proxy=True,
        )
        request_b = ProcessingRequest(
            request_id=2,
            curve_params={"points": ((0.0, 0.0), (0.5, 0.7), (1.0, 1.0))},
            use_proxy=True,
        )
        source = worker._proxy_manager.get_proxy(interactive=True)

        key_a = worker._cache_key(request_a, source)
        key_b = worker._cache_key(request_b, source)

        assert key_a != key_b


class TestProcessingWorkerWhiteBalance:
    """White balance threading through the worker's apply/cache-key paths."""

    def test_wb_params_reach_wb_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        calls = []

        def fake_process(image, **kwargs):
            calls.append(kwargs)
            return image

        monkeypatch.setattr(worker._wb_processor, "process", fake_process)

        request = ProcessingRequest(
            request_id=1,
            wb_params={"temperature": 30.0, "tint": -10.0},
            use_proxy=False,
        )
        worker._process_request(request)

        assert calls == [{"temperature": 30.0, "tint": -10.0}]

    def test_all_zero_wb_params_skip_wb_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        calls = []
        monkeypatch.setattr(
            worker._wb_processor, "process", lambda image, **kw: calls.append(kw)
        )

        request = ProcessingRequest(
            request_id=1,
            wb_params={"temperature": 0.0, "tint": 0.0},
            use_proxy=False,
        )
        worker._process_request(request)

        assert calls == []

    def test_different_wb_params_produce_different_cache_keys(self):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        request_a = ProcessingRequest(
            request_id=1, wb_params={"temperature": 0.0, "tint": 0.0}, use_proxy=True
        )
        request_b = ProcessingRequest(
            request_id=2, wb_params={"temperature": 30.0, "tint": 0.0}, use_proxy=True
        )
        source = worker._proxy_manager.get_proxy(interactive=True)

        key_a = worker._cache_key(request_a, source)
        key_b = worker._cache_key(request_b, source)

        assert key_a != key_b


class TestProcessingWorkerHslMixer:
    """HSL Color Mixer threading through the worker's apply/cache-key paths."""

    def test_hsl_params_reach_hsl_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        calls = []

        def fake_process(image, **kwargs):
            calls.append(kwargs)
            return image

        monkeypatch.setattr(worker._hsl_processor, "process", fake_process)

        request = ProcessingRequest(
            request_id=1,
            hsl_params={"red_sat": 40.0},
            use_proxy=False,
        )
        worker._process_request(request)

        assert calls == [{"red_sat": 40.0}]

    def test_all_zero_hsl_params_skip_hsl_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        calls = []
        monkeypatch.setattr(
            worker._hsl_processor, "process", lambda image, **kw: calls.append(kw)
        )

        request = ProcessingRequest(
            request_id=1,
            hsl_params={"red_sat": 0.0, "orange_hue": 0.0},
            use_proxy=False,
        )
        worker._process_request(request)

        assert calls == []

    def test_different_hsl_params_produce_different_cache_keys(self):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        request_a = ProcessingRequest(
            request_id=1, hsl_params={"red_sat": 0.0}, use_proxy=True
        )
        request_b = ProcessingRequest(
            request_id=2, hsl_params={"red_sat": 40.0}, use_proxy=True
        )
        source = worker._proxy_manager.get_proxy(interactive=True)

        key_a = worker._cache_key(request_a, source)
        key_b = worker._cache_key(request_b, source)

        assert key_a != key_b


class TestProcessingWorkerColorGrading:
    """Color Grading threading through the worker's apply/cache-key paths."""

    def test_color_grading_params_reach_color_grading_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        calls = []

        def fake_process(image, **kwargs):
            calls.append(kwargs)
            return image

        monkeypatch.setattr(worker._color_grading_processor, "process", fake_process)

        request = ProcessingRequest(
            request_id=1,
            color_grading_params={"shadows_sat": 40.0},
            use_proxy=False,
        )
        worker._process_request(request)

        assert calls == [{"shadows_sat": 40.0}]

    def test_empty_color_grading_params_skip_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        calls = []
        monkeypatch.setattr(
            worker._color_grading_processor,
            "process",
            lambda image, **kw: calls.append(kw),
        )

        request = ProcessingRequest(
            request_id=1,
            color_grading_params={},
            use_proxy=False,
        )
        worker._process_request(request)

        assert calls == []

    def test_different_color_grading_params_produce_different_cache_keys(self):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        request_a = ProcessingRequest(
            request_id=1, color_grading_params={"shadows_sat": 0.0}, use_proxy=True
        )
        request_b = ProcessingRequest(
            request_id=2, color_grading_params={"shadows_sat": 40.0}, use_proxy=True
        )
        source = worker._proxy_manager.get_proxy(interactive=True)

        key_a = worker._cache_key(request_a, source)
        key_b = worker._cache_key(request_b, source)

        assert key_a != key_b


class TestProcessingWorkerTexture:
    def test_texture_params_reach_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._texture_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1, texture_params={"texture": 40.0}, use_proxy=False
        ))
        assert calls == [{"texture": 40.0}]

    def test_zero_texture_skips_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._texture_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1, texture_params={"texture": 0.0}, use_proxy=False
        ))
        assert calls == []


class TestProcessingWorkerClarity:
    def test_clarity_params_reach_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._clarity_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1, clarity_params={"clarity": 40.0}, use_proxy=False
        ))
        assert calls == [{"clarity": 40.0}]

    def test_zero_clarity_skips_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._clarity_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1, clarity_params={"clarity": 0.0}, use_proxy=False
        ))
        assert calls == []


class TestProcessingWorkerDehaze:
    def test_dehaze_params_reach_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._dehaze_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1, dehaze_params={"dehaze": 40.0}, use_proxy=False
        ))
        assert calls == [{"dehaze": 40.0}]

    def test_zero_dehaze_skips_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._dehaze_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1, dehaze_params={"dehaze": 0.0}, use_proxy=False
        ))
        assert calls == []


class TestProcessingWorkerVignette:
    def test_vignette_params_reach_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._vignette_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1, vignette_params={"vignette": 40.0}, use_proxy=False
        ))
        assert calls == [{"vignette": 40.0}]

    def test_zero_vignette_skips_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._vignette_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1, vignette_params={"vignette": 0.0}, use_proxy=False
        ))
        assert calls == []


class TestProcessingWorkerGrain:
    def test_grain_params_reach_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._grain_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1, grain_params={"grain": 40.0}, use_proxy=False
        ))
        assert calls == [{"grain": 40.0}]

    def test_zero_grain_skips_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._grain_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1, grain_params={"grain": 0.0}, use_proxy=False
        ))
        assert calls == []

    def test_different_grain_params_produce_different_cache_keys(self):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        request_a = ProcessingRequest(
            request_id=1, grain_params={"grain": 0.0}, use_proxy=True
        )
        request_b = ProcessingRequest(
            request_id=2, grain_params={"grain": 40.0}, use_proxy=True
        )
        source = worker._proxy_manager.get_proxy(interactive=True)

        key_a = worker._cache_key(request_a, source)
        key_b = worker._cache_key(request_b, source)

        assert key_a != key_b


class TestProcessingWorkerSharpening:
    def test_sharpening_params_reach_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._sharpening_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1, sharpening_params={"sharpening": 40.0}, use_proxy=False
        ))
        assert calls == [{"sharpening": 40.0}]

    def test_zero_sharpening_skips_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._sharpening_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1, sharpening_params={"sharpening": 0.0}, use_proxy=False
        ))
        assert calls == []

    def test_different_sharpening_params_produce_different_cache_keys(self):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        request_a = ProcessingRequest(
            request_id=1, sharpening_params={"sharpening": 0.0}, use_proxy=True
        )
        request_b = ProcessingRequest(
            request_id=2, sharpening_params={"sharpening": 40.0}, use_proxy=True
        )
        source = worker._proxy_manager.get_proxy(interactive=True)

        key_a = worker._cache_key(request_a, source)
        key_b = worker._cache_key(request_b, source)

        assert key_a != key_b


class TestProcessingWorkerLuminanceNR:
    def test_luminance_nr_params_reach_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._luminance_nr_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1,
            luminance_nr_params={"luminance_nr": 40.0},
            use_proxy=False,
        ))
        assert calls == [{"luminance_nr": 40.0}]

    def test_zero_luminance_nr_skips_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._luminance_nr_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1,
            luminance_nr_params={"luminance_nr": 0.0},
            use_proxy=False,
        ))
        assert calls == []

    def test_different_luminance_nr_params_produce_different_cache_keys(self):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        request_a = ProcessingRequest(
            request_id=1, luminance_nr_params={"luminance_nr": 0.0}, use_proxy=True
        )
        request_b = ProcessingRequest(
            request_id=2, luminance_nr_params={"luminance_nr": 40.0}, use_proxy=True
        )
        source = worker._proxy_manager.get_proxy(interactive=True)

        key_a = worker._cache_key(request_a, source)
        key_b = worker._cache_key(request_b, source)

        assert key_a != key_b


class TestProcessingWorkerColorNR:
    def test_color_nr_params_reach_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._color_nr_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1,
            color_nr_params={"color_nr": 40.0},
            use_proxy=False,
        ))
        assert calls == [{"color_nr": 40.0}]

    def test_zero_color_nr_skips_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._color_nr_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1,
            color_nr_params={"color_nr": 0.0},
            use_proxy=False,
        ))
        assert calls == []

    def test_different_color_nr_params_produce_different_cache_keys(self):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        request_a = ProcessingRequest(
            request_id=1, color_nr_params={"color_nr": 0.0}, use_proxy=True
        )
        request_b = ProcessingRequest(
            request_id=2, color_nr_params={"color_nr": 40.0}, use_proxy=True
        )
        source = worker._proxy_manager.get_proxy(interactive=True)

        key_a = worker._cache_key(request_a, source)
        key_b = worker._cache_key(request_b, source)

        assert key_a != key_b


class TestProcessingWorkerRemoveCA:
    def test_remove_ca_params_reach_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._remove_ca_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1,
            remove_ca_params={"remove_ca": 40.0},
            use_proxy=False,
        ))
        assert calls == [{"remove_ca": 40.0}]

    def test_zero_remove_ca_skips_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._remove_ca_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1,
            remove_ca_params={"remove_ca": 0.0},
            use_proxy=False,
        ))
        assert calls == []

    def test_different_remove_ca_params_produce_different_cache_keys(self):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        request_a = ProcessingRequest(
            request_id=1, remove_ca_params={"remove_ca": 0.0}, use_proxy=True
        )
        request_b = ProcessingRequest(
            request_id=2, remove_ca_params={"remove_ca": 40.0}, use_proxy=True
        )
        source = worker._proxy_manager.get_proxy(interactive=True)

        key_a = worker._cache_key(request_a, source)
        key_b = worker._cache_key(request_b, source)

        assert key_a != key_b
