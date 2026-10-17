"""Unit tests for CurveProcessor (master RGB tone curve, plus the
independent per-channel Red/Green/Blue curves -- PDF section 12, Phase
E)."""

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


_RAISE_MID = [(0.0, 0.0), (0.5, 0.8), (1.0, 1.0)]
_LOWER_MID = [(0.0, 0.0), (0.5, 0.2), (1.0, 1.0)]


class TestPerChannelIdentity:
    """All-4-curves-identity must be a true, zero-LUT-work no-op --
    mirrors ``StraightenProcessor``/``GeometryProcessor``'s own
    "all defaults => identity copy" convention.
    """

    def test_all_four_identity_is_noop(self, processor):
        rgb = np.random.rand(4, 4, 3).astype(np.float32)
        result = processor.process(
            rgb,
            points=None,
            red_points=[(0.0, 0.0), (1.0, 1.0)],
            green_points=None,
            blue_points=[(0.0, 0.0), (1.0, 1.0)],
        )
        np.testing.assert_array_equal(result, rgb)

    def test_all_four_identity_returns_new_array(self, processor):
        rgb = _solid(0.5)
        result = processor.process(rgb)
        assert result is not rgb


class TestPerChannelIsolation:
    """A change to one channel's curve must never leak into the other
    two channels' pixel values -- the clean, decisive way to prove
    channel isolation.
    """

    def test_red_only_curve_leaves_green_blue_untouched(self, processor):
        # Only sRGB round-trip float32 noise (~1e-7) is tolerated: the
        # green/blue channels must not actually be reshaped by the red
        # curve's LUT.
        rgb = np.random.rand(5, 5, 3).astype(np.float32) * 0.9 + 0.05
        result = processor.process(rgb, red_points=_RAISE_MID)
        np.testing.assert_allclose(result[..., 1], rgb[..., 1], atol=1e-6)
        np.testing.assert_allclose(result[..., 2], rgb[..., 2], atol=1e-6)
        assert not np.allclose(result[..., 0], rgb[..., 0], atol=1e-4)

    def test_green_only_curve_leaves_red_blue_untouched(self, processor):
        rgb = np.random.rand(5, 5, 3).astype(np.float32) * 0.9 + 0.05
        result = processor.process(rgb, green_points=_LOWER_MID)
        np.testing.assert_allclose(result[..., 0], rgb[..., 0], atol=1e-6)
        np.testing.assert_allclose(result[..., 2], rgb[..., 2], atol=1e-6)
        assert not np.allclose(result[..., 1], rgb[..., 1], atol=1e-4)

    def test_blue_only_curve_leaves_red_green_untouched(self, processor):
        rgb = np.random.rand(5, 5, 3).astype(np.float32) * 0.9 + 0.05
        result = processor.process(rgb, blue_points=_RAISE_MID)
        np.testing.assert_allclose(result[..., 0], rgb[..., 0], atol=1e-6)
        np.testing.assert_allclose(result[..., 1], rgb[..., 1], atol=1e-6)
        assert not np.allclose(result[..., 2], rgb[..., 2], atol=1e-4)

    def test_master_and_channel_curves_compose(self, processor):
        """Master applies to all 3 channels FIRST, then the red curve
        applies to red alone -- so a red-raising master plus a
        red-lowering per-channel curve must still differ from the
        master-only result on the red channel, while green/blue match
        the master-only result exactly (master already applied
        identically to all 3, and no per-channel curve touches them).
        """
        rgb = _solid(0.5)
        master_only = processor.process(rgb, points=_RAISE_MID)
        composed = processor.process(
            rgb, points=_RAISE_MID, red_points=_LOWER_MID
        )
        np.testing.assert_array_equal(composed[..., 1], master_only[..., 1])
        np.testing.assert_array_equal(composed[..., 2], master_only[..., 2])
        assert composed[0, 0, 0] != master_only[0, 0, 0]

    def test_endpoints_stay_black_and_white_per_channel(self, processor):
        black = _solid(0.0)
        white = _solid(1.0)
        result_black = processor.process(
            black, red_points=_RAISE_MID, green_points=_LOWER_MID,
            blue_points=_RAISE_MID,
        )
        result_white = processor.process(
            white, red_points=_RAISE_MID, green_points=_LOWER_MID,
            blue_points=_RAISE_MID,
        )
        np.testing.assert_allclose(result_black, black, atol=1e-5)
        np.testing.assert_allclose(result_white, white, atol=1e-5)

    def test_shape_and_dtype_preserved_with_all_four_curves(self, processor):
        rgb = np.random.rand(6, 5, 3).astype(np.float32)
        result = processor.process(
            rgb, points=_RAISE_MID, red_points=_LOWER_MID,
            green_points=_RAISE_MID, blue_points=_LOWER_MID,
        )
        assert result.shape == rgb.shape
        assert result.dtype == np.float32

    def test_alpha_untouched_with_per_channel_curves(self, processor):
        rgba = np.full((2, 2, 4), 0.5, dtype=np.float32)
        rgba[..., 3] = 0.3
        result = processor.process(rgba, red_points=_RAISE_MID)
        np.testing.assert_array_equal(result[..., 3], rgba[..., 3])
