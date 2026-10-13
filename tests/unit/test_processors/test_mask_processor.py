"""Tests for the linear/radial-gradient local-adjustment MaskProcessor
(see docs/planning/implementation-notes/2026-10-13-mask-processor.md)."""

import numpy as np
import pytest

from src.processors.mask_processor import MaskProcessor


def _flat_image(height: int = 40, width: int = 60, value: float = 0.2) -> np.ndarray:
    return np.full((height, width, 3), value, dtype=np.float32)


# ---------------------------------------------------------------------------
# Identity / no-mask
# ---------------------------------------------------------------------------


def test_none_mask_is_exact_identity_copy():
    image = _flat_image()
    result = MaskProcessor().process(image, mask=None)
    np.testing.assert_array_equal(result, image)
    assert result is not image


def test_missing_type_key_is_identity():
    image = _flat_image()
    result = MaskProcessor().process(image, mask={"exposure": 2.0})
    np.testing.assert_array_equal(result, image)


def test_unrecognized_type_is_identity():
    image = _flat_image()
    result = MaskProcessor().process(
        image, mask={"type": "brush", "exposure": 2.0}
    )
    np.testing.assert_array_equal(result, image)


# ---------------------------------------------------------------------------
# Linear gradient: quantitative ramp
# ---------------------------------------------------------------------------


def test_linear_gradient_ramps_from_start_to_end():
    """A strong exposure boost should ramp smoothly from ~0 effect at
    (x0,y0) to ~full effect at (x1,y1), with genuinely intermediate
    values in between -- not just "different somewhere"."""
    image = _flat_image(height=20, width=100, value=0.2)
    mask = {
        "type": "linear",
        "invert": False,
        "x0": 0.0,
        "y0": 0.5,
        "x1": 1.0,
        "y1": 0.5,
        "exposure": 3.0,
        "contrast": 0.0,
        "saturation": 0.0,
        "clarity": 0.0,
    }
    result = MaskProcessor().process(image, mask=mask)

    near_start = result[10, 1, 0]
    quarter = result[10, 25, 0]
    mid = result[10, 50, 0]
    three_quarter = result[10, 75, 0]
    near_end = result[10, 98, 0]

    # Near the start point: close to the unmodified source value.
    np.testing.assert_allclose(near_start, image[10, 1, 0], atol=0.03)
    # Near the end point: close to the fully-boosted (exposure=3.0) value.
    fully_boosted = 0.2 * (2.0 ** 3.0)
    np.testing.assert_allclose(near_end, fully_boosted, atol=0.03)
    # Monotonically increasing across the ramp.
    assert near_start < quarter < mid < three_quarter < near_end


def test_linear_gradient_zero_length_is_degenerate_but_finite():
    """A zero-length gradient (x0,y0) == (x1,y1) must not crash or divide
    by zero; it is treated as fully "on" everywhere."""
    image = _flat_image()
    mask = {
        "type": "linear",
        "x0": 0.5,
        "y0": 0.5,
        "x1": 0.5,
        "y1": 0.5,
        "exposure": 2.0,
    }
    result = MaskProcessor().process(image, mask=mask)
    assert np.all(np.isfinite(result))
    assert result.shape == image.shape


def test_linear_gradient_invert_flips_which_side_is_affected():
    image = _flat_image(height=20, width=100, value=0.2)
    base_mask = {
        "type": "linear",
        "x0": 0.0,
        "y0": 0.5,
        "x1": 1.0,
        "y1": 0.5,
        "exposure": 3.0,
    }
    normal = MaskProcessor().process(image, mask=base_mask)
    inverted = MaskProcessor().process(
        image, mask={**base_mask, "invert": True}
    )
    # Normal: near-start stays near-unchanged, near-end is fully boosted.
    assert normal[10, 1, 0] < normal[10, 98, 0]
    # Inverted: the relationship flips.
    assert inverted[10, 1, 0] > inverted[10, 98, 0]
    np.testing.assert_allclose(
        normal[10, 1, 0], inverted[10, 98, 0], atol=1e-4
    )
    np.testing.assert_allclose(
        normal[10, 98, 0], inverted[10, 1, 0], atol=1e-4
    )


# ---------------------------------------------------------------------------
# Radial gradient
# ---------------------------------------------------------------------------


def test_radial_gradient_concentrates_effect_near_center():
    image = _flat_image(height=100, width=100, value=0.2)
    mask = {
        "type": "radial",
        "cx": 0.5,
        "cy": 0.5,
        "rx": 0.3,
        "ry": 0.3,
        "feather": 0.3,
        "exposure": 3.0,
    }
    result = MaskProcessor().process(image, mask=mask)
    center = result[50, 50, 0]
    beyond_boundary = result[5, 5, 0]
    fully_boosted = 0.2 * (2.0 ** 3.0)
    np.testing.assert_allclose(center, fully_boosted, atol=0.02)
    np.testing.assert_allclose(beyond_boundary, image[5, 5, 0], atol=1e-5)


def test_radial_gradient_invert_flips_which_region_is_affected():
    image = _flat_image(height=100, width=100, value=0.2)
    base_mask = {
        "type": "radial",
        "cx": 0.5,
        "cy": 0.5,
        "rx": 0.3,
        "ry": 0.3,
        "feather": 0.3,
        "exposure": 3.0,
    }
    normal = MaskProcessor().process(image, mask=base_mask)
    inverted = MaskProcessor().process(
        image, mask={**base_mask, "invert": True}
    )
    assert normal[50, 50, 0] > normal[5, 5, 0]
    assert inverted[50, 50, 0] < inverted[5, 5, 0]
    np.testing.assert_allclose(inverted[50, 50, 0], image[50, 50, 0], atol=1e-4)


