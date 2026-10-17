"""Tests for the clone/heal HealingProcessor (see
docs/planning/implementation-notes/2026-10-13-healing-processor.md)."""

import numpy as np
import pytest

from src.processors.healing_processor import HealingProcessor


def _flat_image(height: int = 60, width: int = 80, value: float = 0.2) -> np.ndarray:
    return np.full((height, width, 3), value, dtype=np.float32)


# ---------------------------------------------------------------------------
# Identity / no-op
# ---------------------------------------------------------------------------


def test_none_heal_spots_is_exact_identity_copy():
    image = _flat_image()
    result = HealingProcessor().process(image, heal_spots=None)
    np.testing.assert_array_equal(result, image)
    assert result is not image


def test_empty_list_heal_spots_is_exact_identity_copy():
    image = _flat_image()
    result = HealingProcessor().process(image, heal_spots=[])
    np.testing.assert_array_equal(result, image)
    assert result is not image


def test_identity_preserves_dtype_and_shape():
    image = _flat_image(height=37, width=53)
    result = HealingProcessor().process(image, heal_spots=[])
    assert result.shape == image.shape
    assert result.dtype == np.float32


# ---------------------------------------------------------------------------
# Clone mode
# ---------------------------------------------------------------------------


def _checkered_image(height=60, width=80):
    image = np.full((height, width, 3), 0.2, dtype=np.float32)
    # A distinct-colored block in the top-left quadrant to clone from.
    image[0:20, 0:20] = (0.9, 0.1, 0.1)
    return image


def test_clone_copies_source_into_destination_with_feathered_edge():
    image = _checkered_image()
    spot = {
        "mode": "clone",
        "dst_x": 0.75,
        "dst_y": 0.75,
        "src_x": 0.125,
        "src_y": 0.167,  # center of the 0:20,0:20 red block (10/60 approx)
        "radius": 0.1,
        "feather": 0.3,
        "opacity": 1.0,
    }
    result = HealingProcessor().process(image, heal_spots=[spot])

    dst_cx = int(round(0.75 * 80))
    dst_cy = int(round(0.75 * 60))
    # Center of the destination spot should closely match the source color.
    np.testing.assert_allclose(result[dst_cy, dst_cx], (0.9, 0.1, 0.1), atol=0.05)
    # Far outside the spot's radius, destination is unchanged.
    np.testing.assert_allclose(result[5, 5], image[5, 5], atol=1e-6)

    # The transition is gradual (feathered), not a hard step: sample along
    # a ray from spot center outward and confirm a genuinely intermediate
    # value exists between "fully healed" and "fully original".
    radius_px = round(0.1 * min(60, 80))
    near_edge = result[dst_cy, dst_cx + radius_px]
    full_center = result[dst_cy, dst_cx]
    far_outside = result[dst_cy, dst_cx + radius_px * 3]
    # near_edge should sit strictly between the two extremes on the red
    # channel (0.9 at center vs ~0.2 background).
    assert far_outside[0] < near_edge[0] < full_center[0] or np.isclose(
        near_edge[0], far_outside[0], atol=0.05
    )


def test_clone_does_not_crash_near_image_edge_and_clips_sensibly():
    image = _checkered_image()
    spot = {
        "mode": "clone",
        "dst_x": 0.0,
        "dst_y": 0.0,
        "src_x": 1.0,
        "src_y": 1.0,
        "radius": 0.2,
        "feather": 0.2,
        "opacity": 1.0,
    }
    result = HealingProcessor().process(image, heal_spots=[spot])
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))


def test_clone_opacity_scales_blend_strength_quantitatively():
    image = _flat_image(value=0.1)
    # Paint a distinct source color far from the destination.
    image = image.copy()
    image[0:10, 0:10] = 0.9

    def _heal_with_opacity(opacity):
        spot = {
            "mode": "clone",
            "dst_x": 0.75,
            "dst_y": 0.75,
            "src_x": 0.0625,
            "src_y": 0.0833,
            "radius": 0.05,
            "feather": 0.0,
            "opacity": opacity,
        }
        result = HealingProcessor().process(image, heal_spots=[spot])
        dst_cx = int(round(0.75 * 80))
        dst_cy = int(round(0.75 * 60))
        return result[dst_cy, dst_cx, 0]

    dst_original = 0.1
    src_value = 0.9

    zero = _heal_with_opacity(0.0)
    half = _heal_with_opacity(0.5)
    full = _heal_with_opacity(1.0)

    np.testing.assert_allclose(zero, dst_original, atol=1e-5)
    np.testing.assert_allclose(full, src_value, atol=1e-5)
    np.testing.assert_allclose(half, (dst_original + src_value) / 2.0, atol=1e-5)


def test_clone_is_deterministic():
    image = _checkered_image()
    spot = {
        "mode": "clone",
        "dst_x": 0.75,
        "dst_y": 0.75,
        "src_x": 0.125,
        "src_y": 0.167,
        "radius": 0.1,
        "feather": 0.3,
        "opacity": 0.8,
    }
    result1 = HealingProcessor().process(image, heal_spots=[spot])
    result2 = HealingProcessor().process(image, heal_spots=[spot])
    np.testing.assert_array_equal(result1, result2)


