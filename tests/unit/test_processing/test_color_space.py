"""Unit tests for sRGB <-> linear-light color space conversions."""

import numpy as np
import pytest
from PIL import Image

from src.processing.color_space import (
    srgb_to_linear,
    linear_to_srgb,
    image_to_linear,
    linear_to_image,
)


class TestSrgbToLinear:
    """Tests for srgb_to_linear."""

    def test_black_stays_black(self):
        result = srgb_to_linear(np.array([0.0]))
        assert result[0] == pytest.approx(0.0, abs=1e-6)

    def test_white_stays_white(self):
        result = srgb_to_linear(np.array([1.0]))
        assert result[0] == pytest.approx(1.0, abs=1e-5)

    def test_mid_gray_is_darker_in_linear(self):
        # sRGB 0.5 is much brighter than its linear-light equivalent -
        # this is exactly the nonlinearity the whole conversion exists for.
        result = srgb_to_linear(np.array([0.5]))
        assert result[0] < 0.3

    def test_known_reference_value(self):
        # sRGB 0.5 -> ~0.2140 linear (standard IEC 61966-2-1 reference value)
        result = srgb_to_linear(np.array([0.5]))
        assert result[0] == pytest.approx(0.21404, abs=1e-4)

    def test_linear_segment_near_zero(self):
        # Below the threshold the transfer function is a simple linear
        # scale (encoded / 12.92), not the power curve.
        result = srgb_to_linear(np.array([0.02]))
        assert result[0] == pytest.approx(0.02 / 12.92, abs=1e-6)

    def test_returns_float32(self):
        result = srgb_to_linear(np.array([0.5], dtype=np.float64))
        assert result.dtype == np.float32

    def test_preserves_shape(self):
        arr = np.random.rand(4, 5, 3).astype(np.float32)
        result = srgb_to_linear(arr)
        assert result.shape == (4, 5, 3)


class TestLinearToSrgb:
    """Tests for linear_to_srgb."""

    def test_black_stays_black(self):
        result = linear_to_srgb(np.array([0.0]))
        assert result[0] == pytest.approx(0.0, abs=1e-6)

    def test_white_stays_white(self):
        result = linear_to_srgb(np.array([1.0]))
        assert result[0] == pytest.approx(1.0, abs=1e-5)

    def test_is_inverse_of_srgb_to_linear(self):
        original = np.linspace(0.0, 1.0, 50).astype(np.float32)
        round_tripped = linear_to_srgb(srgb_to_linear(original))
        np.testing.assert_allclose(round_tripped, original, atol=1e-5)

    def test_does_not_raise_on_negative_input(self):
        # A slightly negative intermediate value (from an aggressive
        # adjustment) must not crash on the fractional power.
        result = linear_to_srgb(np.array([-0.01], dtype=np.float32))
        assert np.isfinite(result[0])


class TestImageRoundTrip:
    """Tests for image_to_linear / linear_to_image."""

    def test_rgb_round_trip_is_lossless_to_rounding(self):
        image = Image.new("RGB", (4, 4), color=(128, 64, 200))
        linear = image_to_linear(image)
        restored = linear_to_image(linear, "RGB")
        original_pixel = np.array(image)[0, 0]
        restored_pixel = np.array(restored)[0, 0]
        # Allow +/-1 for 8-bit quantization rounding through the round trip.
        np.testing.assert_allclose(restored_pixel, original_pixel, atol=1)

    def test_rgb_linear_buffer_is_float32_in_unit_range(self):
        image = Image.new("RGB", (2, 2), color=(255, 255, 255))
        linear = image_to_linear(image)
        assert linear.dtype == np.float32
        assert linear.min() >= 0.0
        assert linear.max() <= 1.0 + 1e-6

    def test_rgba_alpha_channel_untouched(self):
        image = Image.new("RGBA", (2, 2), color=(200, 100, 50, 128))
        linear = image_to_linear(image)
        # Alpha is a coverage fraction, not a light quantity: it should
        # pass through as a plain 0-1 scale, not gamma-decoded.
        assert linear[0, 0, 3] == pytest.approx(128 / 255.0, abs=1e-5)

    def test_rgba_round_trip(self):
        image = Image.new("RGBA", (3, 3), color=(10, 200, 30, 90))
        linear = image_to_linear(image)
        restored = linear_to_image(linear, "RGBA")
        original_pixel = np.array(image)[0, 0]
        restored_pixel = np.array(restored)[0, 0]
        np.testing.assert_allclose(restored_pixel, original_pixel, atol=1)

    def test_grayscale_round_trip(self):
        image = Image.new("L", (3, 3), color=140)
        linear = image_to_linear(image)
        restored = linear_to_image(linear, "L")
        original_pixel = np.array(image)[0, 0]
        restored_pixel = np.array(restored)[0, 0]
        assert abs(int(restored_pixel) - int(original_pixel)) <= 1
