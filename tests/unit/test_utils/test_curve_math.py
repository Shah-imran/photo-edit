"""Unit tests for the tone-curve pure-math module."""

import numpy as np
import pytest

from src.utils.curve_math import (
    DEFAULT_CURVE_POINTS,
    build_curve_lut,
    compute_luminance_histogram,
    is_identity_curve,
    normalize_points,
)


class TestNormalizePoints:
    def test_none_returns_default(self):
        assert normalize_points(None) == DEFAULT_CURVE_POINTS

    def test_empty_returns_default(self):
        assert normalize_points([]) == DEFAULT_CURVE_POINTS

    def test_single_point_returns_default(self):
        assert normalize_points([(0.5, 0.5)]) == DEFAULT_CURVE_POINTS

    def test_sorts_by_x(self):
        result = normalize_points([(1.0, 1.0), (0.0, 0.0), (0.5, 0.7)])
        xs = [p[0] for p in result]
        assert xs == sorted(xs)

    def test_pins_endpoints_to_0_and_1(self):
        result = normalize_points([(0.1, 0.2), (0.9, 0.8)])
        assert result[0][0] == 0.0
        assert result[-1][0] == 1.0

    def test_clamps_out_of_range_values(self):
        result = normalize_points([(-0.5, 1.5), (0.5, 0.5), (1.5, -0.5)])
        for x, y in result:
            assert 0.0 <= x <= 1.0
            assert 0.0 <= y <= 1.0

    def test_malformed_input_falls_back_to_default(self):
        assert normalize_points("not points") == DEFAULT_CURVE_POINTS
        assert normalize_points([("a", "b")]) == DEFAULT_CURVE_POINTS

    def test_duplicate_x_gets_separated(self):
        result = normalize_points([(0.0, 0.0), (0.3, 0.1), (0.3, 0.9), (1.0, 1.0)])
        xs = [p[0] for p in result]
        assert len(set(xs)) == len(xs)
        assert xs == sorted(xs)

    def test_result_is_hashable(self):
        result = normalize_points([(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)])
        hash(result)  # must not raise


class TestIsIdentityCurve:
    def test_default_is_identity(self):
        assert is_identity_curve(DEFAULT_CURVE_POINTS) is True

    def test_none_is_identity(self):
        assert is_identity_curve(None) is True

    def test_moved_point_is_not_identity(self):
        assert is_identity_curve([(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)]) is False


class TestBuildCurveLut:
    def test_identity_lut_is_a_straight_line(self):
        lut = build_curve_lut(DEFAULT_CURVE_POINTS, resolution=256)
        expected = np.linspace(0.0, 1.0, 256, dtype=np.float32)
        np.testing.assert_allclose(lut, expected, atol=1e-5)

    def test_passes_through_control_points(self):
        points = [(0.0, 0.1), (0.5, 0.5), (1.0, 0.9)]
        lut = build_curve_lut(points, resolution=101)
        assert lut[0] == pytest.approx(0.1, abs=1e-3)
        assert lut[50] == pytest.approx(0.5, abs=1e-3)
        assert lut[-1] == pytest.approx(0.9, abs=1e-3)

    def test_monotonic_points_yield_monotonic_lut(self):
        points = [(0.0, 0.0), (0.25, 0.1), (0.75, 0.9), (1.0, 1.0)]
        lut = build_curve_lut(points, resolution=256)
        assert np.all(np.diff(lut) >= -1e-6)

    def test_output_is_clamped_to_unit_range(self):
        lut = build_curve_lut([(0.0, 0.0), (0.5, 1.0), (1.0, 0.0)], resolution=256)
        assert np.all(lut >= 0.0)
        assert np.all(lut <= 1.0)

    def test_output_dtype_is_float32(self):
        lut = build_curve_lut(DEFAULT_CURVE_POINTS)
        assert lut.dtype == np.float32


class TestComputeLuminanceHistogram:
    def test_solid_gray_image_concentrates_in_one_bin(self):
        image = np.full((10, 10, 3), 0.5, dtype=np.float32)
        counts = compute_luminance_histogram(image, bins=256)
        assert counts.sum() == 100
        assert counts.max() == 100

    def test_bin_count_matches_argument(self):
        image = np.random.rand(8, 8, 3).astype(np.float32)
        counts = compute_luminance_histogram(image, bins=64)
        assert len(counts) == 64