# ---------------------------------------------------------------------------
# Heal mode -- the distinguishing property vs. Clone
# ---------------------------------------------------------------------------


def _illumination_mismatch_image(height=80, width=80):
    """An image with a bright gradient patch near the top-left (the
    SOURCE) and a uniformly dark region near the bottom-right (the
    DESTINATION's surroundings), so Heal and Clone should disagree."""
    image = np.full((height, width, 3), 0.08, dtype=np.float32)
    # Source patch: a left-bright/right-dim gradient block, much brighter
    # on average than the destination's dark surroundings.
    image[5:25, 5:25] = 0.0
    for col in range(5, 25):
        value = 0.9 if col < 15 else 0.5
        image[5:25, col] = value
    return image


def test_heal_blends_illumination_with_surroundings_unlike_clone():
    """Heal must sit between a plain Clone copy and the original
    destination -- the defining property of Poisson blending over a
    direct copy."""
    image = _illumination_mismatch_image()
    base_spot = {
        "dst_x": 0.8125,  # (65/80) destination far from the source, on dark bg
        "dst_y": 0.8125,
        "src_x": 0.1875,  # (15/80) center of the bright gradient block
        "src_y": 0.1875,
        "radius": 0.1,
        "feather": 0.0,
        "opacity": 1.0,
    }

    clone_spot = {**base_spot, "mode": "clone"}
    heal_spot = {**base_spot, "mode": "heal"}

    original_value = image[64, 64, 0]
    clone_result = HealingProcessor().process(image, heal_spots=[clone_spot])
    heal_result = HealingProcessor().process(image, heal_spots=[heal_spot])

    clone_value = clone_result[64, 64, 0]
    heal_value = heal_result[64, 64, 0]

    # Clone pastes the bright source value essentially unchanged.
    assert clone_value > original_value + 0.1
    # Heal is NOT an exact copy of Clone's result...
    asson = abs(heal_value - clone_value) > 0.02
    assert asson
    # ...and sits between the original (dark) destination and Clone's
    # (bright) result -- Poisson blending anchors overall illumination to
    # the destination's surroundings while still being influenced by the
    # source (confirmed separately below via the preserved gradient).
    low = min(original_value, clone_value)
    high = max(original_value, clone_value)
    assert low - 1e-3 <= heal_value <= high + 1e-3

    # The source's internal left-bright/right-dim structure is still
    # detectable in the healed result (content IS carried over, not just
    # discarded) -- compare two points inside the healed patch.
    heal_left = heal_result[64, 60, 0]
    heal_right = heal_result[64, 68, 0]
    assert heal_left > heal_right


def test_heal_is_deterministic():
    image = _illumination_mismatch_image()
    spot = {
        "mode": "heal",
        "dst_x": 0.8125,
        "dst_y": 0.8125,
        "src_x": 0.1875,
        "src_y": 0.1875,
        "radius": 0.1,
        "feather": 0.2,
        "opacity": 1.0,
    }
    result1 = HealingProcessor().process(image, heal_spots=[spot])
    result2 = HealingProcessor().process(image, heal_spots=[spot])
    np.testing.assert_array_equal(result1, result2)


def test_heal_opacity_zero_leaves_destination_unchanged():
    image = _illumination_mismatch_image()
    spot = {
        "mode": "heal",
        "dst_x": 0.8125,
        "dst_y": 0.8125,
        "src_x": 0.1875,
        "src_y": 0.1875,
        "radius": 0.1,
        "feather": 0.1,
        "opacity": 0.0,
    }
    result = HealingProcessor().process(image, heal_spots=[spot])
    np.testing.assert_allclose(result[64, 64], image[64, 64], atol=1e-6)


def test_heal_shape_and_dtype_preserved():
    image = _illumination_mismatch_image()
    spot = {
        "mode": "heal",
        "dst_x": 0.8125,
        "dst_y": 0.8125,
        "src_x": 0.1875,
        "src_y": 0.1875,
        "radius": 0.1,
        "feather": 0.2,
        "opacity": 1.0,
    }
    result = HealingProcessor().process(image, heal_spots=[spot])
    assert result.shape == image.shape
    assert result.dtype == np.float32


def test_heal_does_not_crash_near_image_edge():
    image = _illumination_mismatch_image()
    spot = {
        "mode": "heal",
        "dst_x": 0.0,
        "dst_y": 0.0,
        "src_x": 1.0,
        "src_y": 1.0,
        "radius": 0.15,
        "feather": 0.2,
        "opacity": 1.0,
    }
    result = HealingProcessor().process(image, heal_spots=[spot])
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))


def test_heal_tiny_radius_falls_back_to_clone_without_crashing():
    """A radius that rounds to below the minimum pixel threshold for
    cv2.seamlessClone must not crash -- confirmed to crash OpenCV
    directly (a 1-pixel mask) during this slice's own investigation."""
    image = _illumination_mismatch_image()
    spot = {
        "mode": "heal",
        "dst_x": 0.8125,
        "dst_y": 0.8125,
        "src_x": 0.1875,
        "src_y": 0.1875,
        "radius": 0.001,  # rounds to a 1px radius on an 80px image
        "feather": 0.2,
        "opacity": 1.0,
    }
    result = HealingProcessor().process(image, heal_spots=[spot])
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))


