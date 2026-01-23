"""Unit tests for ExposureProcessor."""

import pytest
from PIL import Image
import numpy as np
from src.processors.exposure_processor import ExposureProcessor


class TestExposureProcessor:
    """Test cases for ExposureProcessor class."""

    def test_processor_initialization(self):
        """Test ExposureProcessor can be initialized."""
        processor = ExposureProcessor()
        assert processor is not None

    def test_process_no_adjustment(self, sample_image):
        """Test processing with no adjustments returns similar image."""
        processor = ExposureProcessor()
        result = processor.process(sample_image)
        assert result is not None
        assert result.size == sample_image.size
        assert result.mode == sample_image.mode

    def test_exposure_increase(self, sample_image):
        """Test increasing exposure makes image brighter."""
        processor = ExposureProcessor()
        original_mean = np.array(sample_image).mean()
        
        result = processor.process(sample_image, exposure=1.0)
        result_mean = np.array(result).mean()
        
        # Result should be brighter (higher mean, but capped at 255)
        assert result_mean >= original_mean or result_mean == 255

    def test_exposure_decrease(self, sample_image):
        """Test decreasing exposure makes image darker."""
        processor = ExposureProcessor()
        original_mean = np.array(sample_image).mean()
        
        result = processor.process(sample_image, exposure=-1.0)
        result_mean = np.array(result).mean()
        
        assert result_mean <= original_mean

    def test_contrast_increase(self, sample_image):
        """Test increasing contrast."""
        processor = ExposureProcessor()
        result = processor.process(sample_image, contrast=50.0)
        assert result is not None
        assert result.size == sample_image.size

    def test_contrast_decrease(self, sample_image):
        """Test decreasing contrast."""
        processor = ExposureProcessor()
        result = processor.process(sample_image, contrast=-50.0)
        assert result is not None
        assert result.size == sample_image.size

    def test_brightness_increase(self, sample_image):
        """Test increasing brightness."""
        processor = ExposureProcessor()
        original_mean = np.array(sample_image).mean()
        
        result = processor.process(sample_image, brightness=50.0)
        result_mean = np.array(result).mean()
        
        assert result_mean >= original_mean

    def test_brightness_decrease(self, sample_image):
        """Test decreasing brightness."""
        processor = ExposureProcessor()
        original_mean = np.array(sample_image).mean()
        
        result = processor.process(sample_image, brightness=-50.0)
        result_mean = np.array(result).mean()
        
        assert result_mean <= original_mean

    def test_combined_adjustments(self, sample_image):
        """Test applying multiple adjustments together."""
        processor = ExposureProcessor()
        result = processor.process(
            sample_image,
            exposure=0.5,
            contrast=25.0,
            brightness=10.0
        )
        assert result is not None
        assert result.size == sample_image.size

    def test_extreme_values(self, sample_image):
        """Test with extreme adjustment values."""
        processor = ExposureProcessor()
        
        # Max exposure
        result = processor.process(sample_image, exposure=5.0)
        assert result is not None
        
        # Min exposure
        result = processor.process(sample_image, exposure=-5.0)
        assert result is not None
        
        # Max contrast
        result = processor.process(sample_image, contrast=100.0)
        assert result is not None
        
        # Min contrast
        result = processor.process(sample_image, contrast=-100.0)
        assert result is not None
