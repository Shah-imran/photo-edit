"""Unit tests for ColorGradingProcessor (Shadows/Midtones/Highlights grading)."""

import cv2
import numpy as np
import pytest

from src.processors.color_grading_processor import (
    ColorGradingProcessor,
    _range_weight,
    _range_centers,
    _window_width,
    default_color_grading_params,
)


@pytest.fixture
def processor():
    return ColorGradingProcessor()


def _solid(value, shape=(2, 2, 3)):
    return np.full(shape, value, dtype=np.float32)


class TestIdentity:
    def test_no_params_is_identity(self, processor):
        rgb = np.random.rand(4, 4, 3).astype(np.float32)
        result = processor.process(rgb)
        np.testing.assert_array_equal(result, rgb)

    def test_all_default_params_is_identity(self, processor):
        rgb = np.random.rand(4, 4, 3).astype(np.float32)
        result = processor.process(rgb, **default_color_grading_params())
        np.testing.assert_array_equal(result, rgb)

    def test_nondefault_blending_and_balance_alone_is_identity(self, processor):
        """blending/balance only reshape the windows; with all sat/lum at
        zero there is nothing for them to affect -- see the identity
        fast-path note in the implementation note section 5."""
        rgb = np.random.rand(4, 4, 3).astype(np.float32)
        params = default_color_grading_params()
        params["blending"] = 90.0
        params["balance"] = -60.0
        result = processor.process(rgb, **params)
        np.testing.assert_array_equal(result, rgb)

    def test_returns_new_array_not_same_object(self, processor):
        rgb = _solid(0.5)
        result = processor.process(rgb, shadows_sat=50.0)
        assert result is not rgb


class TestPartitionOfUnityAtDefaults:
    """At default balance=0/blending=50, weights sum to exactly 1.0 -- the
    same Hann-window COLA property the HSL Mixer's bands already pin."""

    def test_range_weights_sum_to_one_across_luminance(self):
        centers = _range_centers(balance=0.0)
        width = _window_width(blending=50.0)
        v = np.linspace(0.0, 1.0, 500)
        total = np.zeros_like(v)
        for center in centers.values():
            total += _range_weight(v, center, width)
        np.testing.assert_allclose(total, 1.0, atol=1e-6)


class TestRangeIsolation:
    def test_pure_black_only_addressable_by_shadows(self, processor):
        black = _solid(0.0)
        result_shadows = processor.process(black, shadows_sat=80.0, shadows_hue=200.0)
        result_highlights = processor.process(
            black, highlights_sat=80.0, highlights_hue=200.0
        )
        assert not np.allclose(result_shadows, black)
        np.testing.assert_allclose(result_highlights, black, atol=1e-4)

    def test_pure_white_only_addressable_by_highlights(self, processor):
        white = _solid(1.0)
        result_highlights = processor.process(
            white, highlights_sat=80.0, highlights_hue=200.0
        )
        result_shadows = processor.process(white, shadows_sat=80.0, shadows_hue=200.0)
        assert not np.allclose(result_highlights, white)
        np.testing.assert_allclose(result_shadows, white, atol=1e-4)


class TestBalanceShiftsMidtoneCenter:
    """Balance moves only the midtone center; shadows/highlights stay fixed
    at 0.0/1.0 -- see the implementation note section 5 for why the
    anchors are deliberately not moved."""

    def test_balance_zero_is_the_default_centers(self):
        centers = _range_centers(balance=0.0)
        assert centers["shadows"] == 0.0
        assert centers["midtones"] == pytest.approx(0.5)
        assert centers["highlights"] == 1.0

    def test_balance_extremes_move_only_midtones(self):
        low = _range_centers(balance=-100.0)
        high = _range_centers(balance=100.0)
        assert low["midtones"] == pytest.approx(0.25)
        assert high["midtones"] == pytest.approx(0.75)
        assert low["shadows"] == 0.0 == high["shadows"]
        assert low["highlights"] == 1.0 == high["highlights"]

    def test_balance_changes_weight_where_ranges_compete(self):
        """At a luminance where shadows and midtones both have nonzero raw
        weight (so normalization cannot trivially restore midtones to 1.0),
        shifting the midtone center away changes midtones' normalized share."""
        width = _window_width(blending=50.0)
        v = np.array([0.4])

        centers_neutral = _range_centers(balance=0.0)
        w_shadow_neutral = _range_weight(v, centers_neutral["shadows"], width)
        w_mid_neutral = _range_weight(v, centers_neutral["midtones"], width)
        share_neutral = w_mid_neutral / (w_shadow_neutral + w_mid_neutral)

        centers_shifted = _range_centers(balance=-100.0)
        w_shadow_shifted = _range_weight(v, centers_shifted["shadows"], width)
        w_mid_shifted = _range_weight(v, centers_shifted["midtones"], width)
        share_shifted = w_mid_shifted / (w_shadow_shifted + w_mid_shifted)

        assert share_shifted[0] < share_neutral[0]


class TestDocumentedFormula:
    def test_luminance_offset_matches_documented_formula(self, processor):
        """A pure-black pixel is only under the Shadows range's weight (1.0
        at the exact center), so its luminance offset should match
        ``LUM_STRENGTH`` exactly (no tint contribution since sat=0)."""
        black = _solid(0.0)
        result = processor.process(black, shadows_lum=40.0)
        expected = 0.4 * 0.25  # (40/100) * _LUM_STRENGTH
        np.testing.assert_allclose(result, expected, atol=1e-4)

    def test_full_saturation_full_weight_blends_by_tint_strength(self, processor):
        """A pure-black pixel fully inside Shadows' window with full
        saturation should blend ``_TINT_STRENGTH`` (0.6) of the way toward
        the pure-hue tint color."""
        black = _solid(0.0)
        hue = 0.0  # pure red
        result = processor.process(black, shadows_sat=100.0, shadows_hue=hue)
        tint_hsv = np.array([[[hue, 1.0, 1.0]]], dtype=np.float32)
        tint_rgb = cv2.cvtColor(tint_hsv, cv2.COLOR_HSV2RGB)[0, 0]
        expected = np.zeros(3, dtype=np.float32) * 0.4 + tint_rgb * 0.6
        np.testing.assert_allclose(result[0, 0], expected, atol=1e-3)


class TestOutputProperties:
    def test_dtype_stays_float32(self, processor):
        result = processor.process(_solid(0.5), shadows_sat=50.0)
        assert result.dtype == np.float32

    def test_shape_preserved(self, processor):
        rgb = np.random.rand(6, 5, 3).astype(np.float32)
        result = processor.process(rgb, shadows_sat=50.0)
        assert result.shape == rgb.shape


class TestRgbaPassthrough:
    def test_alpha_channel_untouched(self, processor):
        rgba = np.full((2, 2, 4), 0.5, dtype=np.float32)
        rgba[..., 3] = 0.3
        result = processor.process(
            rgba, shadows_sat=50.0, shadows_hue=30.0, midtones_lum=20.0
        )
        np.testing.assert_array_equal(result[..., 3], rgba[..., 3])


class TestDefaultParams:
    def test_default_params_shape(self):
        params = default_color_grading_params()
        assert len(params) == 11
        assert params["blending"] == 50.0
        assert params["balance"] == 0.0
        for range_ in ("shadows", "midtones", "highlights"):
            for channel in ("hue", "sat", "lum"):
                assert params[f"{range_}_{channel}"] == 0.0
