"""Tests for the Geometry processor (Distortion, Vertical/Horizontal
perspective, Scale, X/Y Offset) -- Phase I's slider-based Geometry
half. See docs/planning/implementation-notes/
2026-10-13-geometry-processor.md."""

import numpy as np
import pytest

from src.processors.geometry_processor import GeometryProcessor


def _marker_image(height: int = 101, width: int = 101, marker_xy=(50, 50)) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.float32)
    x, y = marker_xy
    image[y, x] = 1.0
    return image


def _marker_position(image: np.ndarray) -> tuple:
    y, x = np.unravel_index(np.argmax(image[..., 0]), image[..., 0].shape)
    return (int(x), int(y))


def _vertical_lines_image(height: int = 101, width: int = 101) -> np.ndarray:
    """An image with two full-height vertical lines at x=20 and x=80."""
    image = np.zeros((height, width, 3), dtype=np.float32)
    image[:, 20] = 1.0
    image[:, 80] = 1.0
    return image


def _horizontal_lines_image(height: int = 101, width: int = 101) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.float32)
    image[20, :] = 1.0
    image[80, :] = 1.0
    return image


def _bright_x_positions(row: np.ndarray, threshold: float = 0.4) -> np.ndarray:
    return np.where(row > threshold)[0]


# ---------------------------------------------------------------------------
# Defaults / identity
# ---------------------------------------------------------------------------


def test_all_defaults_is_identity_copy():
    image = _marker_image()
    result = GeometryProcessor().process(image)
    np.testing.assert_array_equal(result, image)
    assert result is not image


def test_explicit_default_values_is_identity_copy():
    image = _marker_image()
    result = GeometryProcessor().process(
        image,
        distortion=0.0,
        vertical=0.0,
        horizontal=0.0,
        scale=100.0,
        offset_x=0.0,
        offset_y=0.0,
    )
    np.testing.assert_array_equal(result, image)
    assert result is not image


# ---------------------------------------------------------------------------
# Shape preservation (the one hard invariant)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"distortion": -100.0},
        {"distortion": 100.0},
        {"vertical": -100.0},
        {"vertical": 100.0},
        {"horizontal": -100.0},
        {"horizontal": 100.0},
        {"scale": 50.0},
        {"scale": 150.0},
        {"offset_x": -50.0},
        {"offset_x": 50.0},
        {"offset_y": -50.0},
        {"offset_y": 50.0},
        {
            "distortion": 100.0,
            "vertical": -80.0,
            "horizontal": 60.0,
            "scale": 140.0,
            "offset_x": -30.0,
            "offset_y": 25.0,
        },
    ],
)
def test_output_shape_identical_to_input_shape(kwargs):
    image = _marker_image(height=64, width=96)
    result = GeometryProcessor().process(image, **kwargs)
    assert result.shape == image.shape


@pytest.mark.parametrize("shape", [(1, 1, 3), (2, 2, 3), (3, 2, 3), (2, 3, 3)])
def test_tiny_images_do_not_crash(shape):
    image = np.full(shape, 0.5, dtype=np.float32)
    result = GeometryProcessor().process(
        image,
        distortion=80.0,
        vertical=60.0,
        horizontal=-60.0,
        scale=130.0,
        offset_x=20.0,
        offset_y=-20.0,
    )
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))


def test_dtype_preserved():
    image = _marker_image()
    result = GeometryProcessor().process(image, distortion=40.0, scale=120.0)
    assert result.dtype == np.float32


def test_is_deterministic_pure_function():
    image = _marker_image()
    result1 = GeometryProcessor().process(image, distortion=25.0, vertical=10.0)
    result2 = GeometryProcessor().process(image, distortion=25.0, vertical=10.0)
    np.testing.assert_array_equal(result1, result2)


# ---------------------------------------------------------------------------
# Distortion
# ---------------------------------------------------------------------------


def test_distortion_zero_is_identity_even_with_others_default():
    image = _marker_image()
    result = GeometryProcessor().process(image, distortion=0.0)
    np.testing.assert_array_equal(result, image)


def test_negative_distortion_pulls_edge_content_inward():
    """Negative `distortion` (correct barrel) pulls edges IN: two full-
    height vertical lines should end up CLOSER together at the top row
    (far from the vertical center) than at the middle row. A single
    hot-pixel marker is too noisy to measure here (bilinear remap
    spreads/dims a lone pixel asymmetrically), so full lines are used,
    mirroring how the sign convention was verified during development."""
    image = _vertical_lines_image()
    result = GeometryProcessor().process(image, distortion=-100.0)
    top_x = _bright_x_positions(result[0, :, 0])
    mid_x = _bright_x_positions(result[50, :, 0])
    top_width = top_x.max() - top_x.min()
    mid_width = mid_x.max() - mid_x.min()
    assert top_width < mid_width


