"""Tests for the Straighten (small-angle rigid rotation) processor."""

import numpy as np
import pytest

from src.processors.straighten_processor import StraightenProcessor


def _marker_image(height: int = 101, width: int = 101, marker_xy=(90, 50)) -> np.ndarray:
    """A mostly-dark image with a single bright marker pixel off-center."""
    image = np.zeros((height, width, 3), dtype=np.float32)
    x, y = marker_xy
    image[y, x] = 1.0
    return image


def _marker_position(image: np.ndarray) -> tuple:
    """Return the (x, y) location of the brightest pixel's channel 0."""
    y, x = np.unravel_index(np.argmax(image[..., 0]), image[..., 0].shape)
    return (int(x), int(y))


def test_zero_is_identity_copy():
    image = _marker_image()
    result = StraightenProcessor().process(image, straighten=0.0)
    np.testing.assert_array_equal(result, image)
    assert result is not image


@pytest.mark.parametrize("angle", [-45.0, -20.0, -1.0, 1.0, 20.0, 45.0])
def test_output_shape_identical_to_input_shape(angle):
    """The single most important invariant in this slice: Straighten must
    never change the (H, W, C) shape, at any angle including the extremes."""
    image = _marker_image(height=64, width=96)
    result = StraightenProcessor().process(image, straighten=angle)
    assert result.shape == image.shape


def test_positive_angle_rotates_counter_clockwise_on_screen():
    """Verified empirically (not assumed) against cv2.getRotationMatrix2D
    + cv2.warpAffine directly, the same way Remove CA's sign convention
    was verified: a marker pixel directly right of center (the "3 o'clock"
    position) moves toward the "12 o'clock" side (up, smaller y) under a
    positive angle, and toward the "6 o'clock" side (down, larger y) under
    the same-magnitude negative angle -- i.e. positive values rotate image
    content counter-clockwise as rendered on screen (y increasing
    downward); negative values rotate it clockwise."""
    image = _marker_image(height=101, width=101, marker_xy=(90, 50))

    positive_result = StraightenProcessor().process(image, straighten=10.0)
    px, py = _marker_position(positive_result)
    assert py < 50  # moved up (toward 12 o'clock) -> counter-clockwise

    negative_result = StraightenProcessor().process(image, straighten=-10.0)
    nx, ny = _marker_position(negative_result)
    assert ny > 50  # moved down (toward 6 o'clock) -> clockwise


def test_dtype_preserved():
    image = _marker_image()
    result = StraightenProcessor().process(image, straighten=15.0)
    assert result.dtype == np.float32


def test_preserves_headroom_without_clipping():
    """A large constant-bright value, sampled well away from any
    rotated-in border, must stay at that exact value -- this avoids the
    boundary-interpolation ambiguity a non-constant image would have."""
    image = np.full((200, 200, 3), 1.5, dtype=np.float32)
    result = StraightenProcessor().process(image, straighten=10.0)
    interior = result[60:140, 60:140]
    np.testing.assert_allclose(interior, 1.5, atol=1e-4)
    assert interior.max() > 1.0


def test_clamps_angle_below_minus_45():
    image = _marker_image()
    low = StraightenProcessor().process(image, straighten=-90.0)
    expected = StraightenProcessor().process(image, straighten=-45.0)
    np.testing.assert_array_equal(low, expected)


def test_clamps_angle_above_45():
    image = _marker_image()
    high = StraightenProcessor().process(image, straighten=90.0)
    expected = StraightenProcessor().process(image, straighten=45.0)
    np.testing.assert_array_equal(high, expected)


def test_is_deterministic_pure_function():
    image = _marker_image()
    result1 = StraightenProcessor().process(image, straighten=12.5)
    result2 = StraightenProcessor().process(image, straighten=12.5)
    np.testing.assert_array_equal(result1, result2)


def test_tiny_1x1_image_does_not_crash():
    """Verified directly: cv2.warpAffine does not crash on a 1x1 float32
    input (the single pixel is trivially returned under
    BORDER_REFLECT_101), so no defensive bypass is added, matching Remove
    CA's/Color NR's/Defringe's "verify first" precedent."""
    image = np.full((1, 1, 3), 0.5, dtype=np.float32)
    result = StraightenProcessor().process(image, straighten=10.0)
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))


def test_tiny_2x2_image_does_not_crash():
    image = np.full((2, 2, 3), 0.5, dtype=np.float32)
    result = StraightenProcessor().process(image, straighten=10.0)
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))
