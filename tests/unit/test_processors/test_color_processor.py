"""Unit tests for ColorProcessor (linear-light pipeline)."""

import numpy as np
import pytest

from src.processors.color_processor import ColorProcessor
from src.utils.color_pipeline import pil_to_linear


def _saturation(image):
    """HSV saturation (max - min) / max per pixel."""
    maxc = image.max(axis=-1)
    return (maxc - image.min(axis=-1)) / np.maximum(maxc, 1e-6)


@pytest.fixture
def sample_linear_image(sample_image):
    return pil_to_linear(sample_image)


@pytest.fixture
def saturated_linear():
    """Mostly-red flat patch in linear space, useful for desaturation tests."""
    arr = np.zeros((4, 4, 3), dtype=np.float32)
    arr[..., 0] = 0.8
    arr[..., 1] = 0.1
    arr[..., 2] = 0.1
    return arr


class TestColorProcessor:
    """Test cases for ColorProcessor."""

    def test_process_no_adjustment_preserves_shape_and_dtype(self, sample_linear_image):
        processor = ColorProcessor()
        result = processor.process(sample_linear_image)
        assert result.shape == sample_linear_image.shape
        assert result.dtype == np.float32

    def test_saturation_minus_100_collapses_to_grayscale_v(self, saturated_linear):
        processor = ColorProcessor()
        result = processor.process(saturated_linear, saturation=-100.0)
        # OpenCV HSV V == max(R, G, B); when S = 0 every channel == V.
        v = saturated_linear.max(axis=-1, keepdims=True)
        np.testing.assert_allclose(result, np.broadcast_to(v, result.shape), atol=1e-5)

    def test_saturation_increase_keeps_dtype(self, sample_linear_image):
        processor = ColorProcessor()
        result = processor.process(sample_linear_image, saturation=50.0)
        assert result.shape == sample_linear_image.shape
        assert result.dtype == np.float32

    def test_vibrance_increase_grows_low_saturation_more(self):
        processor = ColorProcessor()
        # A muted pixel (S=0.2) and a vivid one (S=0.9), same hue.
        image = np.array([[[0.5, 0.45, 0.4], [0.5, 0.15, 0.05]]], dtype=np.float32)

        result = processor.process(image, vibrance=100.0)

        before = _saturation(image)
        gain = _saturation(result) - before
        assert gain[0, 0] > 0.0 and gain[0, 1] > 0.0
        assert gain[0, 0] > 2.0 * gain[0, 1]

    def test_vibrance_decrease_reduces_saturation(self):
        processor = ColorProcessor()
        image = np.array([[[0.5, 0.45, 0.4], [0.5, 0.15, 0.05]]], dtype=np.float32)

        result = processor.process(image, vibrance=-50.0)

        assert np.all(_saturation(result) < _saturation(image))

    def test_combined_adjustments(self, sample_linear_image):
        processor = ColorProcessor()
        result = processor.process(
            sample_linear_image,
            saturation=20.0,
            vibrance=20.0,
        )
        assert result.shape == sample_linear_image.shape
        assert result.dtype == np.float32
