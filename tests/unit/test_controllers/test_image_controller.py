"""Unit tests for ImageController."""

import pytest
from PIL import Image
from PyQt6.QtWidgets import QApplication
from unittest.mock import Mock, patch
from src.controllers.image_controller import ImageController
from src.views.image_view import ImageView
from src.models.image_model import ImageModel
from src.services.image_service import ImageService
from src.services.history_service import HistoryService


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestImageController:
    """Test cases for ImageController class."""

    def test_controller_initialization(self, qapp):
        """Test ImageController can be initialized."""
        view = ImageView()
        controller = ImageController(view)
        assert controller is not None
        assert controller.has_image() is False

    def test_controller_with_dependencies(self, qapp):
        """Test ImageController with injected dependencies."""
        view = ImageView()
        model = ImageModel()
        image_service = ImageService()
        history_service = HistoryService()
        
        controller = ImageController(
            view,
            image_model=model,
            image_service=image_service,
            history_service=history_service
        )
        
        assert controller.image_model is model
        assert controller.history_service is history_service

    def test_load_image_success(self, qapp, sample_image_path):
        """Test loading an image successfully."""
        view = ImageView()
        controller = ImageController(view)
        
        result = controller.load_image(sample_image_path)
        
        assert result is True
        assert controller.has_image() is True

    def test_load_image_file_not_found(self, qapp):
        """Test loading a non-existent file."""
        view = ImageView()
        controller = ImageController(view)
        
        # Mock QMessageBox to avoid dialog
        with patch('src.controllers.image_controller.QMessageBox'):
            result = controller.load_image("nonexistent.jpg")
        
        assert result is False
        assert controller.has_image() is False

    def test_reset_to_original(self, qapp, sample_image_path):
        """Test resetting to original image."""
        view = ImageView()
        controller = ImageController(view)
        controller.load_image(sample_image_path)
        
        controller.reset_to_original()
        
        assert controller.has_image() is True

    def test_zoom_in(self, qapp, sample_image_path):
        """Test zoom in."""
        view = ImageView()
        controller = ImageController(view)
        controller.load_image(sample_image_path)
        
        initial_zoom = controller.get_zoom_factor()
        controller.zoom_in()
        
        assert controller.get_zoom_factor() > initial_zoom

    def test_zoom_out(self, qapp, sample_image_path):
        """Test zoom out."""
        view = ImageView()
        controller = ImageController(view)
        controller.load_image(sample_image_path)
        view.set_zoom_factor(2.0)
        
        controller.zoom_out()
        
        assert controller.get_zoom_factor() < 2.0

    def test_fit_to_window(self, qapp, sample_image_path):
        """Test fit to window."""
        view = ImageView()
        controller = ImageController(view)
        controller.load_image(sample_image_path)
        
        # Should not raise
        controller.fit_to_window()

    def test_view_100_percent(self, qapp, sample_image_path):
        """Test 100% view."""
        view = ImageView()
        controller = ImageController(view)
        controller.load_image(sample_image_path)
        view.set_zoom_factor(2.0)
        
        controller.view_100_percent()
        
        assert controller.get_zoom_factor() == 1.0

    def test_can_undo_initially_false(self, qapp):
        """Test can_undo is False initially."""
        view = ImageView()
        controller = ImageController(view)
        
        assert controller.can_undo() is False

    def test_can_redo_initially_false(self, qapp):
        """Test can_redo is False initially."""
        view = ImageView()
        controller = ImageController(view)
        
        assert controller.can_redo() is False
