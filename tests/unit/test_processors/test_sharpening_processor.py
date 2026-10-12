"""Tests for the linear-light Sharpening (unsharp mask) processor."""

import numpy as np

from src.processors.sharpening_processor import SharpeningProcessor


def _edge_image(height: int = 24, width: int = 24) -> np.ndarray:
    """A hard vertical step edge (left half dark, right half light)."""
    image = np.full((height, width, 3), 0.2, dtype=np.float32)
    image[:, width // 2:] = 0.8
    return image


def _checkerboard_image(height: int = 24, width: int = 24) -> np.ndarray:
    grid = np.indices((height, width)).sum(axis=0) % 2
    return np.repeat((0.3 + grid[..., None] * 0.4).astype(np.float32), 3, axis=2)


def _edge_energy(image: np.ndarray) -> float:
    """A simple measure of local contrast: variance of horizontal diffs."""
    diffs = np.diff(image[..., 0], axis=1)
    return float(np.var(diffs))


def test_zero_is_identity_copy():
    image = _checkerboard_image()
    result = SharpeningProcessor().process(image, sharpening=0.0)
    np.testing.assert_array_equal(result, image)
    assert result is not image


def test_positive_sharpening_increases_edge_energy():
    image = _edge_image()
    result = SharpeningProcessor().process(image, sharpening=80.0)
    assert _edge_energy(result) > _edge_energy(image)


def test_positive_sharpening_increases_checkerboard_contrast():
    image = _checkerboard_image()
    result = SharpeningProcessor().process(image, sharpening=100.0)
    assert not np.array_equal(result, image)
    assert _edge_energy(result) >= _edge_energy(image)


def test_flat_image_stays_nearly_flat():
    """The masking safeguard must suppress added detail where there is no
    edge -- a perfectly flat image should stay flat (within tight
    tolerance), not pick up amplified noise/texture."""
    image = np.full((20, 20, 3), 0.5, dtype=np.float32)
    result = SharpeningProcessor().process(image, sharpening=100.0)
    np.testing.assert_allclose(result, image, atol=1e-5)


def test_masking_suppresses_flat_regions_relative_to_edges():
    """On an image with both a strong edge and a flat region, the change
    introduced by sharpening must be far larger near the edge than deep in
    the flat region -- confirming the masking safeguard actually
    discriminates, rather than scaling everything uniformly."""
    image = _edge_image(height=24, width=24)
    result = SharpeningProcessor().process(image, sharpening=100.0)
    diff = np.abs(result - image)
    edge_zone_change = float(diff[:, 10:14].mean())
    flat_zone_change = float(diff[:, :4].mean())
    assert edge_zone_change > flat_zone_change


def test_preserves_dtype_shape_and_headroom_without_clipping():
    image = _edge_image()
    image[0, 0] = 1.4
    result = SharpeningProcessor().process(image, sharpening=80.0)
    assert result.dtype == np.float32
    assert result.shape == image.shape
    assert result.max() > 1.0


def test_clamps_negative_parameter_to_zero():
    image = _edge_image()
    low = SharpeningProcessor().process(image, sharpening=-50.0)
    np.testing.assert_array_equal(low, image)


def test_clamps_parameter_above_100():
    image = _edge_image()
    high = SharpeningProcessor().process(image, sharpening=1000.0)
    expected = SharpeningProcessor().process(image, sharpening=100.0)
    np.testing.assert_array_equal(high, expected)


def test_tiny_1x1_image_does_not_crash():
    image = np.full((1, 1, 3), 0.5, dtype=np.float32)
    result = SharpeningProcessor().process(image, sharpening=80.0)
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))


def test_is_deterministic_pure_function():
    """Unlike Grain, Sharpening is deterministic -- calling process() twice
    with the same inputs must return byte-identical output."""
    image = _checkerboard_image()
    result1 = SharpeningProcessor().process(image, sharpening=40.0)
    result2 = SharpeningProcessor().process(image, sharpening=40.0)
    np.testing.assert_array_equal(result1, result2)