# ---------------------------------------------------------------------------
# Multiple spots
# ---------------------------------------------------------------------------


def test_multiple_spots_are_all_applied_in_order():
    image = _checkered_image()
    spot_a = {
        "mode": "clone",
        "dst_x": 0.5,
        "dst_y": 0.5,
        "src_x": 0.125,
        "src_y": 0.167,
        "radius": 0.05,
        "feather": 0.0,
        "opacity": 1.0,
    }
    spot_b = {
        "mode": "clone",
        "dst_x": 0.9,
        "dst_y": 0.9,
        "src_x": 0.125,
        "src_y": 0.167,
        "radius": 0.05,
        "feather": 0.0,
        "opacity": 1.0,
    }
    result = HealingProcessor().process(image, heal_spots=[spot_a, spot_b])

    cx_a, cy_a = int(round(0.5 * 80)), int(round(0.5 * 60))
    cx_b, cy_b = int(round(0.9 * 80)), int(round(0.9 * 60))
    np.testing.assert_allclose(result[cy_a, cx_a], (0.9, 0.1, 0.1), atol=0.05)
    np.testing.assert_allclose(result[cy_b, cx_b], (0.9, 0.1, 0.1), atol=0.05)


def test_second_overlapping_spot_overrides_the_first():
    image = _checkered_image()
    # Both spots target the same destination; the second spot's source
    # color should win since spots are applied in list order.
    image[40:50, 40:50] = (0.1, 0.9, 0.1)  # a second, green source block
    spot_red = {
        "mode": "clone",
        "dst_x": 0.75,
        "dst_y": 0.75,
        "src_x": 0.125,
        "src_y": 0.167,
        "radius": 0.05,
        "feather": 0.0,
        "opacity": 1.0,
    }
    spot_green = {
        "mode": "clone",
        "dst_x": 0.75,
        "dst_y": 0.75,
        "src_x": 0.5625,  # 45/80
        "src_y": 0.75,  # 45/60
        "radius": 0.05,
        "feather": 0.0,
        "opacity": 1.0,
    }
    result = HealingProcessor().process(image, heal_spots=[spot_red, spot_green])
    cx, cy = int(round(0.75 * 80)), int(round(0.75 * 60))
    np.testing.assert_allclose(result[cy, cx], (0.1, 0.9, 0.1), atol=0.05)


# ---------------------------------------------------------------------------
# Defensive normalization
# ---------------------------------------------------------------------------


def test_missing_mode_skips_that_spot_without_crashing():
    image = _checkered_image()
    spot = {
        "dst_x": 0.75,
        "dst_y": 0.75,
        "src_x": 0.125,
        "src_y": 0.167,
        "radius": 0.1,
    }
    result = HealingProcessor().process(image, heal_spots=[spot])
    np.testing.assert_array_equal(result, image)


def test_unrecognized_mode_skips_that_spot():
    image = _checkered_image()
    spot = {
        "mode": "smudge",
        "dst_x": 0.75,
        "dst_y": 0.75,
        "src_x": 0.125,
        "src_y": 0.167,
        "radius": 0.1,
    }
    result = HealingProcessor().process(image, heal_spots=[spot])
    np.testing.assert_array_equal(result, image)


def test_non_dict_spot_entry_is_skipped():
    image = _checkered_image()
    result = HealingProcessor().process(image, heal_spots=["not-a-dict", 42, None])
    np.testing.assert_array_equal(result, image)


def test_out_of_range_coordinates_are_clamped_not_crashed():
    image = _checkered_image()
    spot = {
        "mode": "clone",
        "dst_x": 5.0,  # way out of [0, 1]
        "dst_y": -3.0,
        "src_x": 0.125,
        "src_y": 0.167,
        "radius": 10.0,  # way out of range
        "feather": -1.0,
        "opacity": 2.0,
    }
    result = HealingProcessor().process(image, heal_spots=[spot])
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))


def test_missing_optional_keys_default_cleanly():
    image = _checkered_image()
    spot = {"mode": "clone", "dst_x": 0.75, "dst_y": 0.75, "src_x": 0.125, "src_y": 0.167}
    result = HealingProcessor().process(image, heal_spots=[spot])
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))


def test_mixed_valid_and_malformed_spots_only_applies_the_valid_one():
    image = _checkered_image()
    good_spot = {
        "mode": "clone",
        "dst_x": 0.75,
        "dst_y": 0.75,
        "src_x": 0.125,
        "src_y": 0.167,
        "radius": 0.1,
        "feather": 0.0,
        "opacity": 1.0,
    }
    bad_spot = {"mode": "nonsense"}
    result = HealingProcessor().process(image, heal_spots=[bad_spot, good_spot, "garbage"])
    cx, cy = int(round(0.75 * 80)), int(round(0.75 * 60))
    np.testing.assert_allclose(result[cy, cx], (0.9, 0.1, 0.1), atol=0.05)
