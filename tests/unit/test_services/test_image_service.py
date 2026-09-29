"""Unit tests for ImageService (LinearImage I/O)."""

import numpy as np
import pytest

from src.services.image_service import ImageService
from src.utils.color_pipeline import pil_to_linear


@pytest.fixture
def sample_linear_image(sample_image):
    return pil_to_linear(sample_image)


class TestImageService:
    """Test cases for ImageService."""

    def test_image_service_initialization(self):
        service = ImageService()
        assert service is not None

    def test_load_image_valid_file_returns_linear_array(self, sample_image_path):
        service = ImageService()
        image = service.load_image(sample_image_path)
        assert isinstance(image, np.ndarray)
        assert image.dtype == np.float32
        assert image.shape == (100, 100, 3)
        assert 0.0 <= image.min() <= image.max() <= 1.0

    def test_load_image_invalid_file(self):
        service = ImageService()
        with pytest.raises(FileNotFoundError):
            service.load_image("nonexistent.jpg")

    def test_load_image_png(self, sample_png_path):
        service = ImageService()
        image = service.load_image(sample_png_path)
        assert isinstance(image, np.ndarray)
        assert image.dtype == np.float32
        assert image.shape == (200, 200, 3)

    def test_save_image_jpeg_round_trips(self, sample_linear_image, tmp_path):
        service = ImageService()
        output_path = tmp_path / "output.jpg"
        service.save_image(sample_linear_image, str(output_path), format="JPEG")
        assert output_path.exists()

        loaded = service.load_image(str(output_path))
        assert loaded.shape == sample_linear_image.shape

    def test_save_image_png_round_trips_within_one_lsb(
        self, sample_linear_image, tmp_path
    ):
        service = ImageService()
        output_path = tmp_path / "output.png"
        service.save_image(sample_linear_image, str(output_path), format="PNG")
        assert output_path.exists()

        loaded = service.load_image(str(output_path))
        # PNG is lossless; the only error should be 8-bit quantization
        # of the linear -> sRGB -> uint8 -> sRGB -> linear round-trip.
        diff = np.abs(loaded - sample_linear_image)
        assert diff.max() < 0.01

    def test_save_image_with_quality(self, sample_linear_image, tmp_path):
        service = ImageService()
        output_path = tmp_path / "output.jpg"
        service.save_image(
            sample_linear_image, str(output_path), format="JPEG", quality=95
        )
        assert output_path.exists()

    def test_get_supported_formats(self):
        service = ImageService()
        formats = service.get_supported_formats()
        assert isinstance(formats, list)
        assert "JPEG" in formats
        assert "PNG" in formats

    def test_is_format_supported(self):
        service = ImageService()
        assert service.is_format_supported("JPEG") is True
        assert service.is_format_supported("PNG") is True
        assert service.is_format_supported("INVALID") is False

    def test_create_thumbnail_returns_linear_array_of_target_size(
        self, sample_linear_image
    ):
        service = ImageService()
        thumbnail = service.create_thumbnail(sample_linear_image, size=(50, 50))
        assert isinstance(thumbnail, np.ndarray)
        assert thumbnail.dtype == np.float32
        assert thumbnail.shape == (50, 50, 3)

    def test_create_thumbnail_maintains_aspect(self, sample_linear_image):
        service = ImageService()
        thumbnail = service.create_thumbnail(sample_linear_image, size=(50, 30))
        h, w = thumbnail.shape[:2]
        # Original is 100x100; clamping to 50x30 keeps the square shape at 30x30.
        assert h == w

    def test_get_image_info(self, sample_image_path):
        service = ImageService()
        info = service.get_image_info(sample_image_path)
        assert info is not None
        assert info["width"] == 100
        assert info["height"] == 100
