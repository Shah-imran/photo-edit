"""Unit tests for HslMixerProcessor (8-band HSL Color Mixer)."""

import cv2
import numpy as np
import pytest

from src.processors.hsl_mixer_processor import (
    HSL_BAND_CENTERS,
    HslMixerProcessor,
    _band_weight,
    default_hsl_params,
)


@pytest.fixture
def processor():
    return HslMixerProcessor()


def _solid(value, shape=(2, 2, 3)):
    return np.full(shape, value, dtype=np.float32)


def _pure_hue_pixel(hue_deg: float, shape=(2, 2, 3)) -> np.ndarray:
    """A saturated, mid-value pixel at the given HSV hue."""
    hsv = np.full((*shape[:2], 3), [hue_deg, 1.0, 0.5], dtype=np.float32)
    rgb = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    return rgb.astype(np.float32)


class TestIdentity:
    def test_no_params_is_identity(self, processor):
        rgb = np.random.rand(4, 4, 3).astype(np.float32)
        result = processor.process(rgb)
        np.testing.assert_array_equal(result, rgb)

    def test_all_zero_params_is_identity(self, processor):
        rgb = np.random.rand(4, 4, 3).astype(np.float32)
        result = processor.process(rgb, **default_hsl_params())
        np.testing.assert_array_equal(result, rgb)

    def test_returns_new_array_not_same_object(self, processor):
        rgb = _solid(0.5)
        result = processor.process(rgb, red_sat=50.0)
        assert result is not rgb


class TestPartitionOfUnity:
    """Pins the COLA (constant overlap-add) property section 5 relies on."""

    def test_band_weights_sum_to_one_at_every_hue(self):
        hues = np.linspace(0.0, 359.9, 500)
        total = np.zeros_like(hues)
        for center in HSL_BAND_CENTERS.values():
            total += _band_weight(hues, center)
        np.testing.assert_allclose(total, 1.0, atol=1e-6)


class TestBandIsolation:
    def test_red_hue_shift_rotates_red_pixel(self, processor):
        red = _pure_hue_pixel(0.0)
        result = processor.process(red, red_hue=50.0)
        result_hsv = cv2.cvtColor(np.clip(result, 0, 1), cv2.COLOR_RGB2HSV)
        assert result_hsv[0, 0, 0] != pytest.approx(0.0, abs=1e-3)

    def test_red_hue_shift_leaves_green_pixel_unchanged(self, processor):
        green = _pure_hue_pixel(135.0)  # far from Red (0) and its window
        result = processor.process(green, red_hue=100.0)
        np.testing.assert_allclose(result, green, atol=1e-4)


class TestDocumentedFormula:
    def test_saturation_matches_documented_formula(self, processor):
        red = _pure_hue_pixel(0.0)
        result = processor.process(red, red_sat=-50.0)

        original_hsv = cv2.cvtColor(np.clip(red, 0, 1), cv2.COLOR_RGB2HSV)
        expected_sat = np.clip(original_hsv[0, 0, 1] * (1.0 + (-50.0 / 100.0)), 0.0, 1.0)

        result_hsv = cv2.cvtColor(np.clip(result, 0, 1), cv2.COLOR_RGB2HSV)
        assert result_hsv[0, 0, 1] == pytest.approx(expected_sat, abs=1e-3)

    def test_luminance_matches_documented_formula(self, processor):
        red = _pure_hue_pixel(0.0)
        result = processor.process(red, red_lum=40.0)

        original_hsv = cv2.cvtColor(np.clip(red, 0, 1), cv2.COLOR_RGB2HSV)
        expected_val = np.clip(original_hsv[0, 0, 2] + (40.0 / 100.0) * 0.3, 0.0, 1.0)

        result_hsv = cv2.cvtColor(np.clip(result, 0, 1), cv2.COLOR_RGB2HSV)
        assert result_hsv[0, 0, 2] == pytest.approx(expected_val, abs=1e-3)


class TestOutputProperties:
    def test_dtype_stays_float32(self, processor):
        result = processor.process(_solid(0.5), red_sat=50.0)
        assert result.dtype == np.float32

    def test_shape_preserved(self, processor):
        rgb = np.random.rand(6, 5, 3).astype(np.float32)
        result = processor.process(rgb, red_sat=50.0)
        assert result.shape == rgb.shape


class TestRgbaPassthrough:
    def test_alpha_channel_untouched(self, processor):
        rgba = np.full((2, 2, 4), 0.5, dtype=np.float32)
        rgba[..., 3] = 0.3
        result = processor.process(rgba, red_sat=50.0, red_hue=30.0, red_lum=20.0)
        np.testing.assert_array_equal(result[..., 3], rgba[..., 3])
