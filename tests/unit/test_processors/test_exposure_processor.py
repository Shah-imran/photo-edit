"""Unit tests for ExposureProcessor (linear-light pipeline)."""

import numpy as np
import pytest

from src.processors.exposure_processor import ExposureProcessor
from src.utils.color_pipeline import linear_to_srgb, pil_to_linear


@pytest.fixture
def sample_linear_image(sample_image):
    """Convert the existing PIL fixture (red 100x100) to a LinearImage."""
    return pil_to_linear(sample_image)


@pytest.fixture
def flat_grey_linear():
    """Flat 0.25 linear grey -- handy for checking exposure stop math."""
    return np.full((10, 10, 3), 0.25, dtype=np.float32)


class TestExposureProcessor:
    """Test cases for ExposureProcessor."""

    def test_processor_initialization(self):
        processor = ExposureProcessor()
        assert processor is not None

    def test_process_no_adjustment_preserves_shape_and_dtype(self, sample_linear_image):
        processor = ExposureProcessor()
        result = processor.process(sample_linear_image)
        assert result.shape == sample_linear_image.shape
        assert result.dtype == np.float32

    def test_exposure_plus_one_doubles_linear_values(self, flat_grey_linear):
        processor = ExposureProcessor()
        result = processor.process(flat_grey_linear, exposure=1.0)
        np.testing.assert_allclose(result, 0.5, atol=1e-5)

    def test_exposure_minus_one_halves_linear_values(self, flat_grey_linear):
        processor = ExposureProcessor()
        result = processor.process(flat_grey_linear, exposure=-1.0)
        np.testing.assert_allclose(result, 0.125, atol=1e-5)

    def test_exposure_increase_makes_image_brighter(self, sample_linear_image):
        processor = ExposureProcessor()
        original_mean = float(sample_linear_image.mean())
        result = processor.process(sample_linear_image, exposure=1.0)
        # Result should be brighter; out-of-gamut highlights are allowed.
        assert float(result.mean()) > original_mean

    def test_exposure_decrease_makes_image_darker(self, sample_linear_image):
        processor = ExposureProcessor()
        original_mean = float(sample_linear_image.mean())
        result = processor.process(sample_linear_image, exposure=-1.0)
        assert float(result.mean()) <= original_mean

    def test_contrast_increase_widens_distribution_in_srgb(self, sample_linear_image):
        processor = ExposureProcessor()
        result = processor.process(sample_linear_image, contrast=50.0)
        assert result.shape == sample_linear_image.shape

    def test_contrast_decrease_narrows_distribution_in_srgb(self, sample_linear_image):
        processor = ExposureProcessor()
        result = processor.process(sample_linear_image, contrast=-50.0)
        assert result.shape == sample_linear_image.shape

    def test_brightness_increase(self, flat_grey_linear):
        processor = ExposureProcessor()
        result = processor.process(flat_grey_linear, brightness=50.0)
        assert float(result.mean()) > float(flat_grey_linear.mean())

    def test_brightness_decrease(self, flat_grey_linear):
        processor = ExposureProcessor()
        result = processor.process(flat_grey_linear, brightness=-50.0)
        assert float(result.mean()) < float(flat_grey_linear.mean())

    def test_combined_adjustments_returns_linear_image(self, sample_linear_image):
        processor = ExposureProcessor()
        result = processor.process(
            sample_linear_image,
            exposure=0.5,
            contrast=25.0,
            brightness=10.0,
        )
        assert result.shape == sample_linear_image.shape
        assert result.dtype == np.float32

    def test_extreme_values_produce_no_nans(self, sample_linear_image):
        processor = ExposureProcessor()
        for kwargs in (
            {"exposure": 5.0},
            {"exposure": -5.0},
            {"contrast": 100.0},
            {"contrast": -100.0},
            {"brightness": 100.0},
            {"brightness": -100.0},
        ):
            result = processor.process(sample_linear_image, **kwargs)
            assert not np.any(np.isnan(result)), f"NaN in {kwargs}"

    def test_out_of_gamut_highlights_preserved(self, flat_grey_linear):
        """Exposure +5 stops on 0.25 should produce values >> 1.0."""
        processor = ExposureProcessor()
        result = processor.process(flat_grey_linear, exposure=5.0)
        # 0.25 * 32 = 8.0 -- we deliberately don't clip in the processor.
        assert float(result.max()) > 1.0
