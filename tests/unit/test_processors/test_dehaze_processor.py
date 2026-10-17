"""Tests for the linear-light Dehaze processor."""

import numpy as np

from src.processors.dehaze_processor import DehazeProcessor


def _detail_image() -> np.ndarray:
    grid = np.indices((17, 17)).sum(axis=0) % 2
    return np.repeat((0.4 + grid[..., None] * 0.2).astype(np.float32), 3, axis=2)


def test_zero_is_identity_copy():
    image = _detail_image()
    result = DehazeProcessor().process(image, dehaze=0.0)
    np.testing.assert_array_equal(result, image)
    assert result is not image


def test_positive_dehaze_reduces_synthetic_veil():
    """A simulated haze veil (added light gray) should be pulled back down
    by a sufficiently positive Dehaze value, relative to the hazy input."""
    base = _detail_image()
    veil_amount = 0.35
    hazy = base + veil_amount * (0.85 - base)
    dehazed = DehazeProcessor().process(hazy, dehaze=100.0)
    # Removing haze should bring the result's mean back down, closer to
    # (or below) the clean base image's mean, rather than staying as
    # bright as the hazy input.
    assert dehazed.mean() < hazy.mean()


def test_negative_adds_haze():
    image = _detail_image()
    hazy = DehazeProcessor().process(image, dehaze=-60.0)
    # Adding fog should reduce local contrast (pull values toward the
    # light gray haze color) relative to the clean image.
    assert hazy.std() < image.std()
    assert hazy.mean() > image.mean()


def test_constant_neutral_image_is_stable_without_color_cast():
    image = np.full((11, 13, 3), 0.42, dtype=np.float32)
    result = DehazeProcessor().process(image, dehaze=80.0)
    np.testing.assert_allclose(result[..., 0], result[..., 1], atol=1e-6)
    np.testing.assert_allclose(result[..., 1], result[..., 2], atol=1e-6)


def test_negative_constant_neutral_image_is_stable_without_color_cast():
    image = np.full((11, 13, 3), 0.42, dtype=np.float32)
    result = DehazeProcessor().process(image, dehaze=-50.0)
    np.testing.assert_allclose(result[..., 0], result[..., 1], atol=1e-6)
    np.testing.assert_allclose(result[..., 1], result[..., 2], atol=1e-6)


def test_preserves_dtype_shape_and_headroom_without_clipping():
    image = _detail_image()
    image[8, 8] = 1.4
    result = DehazeProcessor().process(image, dehaze=50.0)
    assert result.dtype == np.float32
    assert result.shape == image.shape
    # Headroom above 1.0 is not forcibly clipped by the processor itself.
    assert result.max() > 1.0


def test_clamps_parameter_and_handles_tiny_images():
    image = np.full((1, 1, 3), 0.5, dtype=np.float32)
    high = DehazeProcessor().process(image, dehaze=1000.0)
    expected = DehazeProcessor().process(image, dehaze=100.0)
    np.testing.assert_array_equal(high, expected)

    low = DehazeProcessor().process(image, dehaze=-1000.0)
    expected_low = DehazeProcessor().process(image, dehaze=-100.0)
    np.testing.assert_array_equal(low, expected_low)


def test_distinct_from_clarity_and_texture_semantics():
    """Dehaze is a different operation (veil removal), not another
    signed-residual local-contrast trick at yet another scale -- see
    docs/planning/implementation-notes/2026-10-12-dehaze.md section 1."""
    from src.processors.clarity_processor import ClarityProcessor
    from src.processors.texture_processor import TextureProcessor

    assert not hasattr(DehazeProcessor, "_SIGMA") or (
        DehazeProcessor._SIGMA != ClarityProcessor._SIGMA
        and DehazeProcessor._SIGMA != TextureProcessor._SIGMA
    )
