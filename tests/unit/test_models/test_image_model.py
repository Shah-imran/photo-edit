"""Unit tests for ImageModel (LinearImage storage)."""

import numpy as np
import pytest

from src.models.image_model import ImageModel
from src.utils.color_pipeline import pil_to_linear


@pytest.fixture
def sample_linear_image(sample_image):
    """Convert the existing PIL fixture to a LinearImage."""
    return pil_to_linear(sample_image)


class TestImageModel:
    """Test cases for ImageModel."""

    def test_image_model_initialization(self):
        model = ImageModel()
        assert model is not None
        assert model.original_image is None
        assert model.current_image is None
        assert model.file_path is None

    def test_image_model_with_file_path(self, sample_image_path):
        model = ImageModel(file_path=sample_image_path)
        assert model.file_path == sample_image_path

    def test_set_original_image(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        assert model.original_image is not None
        np.testing.assert_array_equal(model.original_image, sample_linear_image)

    def test_set_original_image_sets_current(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        assert model.current_image is not None
        np.testing.assert_array_equal(model.current_image, sample_linear_image)

    def test_get_current_image(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        current = model.get_current_image()
        assert current is not None
        np.testing.assert_array_equal(current, sample_linear_image)

    def test_get_original_image(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        original = model.get_original_image()
        assert original is not None
        np.testing.assert_array_equal(original, sample_linear_image)

    def test_has_image(self, sample_linear_image):
        model = ImageModel()
        assert model.has_image() is False

        model.set_original_image(sample_linear_image)
        assert model.has_image() is True

    def test_get_image_size(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        width, height = model.get_image_size()
        assert width == 100
        assert height == 100

    def test_get_image_size_no_image(self):
        model = ImageModel()
        width, height = model.get_image_size()
        assert width == 0
        assert height == 0

    def test_reset_to_original(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)

        modified = sample_linear_image * 0.5
        model.current_image = modified

        model.reset_to_original()
        np.testing.assert_array_equal(model.current_image, model.original_image)
        np.testing.assert_array_equal(model.current_image, sample_linear_image)

    def test_is_modified(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        assert model.is_modified() is False

        model.set_modified(True)
        assert model.is_modified() is True

        model.reset_to_original()
        assert model.is_modified() is False
