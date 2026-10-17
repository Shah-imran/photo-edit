"""Tests for the Defringe (purple/green edge-fringe desaturation) processor."""

import numpy as np

from src.processors.defringe_processor import DefringeProcessor


def _flat_image(height: int = 20, width: int = 20, color=(0.5, 0.5, 0.5)) -> np.ndarray:
    return np.full((height, width, 3), color, dtype=np.float32)


def _edge_fringe_image(
    fringe_color,
    height: int = 40,
    width: int = 80,
    fringe_cols=(38, 42),
    left_value: float = 0.85,
    right_value: float = 0.10,
) -> np.ndarray:
    """A high-contrast vertical edge with a thin fringe strip at the boundary.

    Two flat neutral-gray blocks meet at a vertical boundary; the thin
    strip right at that boundary (``fringe_cols``) holds a strongly
    saturated fringe color instead of a smooth gradient, mimicking the
    real-world artifact Defringe targets: color fringing specifically at
    a high-contrast edge.
    """
    image = np.zeros((height, width, 3), dtype=np.float32)
    image[:, : fringe_cols[0], :] = left_value
    image[:, fringe_cols[1] :, :] = right_value
    image[:, fringe_cols[0] : fringe_cols[1], :] = fringe_color
    return image


def _chroma(image: np.ndarray) -> np.ndarray:
    return image.max(axis=-1) - image.min(axis=-1)


_PURPLE = (0.5, 0.05, 0.55)
_GREEN = (0.1, 0.5, 0.05)
_ORANGE = (0.8, 0.3, 0.05)


def test_zero_is_identity_copy():
    image = _edge_fringe_image(_PURPLE)
    result = DefringeProcessor().process(image, defringe=0.0)
    np.testing.assert_array_equal(result, image)
    assert result is not image


def test_edge_purple_fringe_is_desaturated_but_flat_purple_is_not():
    """The key edge-gating behavior: a purple fringe strip sitting right
    at a high-contrast edge must lose a measurable amount of chroma at
    full strength, while the *same* purple hue in a region with no
    luminance gradient at all (a flat, uniform image) is left
    essentially untouched. This distinguishes genuine edge-gated
    defringing from a global purple desaturation."""
    edge_image = _edge_fringe_image(_PURPLE)
    edge_result = DefringeProcessor().process(edge_image, defringe=100.0)
    fringe_slice = (slice(None), slice(38, 42))
    chroma_before = _chroma(edge_image)[fringe_slice]
    chroma_after = _chroma(edge_result)[fringe_slice]
    # Must be a real, substantial reduction at the edge.
    assert chroma_after.mean() < chroma_before.mean() * 0.9

    flat_image = _flat_image(height=40, width=80, color=_PURPLE)
    flat_result = DefringeProcessor().process(flat_image, defringe=100.0)
    # Sample well away from the array border to avoid any border-handling
    # artifacts from the Sobel convolution; the image is fully uniform so
    # there is no gradient anywhere, border or not.
    interior = (slice(5, 35), slice(5, 75))
    chroma_flat_before = _chroma(flat_image)[interior]
    chroma_flat_after = _chroma(flat_result)[interior]
    np.testing.assert_allclose(chroma_flat_after, chroma_flat_before, atol=1e-5)

    # The edge case's relative chroma loss must be clearly larger than
    # the flat case's (near-zero) loss -- the discriminating claim.
    edge_loss = 1.0 - (chroma_after.mean() / chroma_before.mean())
    flat_loss = 1.0 - (chroma_flat_after.mean() / chroma_flat_before.mean())
    assert edge_loss > 0.1
    assert flat_loss < 1e-4
    assert edge_loss > flat_loss + 0.1


def test_edge_green_fringe_is_desaturated():
    """Green-fringe variant of the purple-fringe edge-gating test."""
    edge_image = _edge_fringe_image(_GREEN)
    result = DefringeProcessor().process(edge_image, defringe=100.0)
    fringe_slice = (slice(None), slice(38, 42))
    chroma_before = _chroma(edge_image)[fringe_slice]
    chroma_after = _chroma(result)[fringe_slice]
    assert chroma_after.mean() < chroma_before.mean() * 0.9


def test_non_purple_non_green_edge_receives_little_desaturation():
    """A strongly saturated red/orange edge is outside both hue bands and
    must receive little to no desaturation, verifying the hue-band gating
    actually discriminates by color rather than just by edge strength."""
    edge_image = _edge_fringe_image(_ORANGE)
    result = DefringeProcessor().process(edge_image, defringe=100.0)
    fringe_slice = (slice(None), slice(38, 42))
    chroma_before = _chroma(edge_image)[fringe_slice]
    chroma_after = _chroma(result)[fringe_slice]
    # Allow a small amount of residual desaturation from the Gaussian
    # hue-band tails, but it must be a tiny fraction of the purple/green
    # loss measured above (which exceeds 10%).
    relative_loss = 1.0 - (chroma_after.mean() / chroma_before.mean())
    assert relative_loss < 0.02


def test_flat_image_stays_exactly_flat():
    image = _flat_image(color=(0.2, 0.6, 0.3))
    result = DefringeProcessor().process(image, defringe=100.0)
    np.testing.assert_allclose(result, image, atol=1e-5)


def test_is_deterministic_pure_function():
    image = _edge_fringe_image(_PURPLE)
    result1 = DefringeProcessor().process(image, defringe=60.0)
    result2 = DefringeProcessor().process(image, defringe=60.0)
    np.testing.assert_array_equal(result1, result2)


def test_preserves_dtype_shape_and_headroom_without_clipping():
    image = _edge_fringe_image(_PURPLE)
    image[0, 0] = (1.4, 0.05, 1.3)
    result = DefringeProcessor().process(image, defringe=80.0)
    assert result.dtype == np.float32
    assert result.shape == image.shape
    assert result.max() > 1.0


def test_clamps_negative_parameter_to_zero():
    image = _edge_fringe_image(_PURPLE)
    low = DefringeProcessor().process(image, defringe=-50.0)
    np.testing.assert_array_equal(low, image)


def test_clamps_parameter_above_100():
    image = _edge_fringe_image(_PURPLE)
    high = DefringeProcessor().process(image, defringe=1000.0)
    expected = DefringeProcessor().process(image, defringe=100.0)
    np.testing.assert_array_equal(high, expected)


def test_tiny_1x1_image_does_not_crash():
    """Verified directly: cv2.Sobel does not crash on a 1x1 float32
    input (it returns an all-zero gradient under its border handling),
    so no defensive bypass is added (see the implementation note)."""
    image = np.full((1, 1, 3), 0.5, dtype=np.float32)
    result = DefringeProcessor().process(image, defringe=80.0)
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))


def test_tiny_2x2_image_does_not_crash():
    image = np.full((2, 2, 3), 0.5, dtype=np.float32)
    result = DefringeProcessor().process(image, defringe=80.0)
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))
