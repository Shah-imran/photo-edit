"""Tests for the Crop processor (the one deliberately shape-changing
processor in this codebase -- see docs/planning/implementation-notes/
2026-10-13-crop-processor.md)."""

import numpy as np
import pytest

from src.processors.crop_processor import CropProcessor


def _quadrant_image(height: int = 4, width: int = 4) -> np.ndarray:
    """A single-channel-distinguishable image where each quadrant has a
    distinct, easily-asserted value."""
    image = np.zeros((height, width, 3), dtype=np.float32)
    half_h, half_w = height // 2, width // 2
    image[:half_h, :half_w] = 1.0   # top-left
    image[:half_h, half_w:] = 2.0   # top-right
    image[half_h:, :half_w] = 3.0   # bottom-left
    image[half_h:, half_w:] = 4.0   # bottom-right
    return image


def test_full_frame_default_is_identity_copy():
    image = _quadrant_image()
    result = CropProcessor().process(image, x0=0.0, y0=0.0, x1=1.0, y1=1.0)
    np.testing.assert_array_equal(result, image)
    assert result is not image


def test_crop_produces_correct_sliced_sub_array():
    """Crop to the top-left quadrant and confirm it matches exactly."""
    image = _quadrant_image(height=4, width=4)
    result = CropProcessor().process(image, x0=0.0, y0=0.0, x1=0.5, y1=0.5)
    expected = image[0:2, 0:2]
    np.testing.assert_array_equal(result, expected)
    assert np.all(result == 1.0)


def test_crop_to_bottom_right_quadrant():
    image = _quadrant_image(height=4, width=4)
    result = CropProcessor().process(image, x0=0.5, y0=0.5, x1=1.0, y1=1.0)
    expected = image[2:4, 2:4]
    np.testing.assert_array_equal(result, expected)
    assert np.all(result == 4.0)


def test_output_shape_is_smaller_than_input_shape_for_a_real_crop():
    """The one deliberate shape-change test in this whole codebase --
    every other processor preserves (H, W, C) exactly; Crop must not."""
    image = _quadrant_image(height=100, width=200)
    result = CropProcessor().process(image, x0=0.25, y0=0.25, x1=0.75, y1=0.75)
    assert result.shape != image.shape
    assert result.shape[0] < image.shape[0]
    assert result.shape[1] < image.shape[1]
    assert result.shape[2] == image.shape[2]


@pytest.mark.parametrize(
    "x0,y0,x1,y1",
    [
        (-0.5, 0.0, 1.5, 1.0),   # x out of range both directions
        (0.0, -0.5, 1.0, 1.5),   # y out of range both directions
        (-2.0, -2.0, 2.0, 2.0),  # everything wildly out of range
    ],
)
def test_clamps_out_of_range_input(x0, y0, x1, y1):
    image = _quadrant_image()
    result = CropProcessor().process(image, x0=x0, y0=y0, x1=x1, y1=y1)
    # Out-of-range values clamp to [0, 1] on each side -- here that
    # always clamps back out to the full frame, so the result should be
    # an identity copy.
    np.testing.assert_array_equal(result, image)


def test_swaps_reversed_x_coordinates():
    image = _quadrant_image(height=4, width=4)
    swapped = CropProcessor().process(image, x0=0.5, y0=0.0, x1=0.0, y1=0.5)
    expected = CropProcessor().process(image, x0=0.0, y0=0.0, x1=0.5, y1=0.5)
    np.testing.assert_array_equal(swapped, expected)


def test_swaps_reversed_y_coordinates():
    image = _quadrant_image(height=4, width=4)
    swapped = CropProcessor().process(image, x0=0.0, y0=0.5, x1=0.5, y1=0.0)
    expected = CropProcessor().process(image, x0=0.0, y0=0.0, x1=0.5, y1=0.5)
    np.testing.assert_array_equal(swapped, expected)


def test_degenerate_near_zero_area_rectangle_is_still_non_empty():
    image = _quadrant_image(height=50, width=50)
    result = CropProcessor().process(image, x0=0.5, y0=0.5, x1=0.5001, y1=0.5001)
    assert result.size > 0
    assert result.shape[0] >= 1
    assert result.shape[1] >= 1


def test_tiny_1x1_image_does_not_crash():
    image = np.full((1, 1, 3), 0.5, dtype=np.float32)
    result = CropProcessor().process(image, x0=0.2, y0=0.2, x1=0.8, y1=0.8)
    assert result.shape[0] >= 1
    assert result.shape[1] >= 1
    assert result.shape[2] == 3
    assert np.all(np.isfinite(result))


def test_dtype_is_float32():
    image = _quadrant_image()
    result = CropProcessor().process(image, x0=0.1, y0=0.1, x1=0.9, y1=0.9)
    assert result.dtype == np.float32


def test_is_deterministic():
    image = _quadrant_image(height=20, width=20)
    result1 = CropProcessor().process(image, x0=0.2, y0=0.3, x1=0.8, y1=0.7)
    result2 = CropProcessor().process(image, x0=0.2, y0=0.3, x1=0.8, y1=0.7)
    np.testing.assert_array_equal(result1, result2)


def test_result_does_not_alias_source():
    """copy=True on the returned slice -- a view into `source` must not
    alias it, so mutating the result must not mutate the source."""
    image = _quadrant_image(height=10, width=10)
    result = CropProcessor().process(image, x0=0.0, y0=0.0, x1=0.5, y1=0.5)
    result[0, 0, 0] = -999.0
    assert image[0, 0, 0] != -999.0