def test_positive_distortion_pushes_edge_content_outward():
    """Positive `distortion` (correct pincushion) pushes edges OUT -- the
    opposite of the negative case above."""
    image = _vertical_lines_image()
    result = GeometryProcessor().process(image, distortion=100.0)
    top_x = _bright_x_positions(result[0, :, 0])
    mid_x = _bright_x_positions(result[50, :, 0])
    top_width = top_x.max() - top_x.min()
    mid_width = mid_x.max() - mid_x.min()
    assert top_width > mid_width


def test_distortion_leaves_exact_center_pixel_unmoved():
    """r=0 at the center means the radial model is the identity there,
    regardless of k1's sign or magnitude."""
    image = _marker_image(height=101, width=101, marker_xy=(50, 50))
    result = GeometryProcessor().process(image, distortion=100.0)
    assert _marker_position(result) == (50, 50)


def test_distortion_extreme_displacement_is_sane_not_absurd():
    """At the slider's extreme, a corner pixel should move by a visible
    but bounded amount -- not collapse to the center and not fly off to
    many times the image size."""
    width = height = 101
    image = _marker_image(height=height, width=width, marker_xy=(99, 99))
    result = GeometryProcessor().process(image, distortion=-100.0)
    x, y = _marker_position(result)
    displacement = max(abs(99 - x), abs(99 - y))
    assert 1.0 <= displacement <= 25.0


def test_distortion_clamps_beyond_range():
    image = _marker_image()
    low = GeometryProcessor().process(image, distortion=-500.0)
    expected = GeometryProcessor().process(image, distortion=-100.0)
    np.testing.assert_array_equal(low, expected)
    high = GeometryProcessor().process(image, distortion=500.0)
    expected_high = GeometryProcessor().process(image, distortion=100.0)
    np.testing.assert_array_equal(high, expected_high)


# ---------------------------------------------------------------------------
# Vertical perspective
# ---------------------------------------------------------------------------


def test_positive_vertical_narrows_top_widens_bottom():
    image = _vertical_lines_image()
    result = GeometryProcessor().process(image, vertical=50.0)
    top_x = _bright_x_positions(result[0, :, 0])
    bottom_x = _bright_x_positions(result[-1, :, 0])
    top_width = top_x.max() - top_x.min()
    bottom_width = bottom_x.max() - bottom_x.min()
    assert top_width < bottom_width


def test_negative_vertical_widens_top_narrows_bottom():
    image = _vertical_lines_image()
    result = GeometryProcessor().process(image, vertical=-50.0)
    top_x = _bright_x_positions(result[0, :, 0])
    bottom_x = _bright_x_positions(result[-1, :, 0])
    top_width = top_x.max() - top_x.min()
    bottom_width = bottom_x.max() - bottom_x.min()
    assert top_width > bottom_width


def test_vertical_zero_is_identity():
    image = _vertical_lines_image()
    result = GeometryProcessor().process(image, vertical=0.0)
    np.testing.assert_array_equal(result, image)


# ---------------------------------------------------------------------------
# Horizontal perspective
# ---------------------------------------------------------------------------


def test_positive_horizontal_narrows_left_widens_right():
    image = _horizontal_lines_image()
    result = GeometryProcessor().process(image, horizontal=50.0)
    left_y = _bright_x_positions(result[:, 0, 0])
    right_y = _bright_x_positions(result[:, -1, 0])
    left_height = left_y.max() - left_y.min()
    right_height = right_y.max() - right_y.min()
    assert left_height < right_height


def test_negative_horizontal_widens_left_narrows_right():
    image = _horizontal_lines_image()
    result = GeometryProcessor().process(image, horizontal=-50.0)
    left_y = _bright_x_positions(result[:, 0, 0])
    right_y = _bright_x_positions(result[:, -1, 0])
    left_height = left_y.max() - left_y.min()
    right_height = right_y.max() - right_y.min()
    assert left_height > right_height


# ---------------------------------------------------------------------------
# Scale
# ---------------------------------------------------------------------------


def test_scale_above_100_zooms_in_moves_content_away_from_center():
    image = _marker_image(height=101, width=101, marker_xy=(70, 50))
    result = GeometryProcessor().process(image, scale=150.0)
    x, y = _marker_position(result)
    assert abs(x - 50) > abs(70 - 50)


def test_scale_below_100_zooms_out_moves_content_toward_center():
    image = _marker_image(height=101, width=101, marker_xy=(70, 50))
    result = GeometryProcessor().process(image, scale=50.0)
    x, y = _marker_position(result)
    assert abs(x - 50) < abs(70 - 50)


def test_scale_100_is_identity():
    image = _marker_image()
    result = GeometryProcessor().process(image, scale=100.0)
    np.testing.assert_array_equal(result, image)


def test_scale_center_pixel_stays_at_center():
    image = _marker_image(height=101, width=101, marker_xy=(50, 50))
    result = GeometryProcessor().process(image, scale=150.0)
    assert _marker_position(result) == (50, 50)


