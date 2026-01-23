"""Unit tests for ProjectModel."""

import pytest
from src.models.project_model import ProjectModel


class TestProjectModel:
    """Test cases for ProjectModel class."""

    def test_project_model_initialization(self):
        """Test ProjectModel can be initialized."""
        model = ProjectModel()
        assert model is not None
        assert model.project_path is None
        assert model.images == []
        assert model.current_image_index is None

    def test_project_model_with_path(self):
        """Test ProjectModel initialization with project path."""
        path = "/path/to/project.json"
        model = ProjectModel(project_path=path)
        assert model.project_path == path

    def test_add_image(self):
        """Test adding an image to the project."""
        model = ProjectModel()
        image_path = "/path/to/image.jpg"
        model.add_image(image_path)
        assert len(model.images) == 1
        assert model.images[0] == image_path

    def test_add_multiple_images(self):
        """Test adding multiple images to the project."""
        model = ProjectModel()
        image_paths = ["/path/to/image1.jpg", "/path/to/image2.jpg"]
        for path in image_paths:
            model.add_image(path)
        assert len(model.images) == 2
        assert model.images == image_paths

    def test_remove_image(self):
        """Test removing an image from the project."""
        model = ProjectModel()
        image_path = "/path/to/image.jpg"
        model.add_image(image_path)
        model.remove_image(image_path)
        assert len(model.images) == 0

    def test_remove_nonexistent_image(self):
        """Test removing an image that doesn't exist."""
        model = ProjectModel()
        model.add_image("/path/to/image1.jpg")
        # Should not raise error, just do nothing
        model.remove_image("/path/to/nonexistent.jpg")
        assert len(model.images) == 1

    def test_get_image_count(self):
        """Test getting the number of images in the project."""
        model = ProjectModel()
        assert model.get_image_count() == 0
        
        model.add_image("/path/to/image1.jpg")
        assert model.get_image_count() == 1
        
        model.add_image("/path/to/image2.jpg")
        assert model.get_image_count() == 2

    def test_set_current_image_index(self):
        """Test setting the current image index."""
        model = ProjectModel()
        model.add_image("/path/to/image1.jpg")
        model.add_image("/path/to/image2.jpg")
        
        model.set_current_image_index(0)
        assert model.current_image_index == 0
        
        model.set_current_image_index(1)
        assert model.current_image_index == 1

    def test_get_current_image_path(self):
        """Test getting the current image path."""
        model = ProjectModel()
        image_path = "/path/to/image.jpg"
        model.add_image(image_path)
        model.set_current_image_index(0)
        
        current_path = model.get_current_image_path()
        assert current_path == image_path

    def test_get_current_image_path_no_index(self):
        """Test getting current image path when no index is set."""
        model = ProjectModel()
        model.add_image("/path/to/image.jpg")
        current_path = model.get_current_image_path()
        assert current_path is None

    def test_clear_images(self):
        """Test clearing all images from the project."""
        model = ProjectModel()
        model.add_image("/path/to/image1.jpg")
        model.add_image("/path/to/image2.jpg")
        model.clear_images()
        assert len(model.images) == 0
        assert model.current_image_index is None

    def test_has_images(self):
        """Test checking if project has images."""
        model = ProjectModel()
        assert model.has_images() is False
        
        model.add_image("/path/to/image.jpg")
        assert model.has_images() is True
