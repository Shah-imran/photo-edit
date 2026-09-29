"""Unit tests for CurveProcessor (master RGB tone curve)."""

import numpy as np
import pytest

from src.processors.curve_processor import CurveProcessor


@pytest.fixture
def processor():
    return CurveProcessor()


def _solid(value, shape=(2, 2, 3)):
    return np.full(shape, value, dtype=np.float32)


class TestIdentity:
    def test_no_points_is_identity(self, processor):
        rgb = np.random.rand(4, 4, 3).astype(np.float32)
        result = processor.process(rgb)
        np.testing.assert_array_equal(result, rgb)

    def test_default_straight_line_is_identity(self, processor):
        rgb = np.random.rand(4, 4, 3).astype(np.float32)
        result = processor.process(rgb, points=[(0.0, 0.0), (1.0, 1.0)])
        np.testing.assert_array_equal(result, rgb)

    def test_returns_new_array_not_same_object(self, processor):
        rgb = _solid(0.5)
        result = processor.process(rgb)
        assert result is not rgb


class TestBrightenDarken:
    def test_raised_midpoint_brightens_midtone(self, processor):
        mid = _solid(0.5)
        result = processor.process(mid, points=[(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)])
        assert result[0, 0, 0] > mid[0, 0, 0]

    def test_lowered_midpoint_darkens_midtone(self, processor):
        mid = _solid(0.5)
        result = processor.process(mid, points=[(0.0, 0.0), (0.5, 0.3), (1.0, 1.0)])
        assert result[0, 0, 0] < mid[0, 0, 0]

    def test_endpoints_stay_black_and_white(self, processor):
        black = _solid(0.0)
        white = _solid(1.0)
        points = [(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)]
        result_black = processor.process(black, points=points)
        result_white = processor.process(white, points=points)
        np.testing.assert_allclose(result_black, black, atol=1e-5)
        np.testing.assert_allclose(result_white, white, atol=1e-5)


class TestOutputProperties:
    def test_dtype_stays_float32(self, processor):
        rgb = _solid(0.5)
        result = processor.process(rgb, points=[(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)])
        assert result.dtype == np.float32

    def test_shape_preserved(self, processor):
        rgb = np.random.rand(6, 5, 3).astype(np.float32)
        result = processor.process(rgb, points=[(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)])
        assert result.shape == rgb.shape


class TestRgbaPassthrough:
    def test_alpha_channel_untouched(self, processor):
        rgba = np.full((2, 2, 4), 0.5, dtype=np.float32)
        rgba[..., 3] = 0.3
        result = processor.process(
            rgba, points=[(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)]
        )
        np.testing.assert_array_equal(result[..., 3], rgba[..., 3])
