"""Unit tests for ProcessingWorker internals."""

import numpy as np

from src.processing.display_frame import DisplayFrame
from src.processing.processing_queue import ProcessingRequest
from src.processing.processing_worker import ProcessingWorker
from src.processing.proxy_manager import ProxyManager
from src.processors.exposure_processor import ExposureProcessor
from src.processors.healing_processor import HealingProcessor


def _linear_image(width: int = 1200, height: int = 800) -> np.ndarray:
    return np.full((height, width, 3), 0.25, dtype=np.float32)


class TestProcessingWorkerProxySizePreferences:
    """Constructor wiring for the two optional proxy-size overrides."""

    def test_default_construction_uses_proxy_manager_defaults(self):
        worker = ProcessingWorker()
        assert worker.proxy_manager.max_size == ProxyManager.DEFAULT_PROXY_SIZE
        assert (
            worker.proxy_manager.interactive_max_size
            == ProxyManager.DEFAULT_INTERACTIVE_PROXY_SIZE
        )

    def test_explicit_sizes_are_passed_to_proxy_manager(self):
        worker = ProcessingWorker(
            proxy_max_size=2000, interactive_proxy_max_size=900
        )
        assert worker.proxy_manager.max_size == 2000
        assert worker.proxy_manager.interactive_max_size == 900

    def test_none_sizes_fall_back_to_proxy_manager_defaults(self):
        worker = ProcessingWorker(
            proxy_max_size=None, interactive_proxy_max_size=None
        )
        assert worker.proxy_manager.max_size == ProxyManager.DEFAULT_PROXY_SIZE
        assert (
            worker.proxy_manager.interactive_max_size
            == ProxyManager.DEFAULT_INTERACTIVE_PROXY_SIZE
        )


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


class TestProcessingWorkerDefringe:
    def test_defringe_params_reach_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._defringe_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1,
            defringe_params={"defringe": 40.0},
            use_proxy=False,
        ))
        assert calls == [{"defringe": 40.0}]

    def test_zero_defringe_skips_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._defringe_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1,
            defringe_params={"defringe": 0.0},
            use_proxy=False,
        ))
        assert calls == []

    def test_different_defringe_params_produce_different_cache_keys(self):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        request_a = ProcessingRequest(
            request_id=1, defringe_params={"defringe": 0.0}, use_proxy=True
        )
        request_b = ProcessingRequest(
            request_id=2, defringe_params={"defringe": 40.0}, use_proxy=True
        )
        source = worker._proxy_manager.get_proxy(interactive=True)

        key_a = worker._cache_key(request_a, source)
        key_b = worker._cache_key(request_b, source)

        assert key_a != key_b


class TestProcessingWorkerStraighten:
    def test_straighten_params_reach_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._straighten_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1,
            straighten_params={"straighten": 10.0},
            use_proxy=False,
        ))
        assert calls == [{"straighten": 10.0}]

    def test_zero_straighten_skips_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._straighten_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1,
            straighten_params={"straighten": 0.0},
            use_proxy=False,
        ))
        assert calls == []

    def test_different_straighten_params_produce_different_cache_keys(self):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        request_a = ProcessingRequest(
            request_id=1, straighten_params={"straighten": 0.0}, use_proxy=True
        )
        request_b = ProcessingRequest(
            request_id=2, straighten_params={"straighten": 10.0}, use_proxy=True
        )
        source = worker._proxy_manager.get_proxy(interactive=True)

        key_a = worker._cache_key(request_a, source)
        key_b = worker._cache_key(request_b, source)

        assert key_a != key_b


