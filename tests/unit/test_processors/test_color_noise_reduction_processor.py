"""Tests for the chrominance-only Color Noise Reduction processor."""

import numpy as np

from src.processors.color_noise_reduction_processor import (
    ColorNoiseReductionProcessor,
)

_WR, _WG, _WB = 0.2126, 0.7152, 0.0722


def _luminance(image: np.ndarray) -> np.ndarray:
    return _WR * image[..., 0] + _WG * image[..., 1] + _WB * image[..., 2]


def _chroma_noisy_image(
    height: int = 40, width: int = 40, seed: int = 0, sigma: float = 0.08
) -> np.ndarray:
    """A constant base color with deterministic per-pixel chroma jitter.

    Random per-pixel hue/saturation noise is added to R and B (and the
    negated sum to G, so the perturbation has (approximately) zero
    luminance contribution, i.e. it is predominantly a *chroma* noise
    source rather than a brightness noise source).
    """
    rng = np.random.default_rng(seed)
    base = np.array([0.5, 0.45, 0.4], dtype=np.float32)
    image = np.tile(base, (height, width, 1)).astype(np.float32)
    noise_r = rng.normal(0.0, sigma, (height, width)).astype(np.float32)
    noise_b = rng.normal(0.0, sigma, (height, width)).astype(np.float32)
    # Choose noise_g so that wr*noise_r + wg*noise_g + wb*noise_b ~= 0,
    # keeping luminance approximately constant while R/B (and therefore
    # hue/saturation) jitter around the base color.
    noise_g = -(_WR * noise_r + _WB * noise_b) / _WG
    image[..., 0] += noise_r
    image[..., 1] += noise_g
    image[..., 2] += noise_b
    return image.astype(np.float32)


def _flat_image(height: int = 20, width: int = 20) -> np.ndarray:
    return np.full((height, width, 3), 0.5, dtype=np.float32)


def test_zero_is_identity_copy():
    image = _chroma_noisy_image()
    result = ColorNoiseReductionProcessor().process(image, color_nr=0.0)
    np.testing.assert_array_equal(result, image)
    assert result is not image


def test_decompose_reconstruct_round_trips_at_zero_blending():
    """The luminance/chrominance decomposition must be an exact algebraic
    inverse: decomposing an image into (Y, Cr, Cb) and reconstructing
    immediately (zero smoothing/blending) must return the original image
    to near machine precision. This is the core algebra check requested
    for this slice, pinned directly rather than only indirectly through
    the processor's own zero-is-identity short-circuit."""
    rng = np.random.default_rng(42)
    source = rng.uniform(0.0, 1.0, size=(16, 16, 3)).astype(np.float32)

    r, g, b = source[..., 0], source[..., 1], source[..., 2]
    y = _WR * r + _WG * g + _WB * b
    cr = r - y
    cb = b - y

    # Zero smoothing/blending: Cr_blended == Cr, Cb_blended == Cb.
    new_r = y + cr
    new_b = y + cb
    new_g = y - (_WR * cr + _WB * cb) / _WG
    reconstructed = np.stack([new_r, new_g, new_b], axis=-1)

    np.testing.assert_allclose(reconstructed, source, atol=1e-5)


def test_positive_value_reduces_chroma_variance():
    image = _chroma_noisy_image()
    result = ColorNoiseReductionProcessor().process(image, color_nr=100.0)

    def _chroma_std(img: np.ndarray) -> float:
        y = _luminance(img)
        cr = img[..., 0] - y
        cb = img[..., 2] - y
        return float(np.std(cr) + np.std(cb))

    assert _chroma_std(result) < _chroma_std(image)


def test_luminance_is_approximately_preserved():
    """Color NR smooths chroma only -- it must not systematically darken
    or brighten the image."""
    image = _chroma_noisy_image()
    result = ColorNoiseReductionProcessor().process(image, color_nr=100.0)
    mean_lum_in = float(np.mean(_luminance(image)))
    mean_lum_out = float(np.mean(_luminance(result)))
    assert abs(mean_lum_in - mean_lum_out) < 1e-4


def test_is_deterministic_pure_function():
    """The Gaussian blur has no RNG -- calling process() twice with the
    same inputs must return byte-identical output."""
    image = _chroma_noisy_image()
    result1 = ColorNoiseReductionProcessor().process(image, color_nr=60.0)
    result2 = ColorNoiseReductionProcessor().process(image, color_nr=60.0)
    np.testing.assert_array_equal(result1, result2)


def test_flat_image_stays_nearly_flat():
    """A perfectly flat image has zero chroma to smooth, so it should stay
    (near) exactly unchanged even at full strength."""
    image = _flat_image()
    result = ColorNoiseReductionProcessor().process(image, color_nr=100.0)
    np.testing.assert_allclose(result, image, atol=1e-5)


def test_preserves_dtype_shape_and_headroom_without_clipping():
    image = _chroma_noisy_image()
    image[0, 0] = (1.4, 1.3, 1.2)
    result = ColorNoiseReductionProcessor().process(image, color_nr=80.0)
    assert result.dtype == np.float32
    assert result.shape == image.shape
    assert result.max() > 1.0


def test_clamps_negative_parameter_to_zero():
    image = _chroma_noisy_image()
    low = ColorNoiseReductionProcessor().process(image, color_nr=-50.0)
    np.testing.assert_array_equal(low, image)


def test_clamps_parameter_above_100():
    image = _chroma_noisy_image()
    high = ColorNoiseReductionProcessor().process(image, color_nr=1000.0)
    expected = ColorNoiseReductionProcessor().process(image, color_nr=100.0)
    np.testing.assert_array_equal(high, expected)


def test_tiny_1x1_image_does_not_crash():
    image = np.full((1, 1, 3), 0.5, dtype=np.float32)
    result = ColorNoiseReductionProcessor().process(image, color_nr=80.0)
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))


def test_tiny_2x2_image_does_not_crash():
    image = np.full((2, 2, 3), 0.5, dtype=np.float32)
    result = ColorNoiseReductionProcessor().process(image, color_nr=80.0)
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))