def test_radial_feather_controls_edge_softness():
    """A low feather produces a sharper (steeper) alpha transition than a
    high feather -- verified quantitatively via the alpha gradient's
    steepness, not just "the images differ"."""
    sharp = MaskProcessor()._compute_alpha(
        200, 200, {"type": "radial", "cx": 0.5, "cy": 0.5, "rx": 0.3, "ry": 0.3, "feather": 0.05}
    )
    soft = MaskProcessor()._compute_alpha(
        200, 200, {"type": "radial", "cx": 0.5, "cy": 0.5, "rx": 0.3, "ry": 0.3, "feather": 0.9}
    )
    row = 100
    # Steepness: max absolute difference between adjacent columns along a
    # horizontal slice through the center.
    sharp_steepness = np.max(np.abs(np.diff(sharp[row].astype(np.float64))))
    soft_steepness = np.max(np.abs(np.diff(soft[row].astype(np.float64))))
    assert sharp_steepness > soft_steepness


def test_radial_degenerate_near_zero_radii_does_not_crash():
    image = _flat_image()
    mask = {
        "type": "radial",
        "cx": 0.5,
        "cy": 0.5,
        "rx": 0.0,
        "ry": 0.0,
        "feather": 0.5,
        "exposure": 2.0,
    }
    result = MaskProcessor().process(image, mask=mask)
    assert np.all(np.isfinite(result))
    assert result.shape == image.shape


def test_radial_aspect_ratio_is_preserved_relative_to_image_proportions():
    """The SAME mask geometry applied to a square and a very wide image
    must keep its shape proportional to each axis's own dimension (the
    key correctness property VignetteProcessor itself had to get right)
    -- not stretched into a different relative shape by image shape."""
    mask = {
        "type": "radial",
        "cx": 0.5,
        "cy": 0.5,
        "rx": 0.2,
        "ry": 0.2,
        "feather": 0.3,
        "exposure": 3.0,
    }
    square = _flat_image(height=100, width=100, value=0.2)
    wide = _flat_image(height=100, width=200, value=0.2)

    square_result = MaskProcessor().process(square, mask=mask)
    wide_result = MaskProcessor().process(wide, mask=mask)

    # On the square image, rx_px == ry_px == 20px: the boundary is equally
    # far in both axes from the center.
    assert square_result[50, 50, 0] > square_result[50, 72, 0]
    np.testing.assert_allclose(
        square_result[50, 72, 0], square_result[72, 50, 0], atol=1e-4
    )

    # On the wide image, rx_px = 0.2 * 200 = 40px, ry_px = 0.2 * 100 = 20px:
    # the boundary is twice as far along x as along y -- a point 40px to
    # the right of center sits at the same relative (normalized) distance
    # as a point 20px below center.
    np.testing.assert_allclose(
        wide_result[50, 100 + 40, 0], wide_result[50 + 20, 100, 0], atol=1e-4
    )
    # And that relative-boundary value matches the square image's own
    # relative-boundary value (both are "at the ellipse edge").
    np.testing.assert_allclose(
        wide_result[50, 100 + 40, 0], square_result[50, 72, 0], atol=1e-4
    )


# ---------------------------------------------------------------------------
# General invariants
# ---------------------------------------------------------------------------


def test_dtype_shape_and_headroom_preserved():
    image = _flat_image(height=30, width=50, value=1.3)  # out-of-gamut headroom
    mask = {
        "type": "radial",
        "cx": 0.5,
        "cy": 0.5,
        "rx": 0.3,
        "ry": 0.3,
        "feather": 0.4,
        "exposure": 0.5,
    }
    result = MaskProcessor().process(image, mask=mask)
    assert result.dtype == np.float32
    assert result.shape == image.shape
    assert np.any(result > 1.0)  # headroom preserved, not clipped


def test_is_deterministic():
    image = _flat_image(height=30, width=50)
    mask = {
        "type": "linear",
        "x0": 0.1,
        "y0": 0.2,
        "x1": 0.9,
        "y1": 0.8,
        "exposure": 1.5,
        "clarity": 20.0,
    }
    result1 = MaskProcessor().process(image, mask=mask)
    result2 = MaskProcessor().process(image, mask=mask)
    np.testing.assert_array_equal(result1, result2)


@pytest.mark.parametrize("value", [0.0, -0.5, 1.5])
def test_saturation_and_clarity_also_apply(value):
    """Confirm the sub-stack's saturation/clarity legs actually run (not
    just exposure/contrast) -- a colored, noisy image should visibly
    change under a mask with only saturation or clarity set."""
    rng = np.random.default_rng(0)
    image = (rng.random((20, 20, 3)).astype(np.float32) * 0.6) + 0.2
    mask = {
        "type": "radial",
        "cx": 0.5,
        "cy": 0.5,
        "rx": 0.6,
        "ry": 0.6,
        "feather": 0.9,
        "saturation": 80.0,
        "clarity": 80.0,
    }
    result = MaskProcessor().process(image, mask=mask)
    assert not np.allclose(result, image)
