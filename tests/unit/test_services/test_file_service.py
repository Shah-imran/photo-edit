"""Unit tests for FileService."""

import pytest
from pathlib import Path
from src.services.file_service import FileService


class TestFileService:
    """Test cases for FileService class."""

    def test_file_service_initialization(self):
        """Test FileService can be initialized."""
        service = FileService()
        assert service is not None

    def test_get_image_files_from_directory(self, tmp_path):
        """Test getting image files from a directory."""
        service = FileService()
        
        # Create test image files
        (tmp_path / "image1.jpg").touch()
        (tmp_path / "image2.png").touch()
        (tmp_path / "not_image.txt").touch()
        
        image_files = service.get_image_files_from_directory(str(tmp_path))
        assert len(image_files) == 2
        assert "image1.jpg" in [Path(f).name for f in image_files]
        assert "image2.png" in [Path(f).name for f in image_files]

    def test_get_image_files_recursive(self, tmp_path):
        """Test getting image files recursively."""
        service = FileService()
        
        # Create nested structure
        (tmp_path / "image1.jpg").touch()
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "image2.png").touch()
        
        image_files = service.get_image_files_from_directory(str(tmp_path), recursive=True)
        assert len(image_files) >= 2

    def test_is_image_file(self):
        """Test checking if a file is an image."""
        service = FileService()
        assert service.is_image_file("test.jpg") is True
        assert service.is_image_file("test.png") is True
        assert service.is_image_file("test.tiff") is True
        assert service.is_image_file("test.nef") is True
        assert service.is_image_file("test.txt") is False
        assert service.is_image_file("test") is False

    def test_get_file_extension(self):
        """Test getting file extension."""
        service = FileService()
        assert service.get_file_extension("test.jpg") == ".jpg"
        assert service.get_file_extension("test.image.png") == ".png"
        assert service.get_file_extension("noextension") == ""

    def test_validate_file_path(self, tmp_path):
        """Test validating a file path."""
        service = FileService()
        
        # Create a test file
        test_file = tmp_path / "test.jpg"
        test_file.touch()
        
        assert service.validate_file_path(str(test_file)) is True
        assert service.validate_file_path(str(tmp_path / "nonexistent.jpg")) is False

    def test_create_directory_if_not_exists(self, tmp_path):
        """Test creating directory if it doesn't exist."""
        service = FileService()
        new_dir = tmp_path / "new_directory"
        service.create_directory_if_not_exists(str(new_dir))
        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_get_file_size(self, tmp_path):
        """Test getting file size."""
        service = FileService()
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")
        
        size = service.get_file_size(str(test_file))
        assert size > 0

    def test_get_file_size_nonexistent(self):
        """Test getting file size for non-existent file."""
        service = FileService()
        size = service.get_file_size("nonexistent.txt")
        assert size == 0
