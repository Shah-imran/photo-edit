"""Tests for the linear-light Clarity processor."""

import numpy as np

from src.processors.clarity_processor import ClarityProcessor


def _detail_image() -> np.ndarray:
    grid = np.indices((17, 17)).sum(axis=0) % 2
    return np.repeat((0.4 + grid[..., None] * 0.2).astype(np.float32), 3, axis=2)


def test_zero_is_identity_copy():
    image = _detail_image()
    result = ClarityProcessor().process(image, clarity=0.0)
    np.testing.assert_array_equal(result, image)
    assert result is not image


def test_positive_enhances_and_negative_softens_detail():
    image = _detail_image()
    processor = ClarityProcessor()
    enhanced = processor.process(image, clarity=100.0)
    softened = processor.process(image, clarity=-100.0)
    assert enhanced.std() > image.std()
    assert softened.std() < image.std()


def test_constant_neutral_image_is_stable_without_color_cast():
    image = np.full((11, 13, 3), 0.42, dtype=np.float32)
    result = ClarityProcessor().process(image, clarity=80.0)
    np.testing.assert_allclose(result, image, atol=1e-6)
    np.testing.assert_allclose(result[..., 0], result[..., 1], atol=1e-7)
    np.testing.assert_allclose(result[..., 1], result[..., 2], atol=1e-7)


def test_preserves_dtype_shape_and_headroom_without_clipping():
    image = _detail_image()
    image[8, 8] = 1.4
    result = ClarityProcessor().process(image, clarity=100.0)
    assert result.dtype == np.float32
    assert result.shape == image.shape
    assert result[8, 8, 0] > 1.0


def test_clamps_parameter_and_handles_tiny_images():
    image = np.full((1, 1, 3), 0.5, dtype=np.float32)
    high = ClarityProcessor().process(image, clarity=1000.0)
    expected = ClarityProcessor().process(image, clarity=100.0)
    np.testing.assert_array_equal(high, expected)


def test_uses_a_coarser_scale_than_texture():
    """Clarity's sigma must be distinct from (larger than) Texture's.

    See docs/planning/implementation-notes/2026-09-30-texture.md section 6:
    "Phase G's later Clarity and sharpening slices must use distinct
    scales/semantics."
    """
    from src.processors.texture_processor import TextureProcessor

    assert ClarityProcessor._SIGMA > TextureProcessor._SIGMA