class TestProcessingWorkerCrop:
    """Crop is applied strictly LAST, after Straighten -- the one
    deliberately shape-changing processor in this codebase. See
    docs/planning/implementation-notes/2026-10-13-crop-processor.md."""

    def test_crop_params_reach_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._crop_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1,
            crop_params={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.9},
            use_proxy=False,
        ))
        assert calls == [{"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.9}]

    def test_empty_crop_params_skips_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._crop_processor,
            "process",
            lambda image, **kwargs: calls.append(kwargs) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1,
            crop_params={},
            use_proxy=False,
        ))
        assert calls == []

    def test_crop_actually_shrinks_the_full_resolution_result(self):
        """Confirm the worker's real end-to-end pipeline (not a mocked
        processor) produces a genuinely smaller output for a real crop --
        the one deliberate shape change in this codebase."""
        worker = ProcessingWorker()
        source = _linear_image(width=100, height=80)
        worker.set_image(source)

        results = []
        worker.processing_complete.connect(lambda rid, image: results.append(image))
        worker._process_request(ProcessingRequest(
            request_id=1,
            crop_params={"x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.75},
            use_proxy=False,
        ))

        assert len(results) == 1
        assert results[0].shape != source.shape
        assert results[0].shape[0] < source.shape[0]
        assert results[0].shape[1] < source.shape[1]

    def test_different_crop_params_produce_different_cache_keys(self):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        request_a = ProcessingRequest(
            request_id=1, crop_params={}, use_proxy=True
        )
        request_b = ProcessingRequest(
            request_id=2,
            crop_params={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.9},
            use_proxy=True,
        )
        source = worker._proxy_manager.get_proxy(interactive=True)

        key_a = worker._cache_key(request_a, source)
        key_b = worker._cache_key(request_b, source)

        assert key_a != key_b


class TestProcessingWorkerMask:
    """Mask is applied after every other adjustment (including
    Straighten) and strictly BEFORE Crop. See
    docs/planning/implementation-notes/2026-10-13-mask-processor.md."""

    _MASK = {"type": "linear", "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0,
             "exposure": 1.0, "contrast": 0.0, "saturation": 0.0, "clarity": 0.0}

    def test_mask_params_reach_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._mask_processor,
            "process",
            lambda image, mask=None: calls.append(mask) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1,
            mask_params=self._MASK,
            use_proxy=False,
        ))
        assert calls == [self._MASK]

    def test_empty_mask_params_skips_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._mask_processor,
            "process",
            lambda image, mask=None: calls.append(mask) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1,
            mask_params={},
            use_proxy=False,
        ))
        assert calls == []

    def test_mask_actually_changes_the_full_resolution_result(self):
        """Confirm the worker's real end-to-end pipeline (not a mocked
        processor) produces a genuinely different output for a real
        mask, while preserving shape (mask never changes shape)."""
        worker = ProcessingWorker()
        source = _linear_image(width=100, height=80)
        worker.set_image(source)

        results = []
        worker.processing_complete.connect(lambda rid, image: results.append(image))
        worker._process_request(ProcessingRequest(
            request_id=1,
            mask_params=self._MASK,
            use_proxy=False,
        ))

        assert len(results) == 1
        assert results[0].shape == source.shape
        assert not (results[0] == source).all()

    def test_different_mask_params_produce_different_cache_keys(self):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        request_a = ProcessingRequest(
            request_id=1, mask_params={}, use_proxy=True
        )
        request_b = ProcessingRequest(
            request_id=2,
            mask_params=self._MASK,
            use_proxy=True,
        )
        source = worker._proxy_manager.get_proxy(interactive=True)

        key_a = worker._cache_key(request_a, source)
        key_b = worker._cache_key(request_b, source)

        assert key_a != key_b

    def test_mask_applied_before_crop(self):
        """Pipeline-order regression: with both a mask and a crop
        active, the final shape must reflect the crop (mask never
        changes shape, so this just confirms crop still runs and mask
        doesn't interfere with it)."""
        worker = ProcessingWorker()
        source = _linear_image(width=100, height=80)
        worker.set_image(source)

        results = []
        worker.processing_complete.connect(lambda rid, image: results.append(image))
        worker._process_request(ProcessingRequest(
            request_id=1,
            mask_params=self._MASK,
            crop_params={"x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.75},
            use_proxy=False,
        ))

        assert len(results) == 1
        assert results[0].shape[0] < source.shape[0]
        assert results[0].shape[1] < source.shape[1]


class TestProcessingWorkerHealing:
    """Healing is applied FIRST, before every other adjustment (including
    Exposure, previously the pipeline's first step) and strictly before
    Mask/Crop. See
    docs/planning/implementation-notes/2026-10-13-healing-processor.md."""

    _HEAL_SPOT = {
        "mode": "clone",
        "dst_x": 0.75,
        "dst_y": 0.25,
        "src_x": 0.25,
        "src_y": 0.75,
        "radius": 0.1,
        "feather": 0.0,
        "opacity": 1.0,
    }

    def test_healing_params_reach_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._healing_processor,
            "process",
            lambda image, heal_spots=None: calls.append(heal_spots) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1,
            healing_params={"heal_spots": [self._HEAL_SPOT]},
            use_proxy=False,
        ))
        assert calls == [[self._HEAL_SPOT]]

    def test_empty_healing_params_skips_processor(self, monkeypatch):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())
        calls = []
        monkeypatch.setattr(
            worker._healing_processor,
            "process",
            lambda image, heal_spots=None: calls.append(heal_spots) or image,
        )
        worker._process_request(ProcessingRequest(
            request_id=1,
            healing_params={},
            use_proxy=False,
        ))
        assert calls == []

    def test_healing_actually_changes_the_full_resolution_result(self):
        """Confirm the worker's real end-to-end pipeline (not a mocked
        processor) produces a genuinely different, but same-shape,
        output for a real heal spot."""
        worker = ProcessingWorker()
        source = _linear_image(width=100, height=80)
        source = source.copy()
        # Paint the source patch where this class's _HEAL_SPOT samples
        # from (src_x=0.25, src_y=0.75 -> pixel (25, 60)).
        source[55:65, 20:30] = 0.9
        worker.set_image(source)

        results = []
        worker.processing_complete.connect(lambda rid, image: results.append(image))
        worker._process_request(ProcessingRequest(
            request_id=1,
            healing_params={"heal_spots": [self._HEAL_SPOT]},
            use_proxy=False,
        ))

        assert len(results) == 1
        assert results[0].shape == source.shape
        assert not (results[0] == source).all()

    def test_different_healing_params_produce_different_cache_keys(self):
        worker = ProcessingWorker()
        worker.set_image(_linear_image())

        request_a = ProcessingRequest(
            request_id=1, healing_params={}, use_proxy=True
        )
        request_b = ProcessingRequest(
            request_id=2,
            healing_params={"heal_spots": [self._HEAL_SPOT]},
            use_proxy=True,
        )
        source = worker._proxy_manager.get_proxy(interactive=True)

        key_a = worker._cache_key(request_a, source)
        key_b = worker._cache_key(request_b, source)

        assert key_a != key_b

    def test_healing_applied_before_mask_and_crop(self):
        """Pipeline-order regression: with healing, mask, and crop all
        active, the final shape must reflect the crop (healing/mask
        never change shape)."""
        worker = ProcessingWorker()
        source = _linear_image(width=100, height=80)
        source = source.copy()
        source[55:65, 20:30] = 0.9
        worker.set_image(source)

        mask = {
            "type": "linear", "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0,
            "exposure": 1.0, "contrast": 0.0, "saturation": 0.0, "clarity": 0.0,
        }

        results = []
        worker.processing_complete.connect(lambda rid, image: results.append(image))
        worker._process_request(ProcessingRequest(
            request_id=1,
            healing_params={"heal_spots": [self._HEAL_SPOT]},
            mask_params=mask,
            crop_params={"x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.75},
            use_proxy=False,
        ))

        assert len(results) == 1
        assert results[0].shape[0] < source.shape[0]
        assert results[0].shape[1] < source.shape[1]

    def test_healing_runs_before_exposure_contrast_in_real_pipeline(self):
        """Ordering regression: Healing must run BEFORE Exposure/Contrast
        in the real worker pipeline -- the one genuinely new
        architectural wrinkle in this slice (every prior Phase G/H/I/J
        processor so far was appended LATER in the chain).

        Verified with a feathered Clone spot (a genuinely PARTIAL
        per-pixel blend, not a 0/1 substitution) and a nonlinear
        Contrast adjustment -- the two orderings provably differ,
        because a nonlinear pointwise operation does not commute with a
        partial (feathered) blend. This is a concrete, falsifiable test:
        it fails if Healing is ever moved after Exposure in the pipeline.
        """
        width, height = 120, 100
        source = np.full((height, width, 3), 0.3, dtype=np.float32)
        source[10:30, 10:30] = 0.8  # distinct source patch

        worker = ProcessingWorker()
        worker.set_image(source)

        heal_spot = {
            "mode": "clone",
            "dst_x": 0.75,
            "dst_y": 0.75,
            "src_x": 0.1667,
            "src_y": 0.2,
            "radius": 0.15,
            # feather spans the whole radius, so every point strictly
            # inside the disk (other than the exact center) gets a
            # genuinely PARTIAL alpha blend, not a pure 0/1 substitution.
            "feather": 1.0,
            "opacity": 1.0,
        }
        contrast_params = {"exposure": 0.0, "contrast": 80.0, "brightness": 0.0}

        results = []
        worker.processing_complete.connect(lambda rid, image: results.append(image))
        worker._process_request(ProcessingRequest(
            request_id=1,
            exposure_params=contrast_params,
            healing_params={"heal_spots": [heal_spot]},
            use_proxy=False,
        ))
        assert len(results) == 1
        actual = results[0]

        # "Correct" order per this slice's design: heal, then contrast.
        correct_order = HealingProcessor().process(source.copy(), heal_spots=[heal_spot])
        correct_order = ExposureProcessor().process(correct_order, **contrast_params)

        # "Wrong" order a regression would produce: contrast, then heal.
        wrong_order = ExposureProcessor().process(source.copy(), **contrast_params)
        wrong_order = HealingProcessor().process(wrong_order, heal_spots=[heal_spot])

        dst_cx = int(round(0.75 * width))
        dst_cy = int(round(0.75 * height))
        radius_px = round(0.15 * min(width, height))
        # Sample off-center (inside the feather band, not at the exact
        # spot center where alpha==1.0 would make both orderings agree
        # trivially via pure substitution).
        sample_x = dst_cx + radius_px // 2
        sample_y = dst_cy

        np.testing.assert_allclose(
            actual[sample_y, sample_x],
            correct_order[sample_y, sample_x],
            atol=1e-5,
        )
        assert not np.allclose(
            actual[sample_y, sample_x],
            wrong_order[sample_y, sample_x],
            atol=1e-4,
        )
