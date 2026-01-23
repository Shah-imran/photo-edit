"""Unit tests for ImageService."""

import pytest
from PIL import Image
from pathlib import Path
from src.services.image_service import ImageService


class TestImageService:
    """Test cases for ImageService class."""

    def test_image_service_initialization(self):
        """Test ImageService can be initialized."""
        service = ImageService()
        assert service is not None

    def test_load_image_valid_file(self, sample_image_path):
        """Test loading a valid image file."""
        service = ImageService()
        image = service.load_image(sample_image_path)
        assert image is not None
        assert isinstance(image, Image.Image)
        assert image.size == (100, 100)

    def test_load_image_invalid_file(self):
        """Test loading a non-existent file raises error."""
        service = ImageService()
        with pytest.raises(FileNotFoundError):
            service.load_image("nonexistent.jpg")

    def test_load_image_png(self, sample_png_path):
        """Test loading a PNG file."""
        service = ImageService()
        image = service.load_image(sample_png_path)
        assert image is not None
        assert isinstance(image, Image.Image)
        assert image.size == (200, 200)

    def test_save_image_jpeg(self, sample_image, tmp_path):
        """Test saving an image as JPEG."""
        service = ImageService()
        output_path = tmp_path / "output.jpg"
        service.save_image(sample_image, str(output_path), format="JPEG")
        assert output_path.exists()
        
        # Verify it can be loaded back
        loaded = service.load_image(str(output_path))
        assert loaded is not None
        assert loaded.size == sample_image.size

    def test_save_image_png(self, sample_image, tmp_path):
        """Test saving an image as PNG."""
        service = ImageService()
        output_path = tmp_path / "output.png"
        service.save_image(sample_image, str(output_path), format="PNG")
        assert output_path.exists()
        
        loaded = service.load_image(str(output_path))
        assert loaded is not None

    def test_save_image_with_quality(self, sample_image, tmp_path):
        """Test saving JPEG with quality setting."""
        service = ImageService()
        output_path = tmp_path / "output.jpg"
        service.save_image(sample_image, str(output_path), format="JPEG", quality=95)
        assert output_path.exists()

    def test_get_supported_formats(self):
        """Test getting list of supported formats."""
        service = ImageService()
        formats = service.get_supported_formats()
        assert isinstance(formats, list)
        assert "JPEG" in formats
        assert "PNG" in formats

    def test_is_format_supported(self):
        """Test checking if a format is supported."""
        service = ImageService()
        assert service.is_format_supported("JPEG") is True
        assert service.is_format_supported("PNG") is True
        assert service.is_format_supported("INVALID") is False

    def test_create_thumbnail(self, sample_image):
        """Test creating a thumbnail."""
        service = ImageService()
        thumbnail = service.create_thumbnail(sample_image, size=(50, 50))
        assert thumbnail is not None
        assert thumbnail.size == (50, 50)

    def test_create_thumbnail_maintains_aspect(self, sample_image):
        """Test thumbnail maintains aspect ratio."""
        service = ImageService()
        # Original is 100x100, request 50x30 should maintain aspect
        thumbnail = service.create_thumbnail(sample_image, size=(50, 30))
        assert thumbnail is not None
        # Should be 30x30 to maintain square aspect
        assert thumbnail.size[0] == thumbnail.size[1]

    def test_get_image_info(self, sample_image_path):
        """Test getting image information."""
        service = ImageService()
        info = service.get_image_info(sample_image_path)
        assert info is not None
        assert "width" in info
        assert "height" in info
        assert "format" in info
        assert info["width"] == 100
        assert info["height"] == 100
