"""Tests for the linear-light Vignette processor."""

import numpy as np

from src.processors.vignette_processor import VignetteProcessor


def _bright_image(height: int = 41, width: int = 41) -> np.ndarray:
    return np.full((height, width, 3), 0.8, dtype=np.float32)


def _detail_image() -> np.ndarray:
    grid = np.indices((21, 21)).sum(axis=0) % 2
    return np.repeat((0.4 + grid[..., None] * 0.2).astype(np.float32), 3, axis=2)


def test_zero_is_identity_copy():
    image = _detail_image()
    result = VignetteProcessor().process(image, vignette=0.0)
    np.testing.assert_array_equal(result, image)
    assert result is not image


def test_positive_vignette_darkens_corners_more_than_center():
    image = _bright_image()
    result = VignetteProcessor().process(image, vignette=80.0)
    center = result[20, 20].mean()
    corner = result[0, 0].mean()
    assert corner < center
    # Center should stay (near) unaffected by the smoothstep midpoint.
    np.testing.assert_allclose(center, image[20, 20].mean(), atol=1e-5)
    assert corner < image[0, 0].mean()


def test_negative_vignette_lightens_corners_more_than_center():
    image = _bright_image()
    result = VignetteProcessor().process(image, vignette=-80.0)
    center = result[20, 20].mean()
    corner = result[0, 0].mean()
    assert corner > center
    np.testing.assert_allclose(center, image[20, 20].mean(), atol=1e-5)
    assert corner > image[0, 0].mean()


def test_tiny_image_does_not_divide_by_zero():
    image = np.full((1, 1, 3), 0.5, dtype=np.float32)
    result = VignetteProcessor().process(image, vignette=80.0)
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))


def test_non_square_image_works():
    image = np.full((9, 31, 3), 0.6, dtype=np.float32)
    result = VignetteProcessor().process(image, vignette=70.0)
    assert result.shape == image.shape
    assert np.all(np.isfinite(result))
    # The corners (farthest in the normalized aspect-correct radius) should
    # darken more than the vertical/horizontal edge midpoints.
    center_row, center_col = 4, 15
    corner_val = result[0, 0].mean()
    center_val = result[center_row, center_col].mean()
    assert corner_val < center_val


def test_constant_neutral_image_is_stable_without_color_cast():
    image = np.full((11, 13, 3), 0.42, dtype=np.float32)
    result = VignetteProcessor().process(image, vignette=60.0)
    np.testing.assert_allclose(result[..., 0], result[..., 1], atol=1e-6)
    np.testing.assert_allclose(result[..., 1], result[..., 2], atol=1e-6)


def test_negative_constant_neutral_image_is_stable_without_color_cast():
    image = np.full((11, 13, 3), 0.42, dtype=np.float32)
    result = VignetteProcessor().process(image, vignette=-60.0)
    np.testing.assert_allclose(result[..., 0], result[..., 1], atol=1e-6)
    np.testing.assert_allclose(result[..., 1], result[..., 2], atol=1e-6)


def test_preserves_dtype_shape_and_headroom_without_clipping():
    image = _detail_image()
    image[0, 0] = 1.4
    result = VignetteProcessor().process(image, vignette=-50.0)
    assert result.dtype == np.float32
    assert result.shape == image.shape
    # Headroom above 1.0 is not forcibly clipped by the processor itself.
    assert result.max() > 1.0


def test_clamps_parameter_and_handles_tiny_images():
    image = np.full((1, 1, 3), 0.5, dtype=np.float32)
    high = VignetteProcessor().process(image, vignette=1000.0)
    expected = VignetteProcessor().process(image, vignette=100.0)
    np.testing.assert_array_equal(high, expected)

    low = VignetteProcessor().process(image, vignette=-1000.0)
    expected_low = VignetteProcessor().process(image, vignette=-100.0)
    np.testing.assert_array_equal(low, expected_low)


def test_distinct_from_texture_clarity_dehaze_semantics():
    """Vignette is a spatially radial mask, not another blur-based local
    operation at yet another scale -- see
    docs/planning/implementation-notes/2026-10-12-vignette.md section 1."""
    from src.processors.clarity_processor import ClarityProcessor
    from src.processors.dehaze_processor import DehazeProcessor
    from src.processors.texture_processor import TextureProcessor

    # Vignette has no blur sigma at all -- it should not define one of the
    # other processors' scale attributes.
    assert not hasattr(VignetteProcessor, "_SIGMA")
    assert hasattr(ClarityProcessor, "_SIGMA")
    assert hasattr(TextureProcessor, "_SIGMA")
    assert hasattr(DehazeProcessor, "_SIGMA")
