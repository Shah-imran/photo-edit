"""Tests for the linear-light Grain processor."""

import numpy as np

from src.processors.grain_processor import GrainProcessor


def _detail_image(height: int = 24, width: int = 24) -> np.ndarray:
    grid = np.indices((height, width)).sum(axis=0) % 2
    return np.repeat((0.4 + grid[..., None] * 0.2).astype(np.float32), 3, axis=2)


def test_zero_is_identity_copy():
    image = _detail_image()
    result = GrainProcessor().process(image, grain=0.0)
    np.testing.assert_array_equal(result, image)
    assert result is not image


def test_same_image_and_params_are_deterministic():
    """process(image, grain=X) called twice must return byte-identical
    output -- required for the preview cache and for a pure-function
    pipeline. See docs/planning/implementation-notes/2026-10-12-grain.md
    section 5."""
    image = _detail_image()
    result1 = GrainProcessor().process(image, grain=40.0)
    result2 = GrainProcessor().process(image, grain=40.0)
    np.testing.assert_array_equal(result1, result2)


def test_different_grain_amount_changes_output():
    image = _detail_image()
    result_a = GrainProcessor().process(image, grain=20.0)
    result_b = GrainProcessor().process(image, grain=90.0)
    assert not np.array_equal(result_a, result_b)


def test_different_image_shape_changes_noise():
    small = np.full((16, 16, 3), 0.5, dtype=np.float32)
    large = np.full((32, 32, 3), 0.5, dtype=np.float32)
    result_small = GrainProcessor().process(small, grain=50.0)
    result_large = GrainProcessor().process(large, grain=50.0)
    # Compare the overlapping region: different shapes must reseed and
    # therefore produce different noise, not a cropped version of the
    # same field.
    assert not np.array_equal(
        result_small[:16, :16], result_large[:16, :16]
    )


def test_grain_adds_nonzero_variance_from_source():
    image = _detail_image()
    result = GrainProcessor().process(image, grain=60.0)
    assert not np.array_equal(result, image)
    diff = result - image
    assert float(np.var(diff)) > 0.0


def test_preserves_dtype_shape_and_headroom_without_clipping():
    image = _detail_image()
    image[0, 0] = 1.4
    result = GrainProcessor().process(image, grain=80.0)
    assert result.dtype == np.float32
    assert result.shape == image.shape
    # Headroom above 1.0 is not forcibly clipped.
    assert result.max() > 1.0


def test_clamps_negative_parameter_to_zero():
    image = _detail_image()
    low = GrainProcessor().process(image, grain=-50.0)
    np.testing.assert_array_equal(low, image)


def test_clamps_parameter_above_100():
    image = _detail_image()
    high = GrainProcessor().process(image, grain=1000.0)
    expected = GrainProcessor().process(image, grain=100.0)
    np.testing.assert_array_equal(high, expected)


def test_tiny_1x1_image_does_not_crash():
    image = np.full((1, 1, 3), 0.5, dtype=np.float32)
    result = GrainProcessor().process(image, grain=80.0)
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))


def test_small_image_below_downsample_target_does_not_crash():
    image = np.full((2, 2, 3), 0.5, dtype=np.float32)
    result = GrainProcessor().process(image, grain=80.0)
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))


def test_broadcasts_same_noise_field_across_channels():
    """Grain is luminance-only -- the same 2-D noise field is broadcast
    across channels, so channel differences (the noise contribution) must
    be identical to within floating point precision for a neutral
    constant image."""
    image = np.full((20, 20, 3), 0.5, dtype=np.float32)
    result = GrainProcessor().process(image, grain=70.0)
    diff = result - image
    np.testing.assert_allclose(diff[..., 0], diff[..., 1], atol=1e-6)
    np.testing.assert_allclose(diff[..., 1], diff[..., 2], atol=1e-6)
