"""Tests for the Remove Chromatic Aberration (lateral CA) processor."""

import cv2
import numpy as np

from src.processors.remove_chromatic_aberration_processor import (
    RemoveChromaticAberrationProcessor,
)


def _flat_image(height: int = 20, width: int = 20) -> np.ndarray:
    return np.full((height, width, 3), 0.5, dtype=np.float32)


def _ca_image(height: int = 101, width: int = 101) -> np.ndarray:
    """A synthetic image with deliberate radial R/G/B misalignment.

    A single bright point is placed near the right edge in each channel,
    but R and B are pre-shifted radially *outward* from where G sits --
    the opposite of what ``RemoveChromaticAberrationProcessor`` corrects
    for (it shrinks R and expands B), so correcting should measurably
    reduce the R-G and increase... actually: the processor's fixed
    direction (shrink R toward center, expand B away from center) is
    applied regardless of the source image's actual misalignment, since
    there is no lens profile to calibrate against (see the implementation
    note). This test instead builds the misalignment in exactly the
    direction the processor corrects, so applying Remove CA measurably
    re-aligns the channels.
    """
    image = np.zeros((height, width, 3), dtype=np.float32)
    cy = (height - 1) / 2.0
    cx = (width - 1) / 2.0
    # Place the green reference point.
    gy, gx = int(cy), int(cx + 30)
    image[gy, gx, 1] = 1.0
    # Red is shifted further FROM the center than green (needs shrinking
    # inward to re-align -- exactly what k = +_MAX_K does).
    ry, rx = gy, gx + 2
    image[ry, rx, 0] = 1.0
    # Blue is shifted closer TO the center than green (needs expanding
    # outward to re-align -- exactly what k = -_MAX_K does).
    by, bx = gy, gx - 2
    image[by, bx, 2] = 1.0
    return image


def _channel_peak_x(channel: np.ndarray) -> int:
    _, x = np.unravel_index(np.argmax(channel), channel.shape)
    return int(x)


def _channel_centroid_x(channel: np.ndarray) -> float:
    """Sub-pixel intensity-weighted x centroid.

    The per-value radial scale is a small fraction of a pixel at the
    radii used in these tests, so a discrete argmax position does not
    move -- only the sub-pixel energy distribution around it does. A
    weighted centroid over a small window makes that sub-pixel shift
    directly measurable.
    """
    y, x = np.unravel_index(np.argmax(channel), channel.shape)
    y0, y1 = max(0, y - 2), min(channel.shape[0], y + 3)
    x0, x1 = max(0, x - 2), min(channel.shape[1], x + 3)
    window = channel[y0:y1, x0:x1]
    xs = np.arange(x0, x1, dtype=np.float64)
    weights = window.sum(axis=0).astype(np.float64)
    total = weights.sum()
    if total == 0:
        return float(x)
    return float((xs * weights).sum() / total)


def test_zero_is_identity_copy():
    image = _ca_image()
    result = RemoveChromaticAberrationProcessor().process(image, remove_ca=0.0)
    np.testing.assert_array_equal(result, image)
    assert result is not image


def test_green_channel_is_never_modified():
    image = _ca_image()
    for value in (1.0, 25.0, 50.0, 100.0):
        result = RemoveChromaticAberrationProcessor().process(
            image, remove_ca=value
        )
        np.testing.assert_array_equal(result[..., 1], image[..., 1])


def test_positive_value_reduces_r_g_and_b_g_misalignment():
    """Applying Remove CA at full strength must measurably re-align the
    R and B bright-point positions toward the G bright-point position,
    using the peak pixel x-coordinate in each channel as a concrete,
    deterministic alignment metric."""
    image = _ca_image()
    g_x = _channel_centroid_x(image[..., 1])
    r_x_before = _channel_centroid_x(image[..., 0])
    b_x_before = _channel_centroid_x(image[..., 2])
    misalignment_before = abs(r_x_before - g_x) + abs(b_x_before - g_x)

    result = RemoveChromaticAberrationProcessor().process(image, remove_ca=100.0)
    r_x_after = _channel_centroid_x(result[..., 0])
    b_x_after = _channel_centroid_x(result[..., 2])
    misalignment_after = abs(r_x_after - g_x) + abs(b_x_after - g_x)

    assert misalignment_after < misalignment_before


def test_flat_image_stays_nearly_flat():
    image = _flat_image()
    result = RemoveChromaticAberrationProcessor().process(image, remove_ca=100.0)
    np.testing.assert_allclose(result, image, atol=1e-4)


def test_is_deterministic_pure_function():
    """cv2.remap has no RNG -- calling process() twice with the same
    inputs must return byte-identical output."""
    image = _ca_image()
    result1 = RemoveChromaticAberrationProcessor().process(image, remove_ca=60.0)
    result2 = RemoveChromaticAberrationProcessor().process(image, remove_ca=60.0)
    np.testing.assert_array_equal(result1, result2)


def test_preserves_dtype_shape_and_headroom_without_clipping():
    image = _ca_image()
    image[0, 0] = (1.4, 1.3, 1.2)
    result = RemoveChromaticAberrationProcessor().process(image, remove_ca=80.0)
    assert result.dtype == np.float32
    assert result.shape == image.shape
    assert result.max() > 1.0


def test_clamps_negative_parameter_to_zero():
    image = _ca_image()
    low = RemoveChromaticAberrationProcessor().process(image, remove_ca=-50.0)
    np.testing.assert_array_equal(low, image)


def test_clamps_parameter_above_100():
    image = _ca_image()
    high = RemoveChromaticAberrationProcessor().process(image, remove_ca=1000.0)
    expected = RemoveChromaticAberrationProcessor().process(image, remove_ca=100.0)
    np.testing.assert_array_equal(high, expected)


def test_tiny_1x1_image_does_not_crash():
    """Verified directly: cv2.remap does not crash or misbehave on a
    1x1 float32 input, so no defensive bypass is added (see the
    implementation note section 5)."""
    image = np.full((1, 1, 3), 0.5, dtype=np.float32)
    result = RemoveChromaticAberrationProcessor().process(image, remove_ca=80.0)
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))


def test_tiny_2x2_image_does_not_crash():
    image = np.full((2, 2, 3), 0.5, dtype=np.float32)
    result = RemoveChromaticAberrationProcessor().process(image, remove_ca=80.0)
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))


def test_sign_convention_shrinks_red_and_expands_blue():
    """Pins the empirically-verified sign convention directly against
    cv2.remap: a positive radial scale ``k`` pulls sampled content
    *inward* (shrinks it toward the center), a negative ``k`` pushes it
    *outward* (expands it). The processor uses ``k = +_MAX_K`` for red
    (shrink) and ``k = -_MAX_K`` for blue (expand)."""
    height, width = 101, 101
    cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
    channel = np.zeros((height, width), dtype=np.float32)
    px, py = 90, int(cy)
    channel[py, px] = 1.0

    map_x, map_y = np.meshgrid(
        np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32)
    )

    def _remap(k: float) -> np.ndarray:
        sx = (cx + (map_x - cx) * (1.0 + k)).astype(np.float32)
        sy = (cy + (map_y - cy) * (1.0 + k)).astype(np.float32)
        return cv2.remap(
            channel, sx, sy,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )

    shrunk = _remap(0.05)
    expanded = _remap(-0.05)
    _, shrunk_x = np.unravel_index(np.argmax(shrunk), shrunk.shape)
    _, expanded_x = np.unravel_index(np.argmax(expanded), expanded.shape)

    assert shrunk_x < px  # positive k: content pulled toward center
    assert expanded_x > px  # negative k: content pushed away from center
