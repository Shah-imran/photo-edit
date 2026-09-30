"""Unit tests for TonalProcessor (Highlights/Shadows/Whites/Blacks)."""

import numpy as np
import pytest

from src.processors.tonal_processor import TonalProcessor


@pytest.fixture
def processor():
    return TonalProcessor()


def _solid(value, shape=(2, 2, 3)):
    return np.full(shape, value, dtype=np.float32)


class TestIdentity:
    """All-zero parameters must leave the buffer unchanged."""

    def test_all_zero_params_is_identity(self, processor):
        rgb = np.random.rand(4, 4, 3).astype(np.float32)
        result = processor.process(rgb)
        np.testing.assert_array_equal(result, rgb)

    def test_returns_new_array_not_same_object(self, processor):
        rgb = _solid(0.5)
        result = processor.process(rgb)
        assert result is not rgb


class TestHighlights:
    """Highlights should only affect pixels above mid-gray luminance."""

    def test_positive_highlights_brightens_bright_pixel(self, processor):
        bright = _solid(0.9)
        result = processor.process(bright, highlights=50.0)
        assert result[0, 0, 0] > 0.9

    def test_positive_highlights_leaves_dark_pixel_unchanged(self, processor):
        dark = _solid(0.1)
        result = processor.process(dark, highlights=100.0)
        np.testing.assert_allclose(result, dark, atol=1e-6)

    def test_negative_highlights_darkens_bright_pixel(self, processor):
        bright = _solid(0.9)
        result = processor.process(bright, highlights=-50.0)
        assert result[0, 0, 0] < 0.9

    def test_full_white_pixel_has_no_room_to_brighten_further(self, processor):
        white = _solid(1.0)
        result = processor.process(white, highlights=100.0)
        np.testing.assert_allclose(result, white, atol=1e-6)

    def test_mid_gray_is_unaffected(self, processor):
        # smoothstep(0.5, 1.0, 0.5) == 0, so the mask weight at exactly
        # mid-gray is zero.
        mid = _solid(0.5)
        result = processor.process(mid, highlights=100.0)
        np.testing.assert_allclose(result, mid, atol=1e-6)


class TestShadows:
    """Shadows should only affect pixels below mid-gray luminance."""

    def test_positive_shadows_lifts_dark_pixel(self, processor):
        dark = _solid(0.1)
        result = processor.process(dark, shadows=50.0)
        assert result[0, 0, 0] > 0.1

    def test_positive_shadows_leaves_bright_pixel_unchanged(self, processor):
        bright = _solid(0.9)
        result = processor.process(bright, shadows=100.0)
        np.testing.assert_allclose(result, bright, atol=1e-6)

    def test_negative_shadows_deepens_dark_pixel(self, processor):
        dark = _solid(0.2)
        result = processor.process(dark, shadows=-50.0)
        assert result[0, 0, 0] < 0.2

    def test_full_black_pixel_has_no_room_to_deepen_further(self, processor):
        black = _solid(0.0)
        result = processor.process(black, shadows=-100.0)
        np.testing.assert_allclose(result, black, atol=1e-6)

    def test_mid_gray_is_unaffected(self, processor):
        mid = _solid(0.5)
        result = processor.process(mid, shadows=100.0)
        np.testing.assert_allclose(result, mid, atol=1e-6)


class TestWhitesBlacks:
    """Whites/Blacks remap the input black/white points."""

    def test_whites_zero_blacks_zero_is_identity(self, processor):
        rgb = _solid(0.4)
        result = processor.process(rgb, whites=0.0, blacks=0.0)
        np.testing.assert_allclose(result, rgb, atol=1e-6)

    def test_matches_documented_formula(self, processor):
        rgb = _solid(0.6)
        whites, blacks = 40.0, -20.0
        result = processor.process(rgb, whites=whites, blacks=blacks)

        white_point = 1.0 - whites / 200.0
        black_point = -blacks / 200.0
        expected = (0.6 - black_point) / (white_point - black_point)

        np.testing.assert_allclose(result[0, 0, 0], expected, atol=1e-6)

    def test_positive_whites_brightens_midtone(self, processor):
        mid = _solid(0.5)
        result = processor.process(mid, whites=50.0)
        assert result[0, 0, 0] > 0.5

    def test_positive_blacks_lifts_shadow_negative_blacks_crushes_it(self, processor):
        # Matches Lightroom: positive Blacks opens up/lifts shadow detail,
        # negative Blacks deepens/crushes it toward pure black.
        shadow = _solid(0.1)
        lifted = processor.process(shadow, blacks=50.0)
        crushed = processor.process(shadow, blacks=-50.0)
        assert lifted[0, 0, 0] > shadow[0, 0, 0]
        assert crushed[0, 0, 0] < shadow[0, 0, 0]
        assert lifted[0, 0, 0] > crushed[0, 0, 0]

    def test_degenerate_span_does_not_raise_or_produce_nan(self, processor):
        rgb = _solid(0.5)
        # whites=100 -> white_point=0.5; blacks=-100 -> black_point=0.5:
        # span would be exactly zero without the floor.
        result = processor.process(rgb, whites=100.0, blacks=-100.0)
        assert np.all(np.isfinite(result))


class TestRgbaPassthrough:
    """An alpha channel must not be touched by any of the four sliders."""

    def test_alpha_channel_untouched(self, processor):
        rgba = np.full((2, 2, 4), 0.5, dtype=np.float32)
        rgba[..., 3] = 0.3
        result = processor.process(rgba, highlights=50.0, shadows=50.0, whites=20.0, blacks=-20.0)
        np.testing.assert_array_equal(result[..., 3], rgba[..., 3])
