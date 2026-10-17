"""Tests for the edge-preserving Luminance Noise Reduction processor."""

import numpy as np

from src.processors.luminance_noise_reduction_processor import (
    LuminanceNoiseReductionProcessor,
)


def _flat_noisy_image(
    height: int = 40, width: int = 40, seed: int = 0, sigma: float = 0.05
) -> np.ndarray:
    """A flat gray patch with deterministic additive Gaussian noise."""
    rng = np.random.default_rng(seed)
    base = np.full((height, width, 3), 0.5, dtype=np.float32)
    noise = rng.normal(0.0, sigma, (height, width)).astype(np.float32)
    noisy = base + noise[..., np.newaxis]
    return noisy.astype(np.float32)


def _colorful_edge_image(height: int = 32, width: int = 32) -> np.ndarray:
    """A hard vertical edge between two saturated colors (red/blue)."""
    image = np.zeros((height, width, 3), dtype=np.float32)
    image[:, : width // 2] = (0.8, 0.1, 0.1)
    image[:, width // 2 :] = (0.1, 0.1, 0.8)
    return image


def test_zero_is_identity_copy():
    image = _flat_noisy_image()
    result = LuminanceNoiseReductionProcessor().process(image, luminance_nr=0.0)
    np.testing.assert_array_equal(result, image)
    assert result is not image


def test_positive_value_reduces_luminance_variance():
    image = _flat_noisy_image()
    result = LuminanceNoiseReductionProcessor().process(image, luminance_nr=100.0)
    luminance_in = (
        0.2126 * image[..., 0] + 0.7152 * image[..., 1] + 0.0722 * image[..., 2]
    )
    luminance_out = (
        0.2126 * result[..., 0] + 0.7152 * result[..., 1] + 0.0722 * result[..., 2]
    )
    assert np.var(luminance_out) < np.var(luminance_in)


def test_is_deterministic_pure_function():
    """The bilateral filter has no RNG -- calling process() twice with the
    same inputs must return byte-identical output."""
    image = _flat_noisy_image()
    result1 = LuminanceNoiseReductionProcessor().process(image, luminance_nr=60.0)
    result2 = LuminanceNoiseReductionProcessor().process(image, luminance_nr=60.0)
    np.testing.assert_array_equal(result1, result2)


def test_preserves_color_ratios_on_colorful_edge_image():
    """Luminance-only NR must not desaturate or color-shift a colorful
    edge image -- the per-channel change should be small relative to the
    strong color difference across the edge."""
    image = _colorful_edge_image()
    result = LuminanceNoiseReductionProcessor().process(image, luminance_nr=100.0)
    # Hue/color identity: red side stays red-dominant, blue side stays
    # blue-dominant.
    assert result[:, 0, 0].mean() > result[:, 0, 2].mean()
    assert result[:, -1, 2].mean() > result[:, -1, 0].mean()
    # The change introduced is small relative to the cross-edge color
    # difference itself (no gross color shift / desaturation).
    diff = np.abs(result - image)
    assert diff.max() < 0.3


def test_preserves_dtype_shape_and_headroom_without_clipping():
    image = _flat_noisy_image()
    image[0, 0] = 1.4
    result = LuminanceNoiseReductionProcessor().process(image, luminance_nr=80.0)
    assert result.dtype == np.float32
    assert result.shape == image.shape
    assert result.max() > 1.0


def test_clamps_negative_parameter_to_zero():
    image = _flat_noisy_image()
    low = LuminanceNoiseReductionProcessor().process(image, luminance_nr=-50.0)
    np.testing.assert_array_equal(low, image)


def test_clamps_parameter_above_100():
    image = _flat_noisy_image()
    high = LuminanceNoiseReductionProcessor().process(image, luminance_nr=1000.0)
    expected = LuminanceNoiseReductionProcessor().process(image, luminance_nr=100.0)
    np.testing.assert_array_equal(high, expected)


def test_tiny_1x1_image_does_not_crash():
    image = np.full((1, 1, 3), 0.5, dtype=np.float32)
    result = LuminanceNoiseReductionProcessor().process(image, luminance_nr=80.0)
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))


def test_tiny_2x2_image_does_not_crash():
    image = np.full((2, 2, 3), 0.5, dtype=np.float32)
    result = LuminanceNoiseReductionProcessor().process(image, luminance_nr=80.0)
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))
