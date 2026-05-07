"""Unit tests for LibraryView widget."""

import time
from unittest.mock import patch

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from src.services.settings_service import SettingsService
from src.views.library_view import LibraryView


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestLibraryView:
    """Test cases for LibraryView widget."""

    def test_library_view_initialization(self, qapp):
        """Test LibraryView can be initialized."""
        view = LibraryView()
        assert view is not None
        assert view.get_image_count() == 0

    def test_add_single_image(self, qapp, sample_image_path):
        """Test adding a single image."""
        view = LibraryView()
        view.add_image(sample_image_path)
        assert view.get_image_count() == 1

    def test_add_multiple_images(self, qapp, sample_image_path, sample_png_path):
        """Test adding multiple images."""
        view = LibraryView()
        view.add_images([sample_image_path, sample_png_path])
        assert view.get_image_count() == 2

    def test_add_duplicate_image(self, qapp, sample_image_path):
        """Test adding duplicate image doesn't increase count."""
        view = LibraryView()
        view.add_image(sample_image_path)
        view.add_image(sample_image_path)
        assert view.get_image_count() == 1

    def test_clear_images(self, qapp, sample_image_path):
        """Test clearing all images."""
        view = LibraryView()
        view.add_image(sample_image_path)
        view.clear()
        assert view.get_image_count() == 0

    def test_get_selected_path_no_selection(self, qapp):
        """Test get_selected_path with no selection."""
        view = LibraryView()
        assert view.get_selected_path() is None

    def test_image_selected_signal(self, qapp, sample_image_path):
        """Test image_selected signal is emitted."""
        view = LibraryView()
        view.add_image(sample_image_path)
        
        signal_received = []
        view.image_selected.connect(lambda p: signal_received.append(p))
        
        # Simulate click by selecting item
        item = view._list_widget.item(0)
        view._list_widget.setCurrentItem(item)
        view._on_item_clicked(item)
        
        assert len(signal_received) == 1
        assert signal_received[0] == sample_image_path

    def test_images_imported_signal(self, qapp, sample_image_path):
        """Test images_imported signal is emitted."""
        view = LibraryView()
        
        signal_received = []
        view.images_imported.connect(lambda paths: signal_received.append(paths))
        
        # Manually trigger import (without dialog)
        view.add_images([sample_image_path])
        view.images_imported.emit([sample_image_path])
        
        assert len(signal_received) == 1
        assert sample_image_path in signal_received[0]

    def test_import_folder(self, qapp, tmp_path, qtbot):
        """Test importing from folder."""
        # Create test images in folder
        from PIL import Image
        for i in range(3):
            img = Image.new('RGB', (50, 50), color='blue')
            img.save(tmp_path / f"test_{i}.jpg")
        
        view = LibraryView()
        imported = view.import_folder(str(tmp_path))
        
        assert len(imported) == 3
        qtbot.waitUntil(lambda: view.get_image_count() == 3, timeout=5000)
        assert view.get_image_count() == 3

    def test_cancel_thumbnail_batch(self, qapp, tmp_path, qtbot):
        """Cancelling stops the worker and clears the loader for a new batch."""
        from PIL import Image

        from src.services.image_service import ImageService

        paths = []
        for i in range(20):
            p = tmp_path / f"cancel_test_{i}.jpg"
            Image.new("RGB", (8, 8), color=(i, 0, 0)).save(p)
            paths.append(str(p))

        _real_thumb = ImageService.load_preview_thumbnail

        def _slow_thumb(self, file_path, size):
            time.sleep(0.04)
            return _real_thumb(self, file_path, size)

        view = LibraryView()
        with patch.object(ImageService, "load_preview_thumbnail", _slow_thumb):
            view.add_images_async(paths)
            view.cancel_thumbnail_batch()

        qtbot.waitUntil(lambda: view._thumbnail_thread is None, timeout=8000)
        assert view._thumbnail_worker is None
        assert view.get_image_count() < len(paths)


class TestLibraryViewImportSettings:
    """Wiring between ``_import_images`` and ``SettingsService``."""

    @pytest.fixture
    def isolated_settings(self, tmp_path):
        ini_path = tmp_path / "photoedit-test.ini"
        return SettingsService(QSettings(str(ini_path), QSettings.Format.IniFormat))

    def test_import_seeds_dialog_with_last_open_dir(
        self, qapp, sample_image_path, tmp_path, isolated_settings
    ):
        seeded = tmp_path / "previous_session"
        seeded.mkdir()
        isolated_settings.set_last_open_dir(str(seeded))

        view = LibraryView(settings_service=isolated_settings)

        with patch(
            "src.views.library_view.QFileDialog.getOpenFileNames",
            return_value=([sample_image_path], "Image Files"),
        ) as dialog:
            view._import_images()

        args, _ = dialog.call_args
        assert args[2] == str(seeded)

    def test_import_persists_first_chosen_directory(
        self, qapp, sample_image_path, isolated_settings
    ):
        view = LibraryView(settings_service=isolated_settings)

        with patch(
            "src.views.library_view.QFileDialog.getOpenFileNames",
            return_value=([sample_image_path], "Image Files"),
        ):
            view._import_images()

        from pathlib import Path

        assert isolated_settings.get_last_open_dir() == str(
            Path(sample_image_path).parent
        )
