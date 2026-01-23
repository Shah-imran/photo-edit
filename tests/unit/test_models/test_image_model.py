"""Unit tests for ImageModel."""

import pytest
from PIL import Image
from pathlib import Path
from src.models.image_model import ImageModel


class TestImageModel:
    """Test cases for ImageModel class."""

    def test_image_model_initialization(self):
        """Test ImageModel can be initialized."""
        model = ImageModel()
        assert model is not None
        assert model.original_image is None
        assert model.current_image is None
        assert model.file_path is None

    def test_image_model_with_file_path(self, sample_image_path):
        """Test ImageModel initialization with file path."""
        model = ImageModel(file_path=sample_image_path)
        assert model.file_path == sample_image_path

    def test_set_original_image(self, sample_image):
        """Test setting original image."""
        model = ImageModel()
        model.set_original_image(sample_image)
        assert model.original_image is not None
        assert model.original_image == sample_image

    def test_set_original_image_sets_current(self, sample_image):
        """Test that setting original image also sets current image."""
        model = ImageModel()
        model.set_original_image(sample_image)
        assert model.current_image is not None
        assert model.current_image == sample_image

    def test_get_current_image(self, sample_image):
        """Test getting current image."""
        model = ImageModel()
        model.set_original_image(sample_image)
        current = model.get_current_image()
        assert current is not None
        assert current == sample_image

    def test_get_original_image(self, sample_image):
        """Test getting original image."""
        model = ImageModel()
        model.set_original_image(sample_image)
        original = model.get_original_image()
        assert original is not None
        assert original == sample_image

    def test_has_image(self, sample_image):
        """Test has_image method."""
        model = ImageModel()
        assert model.has_image() is False
        
        model.set_original_image(sample_image)
        assert model.has_image() is True

    def test_get_image_size(self, sample_image):
        """Test getting image size."""
        model = ImageModel()
        model.set_original_image(sample_image)
        width, height = model.get_image_size()
        assert width == 100
        assert height == 100

    def test_get_image_size_no_image(self):
        """Test getting image size when no image is loaded."""
        model = ImageModel()
        width, height = model.get_image_size()
        assert width == 0
        assert height == 0

    def test_reset_to_original(self, sample_image):
        """Test resetting to original image."""
        model = ImageModel()
        model.set_original_image(sample_image)
        
        # Modify current image
        modified = sample_image.copy()
        model.current_image = modified
        
        # Reset
        model.reset_to_original()
        assert model.current_image == model.original_image
        assert model.current_image == sample_image

    def test_is_modified(self, sample_image):
        """Test checking if image is modified."""
        model = ImageModel()
        model.set_original_image(sample_image)
        assert model.is_modified() is False
        
        # Mark as modified
        model.set_modified(True)
        assert model.is_modified() is True
        
        # Reset to original should clear modified flag
        model.reset_to_original()
        assert model.is_modified() is False
