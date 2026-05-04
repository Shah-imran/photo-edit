"""Unit tests for ImageController."""

import pytest
from PIL import Image
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from unittest.mock import Mock, patch
from src.controllers.image_controller import ImageController
from src.views.image_view import ImageView
from src.models.image_model import ImageModel
from src.services.image_service import ImageService
from src.services.history_service import HistoryService
from src.services.settings_service import SettingsService


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
        controller = ImageController(view, use_threading=False)
        assert controller is not None
        assert controller.has_image() is False
        controller.cleanup()

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
            history_service=history_service,
            use_threading=False
        )
        
        assert controller.image_model is model
        assert controller.history_service is history_service
        controller.cleanup()

    def test_load_image_success(self, qapp, sample_image_path):
        """Test loading an image successfully."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        
        result = controller.load_image(sample_image_path)
        
        assert result is True
        assert controller.has_image() is True
        controller.cleanup()

    def test_load_image_file_not_found(self, qapp):
        """Test loading a non-existent file."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        
        # Mock QMessageBox to avoid dialog
        with patch('src.controllers.image_controller.QMessageBox'):
            result = controller.load_image("nonexistent.jpg")
        
        assert result is False
        assert controller.has_image() is False
        controller.cleanup()

    def test_reset_to_original(self, qapp, sample_image_path):
        """Test resetting to original image."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller.load_image(sample_image_path)
        
        controller.reset_to_original()
        
        assert controller.has_image() is True
        controller.cleanup()

    def test_zoom_in(self, qapp, sample_image_path):
        """Test zoom in."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller.load_image(sample_image_path)
        
        initial_zoom = controller.get_zoom_factor()
        controller.zoom_in()
        
        assert controller.get_zoom_factor() > initial_zoom
        controller.cleanup()

    def test_zoom_out(self, qapp, sample_image_path):
        """Test zoom out."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller.load_image(sample_image_path)
        view.set_zoom_factor(2.0)
        
        controller.zoom_out()
        
        assert controller.get_zoom_factor() < 2.0
        controller.cleanup()

    def test_fit_to_window(self, qapp, sample_image_path):
        """Test fit to window."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller.load_image(sample_image_path)
        
        # Should not raise
        controller.fit_to_window()
        controller.cleanup()

    def test_view_100_percent(self, qapp, sample_image_path):
        """Test 100% view."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        controller.load_image(sample_image_path)
        view.set_zoom_factor(2.0)
        
        controller.view_100_percent()
        
        assert controller.get_zoom_factor() == 1.0
        controller.cleanup()

    def test_can_undo_initially_false(self, qapp):
        """Test can_undo is False initially."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        
        assert controller.can_undo() is False
        controller.cleanup()

    def test_can_redo_initially_false(self, qapp):
        """Test can_redo is False initially."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)
        
        assert controller.can_redo() is False
        controller.cleanup()


class TestImageControllerOpenImageSettings:
    """Wiring between ``open_image`` and ``SettingsService``."""

    @pytest.fixture
    def isolated_settings(self, tmp_path):
        ini_path = tmp_path / "photoedit-test.ini"
        return SettingsService(QSettings(str(ini_path), QSettings.Format.IniFormat))

    def test_open_image_seeds_dialog_with_last_open_dir(
        self, qapp, sample_image_path, tmp_path, isolated_settings
    ):
        """The dialog must start in the previously-stored open directory."""
        seeded = tmp_path / "previously_used"
        seeded.mkdir()
        isolated_settings.set_last_open_dir(str(seeded))

        view = ImageView()
        controller = ImageController(
            view, settings_service=isolated_settings, use_threading=False
        )

        with patch(
            "src.controllers.image_controller.QFileDialog.getOpenFileName",
            return_value=(sample_image_path, "Image Files"),
        ) as dialog:
            controller.open_image()

        args, _ = dialog.call_args
        assert args[2] == str(seeded)
        controller.cleanup()

    def test_open_image_persists_chosen_directory(
        self, qapp, sample_image_path, isolated_settings
    ):
        """After picking a file, its parent directory must be stored."""
        view = ImageView()
        controller = ImageController(
            view, settings_service=isolated_settings, use_threading=False
        )

        with patch(
            "src.controllers.image_controller.QFileDialog.getOpenFileName",
            return_value=(sample_image_path, "Image Files"),
        ):
            controller.open_image()

        from pathlib import Path

        assert isolated_settings.get_last_open_dir() == str(
            Path(sample_image_path).parent
        )
        controller.cleanup()

    def test_open_image_no_settings_uses_empty_default(self, qapp, sample_image_path):
        """Backwards-compat: no SettingsService keeps the legacy empty default."""
        view = ImageView()
        controller = ImageController(view, use_threading=False)

        with patch(
            "src.controllers.image_controller.QFileDialog.getOpenFileName",
            return_value=(sample_image_path, "Image Files"),
        ) as dialog:
            controller.open_image()

        args, _ = dialog.call_args
        assert args[2] == ""
        controller.cleanup()