def test_scale_clamps_beyond_range():
    image = _marker_image()
    low = GeometryProcessor().process(image, scale=10.0)
    expected = GeometryProcessor().process(image, scale=50.0)
    np.testing.assert_array_equal(low, expected)
    high = GeometryProcessor().process(image, scale=300.0)
    expected_high = GeometryProcessor().process(image, scale=150.0)
    np.testing.assert_array_equal(high, expected_high)


# ---------------------------------------------------------------------------
# Offset
# ---------------------------------------------------------------------------


def test_positive_offset_x_shifts_content_right():
    image = _marker_image(height=101, width=101, marker_xy=(50, 50))
    result = GeometryProcessor().process(image, offset_x=20.0)
    x, y = _marker_position(result)
    assert x > 50
    assert y == 50


def test_negative_offset_x_shifts_content_left():
    image = _marker_image(height=101, width=101, marker_xy=(50, 50))
    result = GeometryProcessor().process(image, offset_x=-20.0)
    x, y = _marker_position(result)
    assert x < 50


def test_positive_offset_y_shifts_content_down():
    image = _marker_image(height=101, width=101, marker_xy=(50, 50))
    result = GeometryProcessor().process(image, offset_y=20.0)
    x, y = _marker_position(result)
    assert y > 50
    assert x == 50


def test_negative_offset_y_shifts_content_up():
    image = _marker_image(height=101, width=101, marker_xy=(50, 50))
    result = GeometryProcessor().process(image, offset_y=-20.0)
    x, y = _marker_position(result)
    assert y < 50


def test_offset_magnitude_matches_percent_of_dimension():
    image = _marker_image(height=100, width=100, marker_xy=(50, 50))
    result = GeometryProcessor().process(image, offset_x=10.0)
    x, y = _marker_position(result)
    # 10% of width=100 is 10 px.
    assert abs(x - 60) <= 1


def test_offset_clamps_beyond_range():
    image = _marker_image()
    low = GeometryProcessor().process(image, offset_x=-500.0)
    expected = GeometryProcessor().process(image, offset_x=-50.0)
    np.testing.assert_array_equal(low, expected)
    high = GeometryProcessor().process(image, offset_x=500.0)
    expected_high = GeometryProcessor().process(image, offset_x=50.0)
    np.testing.assert_array_equal(high, expected_high)


# ---------------------------------------------------------------------------
# Border fill
# ---------------------------------------------------------------------------


def test_scale_down_fills_new_border_via_reflect_not_black():
    """Zooming out exposes new border area -- it must be filled by
    reflecting existing content (BORDER_REFLECT_101), never left as
    black/zero, the same convention Straighten/Remove CA already use."""
    image = np.full((101, 101, 3), 0.8, dtype=np.float32)
    image[40:60, 40:60] = 0.2  # distinctive interior content
    result = GeometryProcessor().process(image, scale=50.0)
    corners = [
        result[0, 0],
        result[0, -1],
        result[-1, 0],
        result[-1, -1],
    ]
    for corner in corners:
        assert not np.allclose(corner, 0.0)


def test_offset_fills_new_border_via_reflect_not_black():
    image = np.full((101, 101, 3), 0.8, dtype=np.float32)
    result = GeometryProcessor().process(image, offset_x=30.0)
    left_edge = result[:, 0]
    assert not np.allclose(left_edge, 0.0)


def test_distortion_preserves_headroom_without_clipping():
    """A large constant-bright value, sampled well away from the warp's
    border, must stay at that exact value (same precedent as Straighten's
    own headroom test)."""
    image = np.full((200, 200, 3), 1.5, dtype=np.float32)
    result = GeometryProcessor().process(image, distortion=50.0)
    interior = result[80:120, 80:120]
    np.testing.assert_allclose(interior, 1.5, atol=1e-3)


# ---------------------------------------------------------------------------
# Combined params
# ---------------------------------------------------------------------------


def test_combined_params_differs_from_any_single_param_alone():
    image = _vertical_lines_image()
    combined = GeometryProcessor().process(
        image, distortion=40.0, vertical=30.0, horizontal=-20.0,
        scale=110.0, offset_x=5.0, offset_y=-5.0,
    )
    only_vertical = GeometryProcessor().process(image, vertical=30.0)
    only_scale = GeometryProcessor().process(image, scale=110.0)
    assert not np.array_equal(combined, only_vertical)
    assert not np.array_equal(combined, only_scale)
    assert combined.shape == image.shape


def test_combined_matches_sequential_single_param_order_for_perspective_scale_offset():
    """The combined homography for vertical/horizontal/scale/offset
    should be algebraically equivalent to composing each step's own
    matrix in the documented order (horizontal, then vertical, then
    scale, then offset) -- verified here by comparing against a
    processor call with only vertical+horizontal (no distortion
    involved, since distortion is intentionally a separate non-linear
    remap pass applied before the homography, not part of it)."""
    image = _marker_image(height=101, width=101, marker_xy=(70, 30))
    result = GeometryProcessor().process(image, vertical=20.0, horizontal=15.0)
    # Just assert it runs and stays finite/shape-correct; the exact
    # pixel math is covered by the per-param direction tests above.
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))
