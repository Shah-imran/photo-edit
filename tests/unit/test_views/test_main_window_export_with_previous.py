"""Unit tests for MainWindow._export_with_previous ("Export with Previous")."""

from src.processing.export_render import BackgroundTask
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from src.services.library_catalog_service import LibraryCatalogService
from src.services.library_image_preview_cache_service import (
    LibraryImagePreviewCacheService,
)
from src.services.library_thumbnail_cache_service import LibraryThumbnailCacheService
from src.services.settings_service import SettingsService
from src.views.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def settings_service(tmp_path):
    settings = QSettings(str(tmp_path / "main-window.ini"), QSettings.Format.IniFormat)
    return SettingsService(settings)


@pytest.fixture
def main_window(qapp, qtbot, tmp_path, settings_service):
    """Create a MainWindow instance for testing."""
    catalog = LibraryCatalogService(catalog_path=tmp_path / "catalog.json")
    cache = LibraryThumbnailCacheService(cache_dir=tmp_path / "cache")
    preview_cache = LibraryImagePreviewCacheService(
        cache_dir=tmp_path / "preview-cache"
    )
    window = MainWindow(
        settings_service=settings_service,
        catalog_service=catalog,
        thumbnail_cache_service=cache,
        image_preview_cache_service=preview_cache,
    )
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    yield window
    window.close()


@pytest.fixture
def sample_image():
    return np.full((10, 10, 3), 0.5, dtype=np.float32)


def _make_has_image(main_window, sample_image):
    """Patch image_controller so an "image" is considered loaded.

    The full-resolution render is a real background task over
    ``sample_image``, so these tests exercise the asynchronous flow.
    """
    main_window._image_controller.has_image = MagicMock(return_value=True)
    main_window._image_controller.get_export_image = MagicMock(
        side_effect=AssertionError("export must not render on the UI thread")
    )

    def start_export_render(post=None, apply_crop=True):
        return BackgroundTask(
            lambda: post(sample_image) if post is not None else sample_image
        ).start()

    main_window._image_controller.start_export_render = start_export_render
    main_window._image_controller.image_model.file_path = None


def _export_and_wait(main_window, qtbot):
    """Run Export with Previous and wait for its background job."""
    main_window._export_with_previous()
    qtbot.waitUntil(lambda: not main_window._export_tasks, timeout=5000)


class TestExportWithPreviousNoPreviousOptions:
    """Falls back to the normal Export dialog flow when nothing was exported before."""

    def test_falls_back_to_export_image(self, main_window, sample_image):
        _make_has_image(main_window, sample_image)
        assert main_window._settings_service.get_last_export_options() is None

        with patch.object(main_window, '_export_image') as mock_export_image:
            main_window._export_with_previous()

        mock_export_image.assert_called_once()

    def test_no_image_shows_status_message_and_does_not_fallback(self, main_window):
        main_window._image_controller.has_image = MagicMock(return_value=False)

        with patch.object(main_window, '_export_image') as mock_export_image:
            main_window._export_with_previous()

        mock_export_image.assert_not_called()


class TestExportWithPreviousWithOptions:
    """Exports directly, without showing ExportDialog, when options exist."""

    def _set_options(self, main_window, **overrides):
        options = {
            "format": "JPEG",
            "quality": 80,
            "width": None,
            "height": None,
            "preserve_aspect": True,
        }
        options.update(overrides)
        main_window._settings_service.set_last_export_options(options)
        return options

    def test_exports_without_showing_dialog(self, main_window, sample_image, tmp_path, qtbot):
        _make_has_image(main_window, sample_image)
        self._set_options(main_window)

        with patch('src.views.main_window.ExportDialog') as mock_dialog_cls, \
                patch('src.views.main_window.ExportService') as mock_service_cls, \
                patch('src.views.main_window.confirm_overwrite_if_needed', return_value=True):
            mock_service_instance = MagicMock()
            mock_service_instance.export_image.return_value = True
            mock_service_cls.return_value = mock_service_instance

            _export_and_wait(main_window, qtbot)

        mock_dialog_cls.assert_not_called()
        mock_service_instance.export_image.assert_called_once()

    def test_passes_stored_options_to_export_service(self, main_window, sample_image, tmp_path, qtbot):
        _make_has_image(main_window, sample_image)
        self._set_options(main_window, width=100, height=200, quality=33, preserve_aspect=False)

        with patch('src.views.main_window.ExportService') as mock_service_cls, \
                patch('src.views.main_window.confirm_overwrite_if_needed', return_value=True):
            mock_service_instance = MagicMock()
            mock_service_instance.export_image.return_value = True
            mock_service_cls.return_value = mock_service_instance

            _export_and_wait(main_window, qtbot)

        _, kwargs = mock_service_instance.export_image.call_args
        assert kwargs['format'] == "JPEG"
        assert kwargs['quality'] == 33
        assert kwargs['resize'] == (100, 200)
        assert kwargs['preserve_aspect'] is False

    def test_overwrite_confirmation_declined_aborts_export(self, main_window, sample_image, qtbot):
        _make_has_image(main_window, sample_image)
        self._set_options(main_window)

        with patch('src.views.main_window.ExportService') as mock_service_cls, \
                patch('src.views.main_window.confirm_overwrite_if_needed', return_value=False):
            mock_service_instance = MagicMock()
            mock_service_cls.return_value = mock_service_instance

            _export_and_wait(main_window, qtbot)

        mock_service_instance.export_image.assert_not_called()

    def test_success_updates_status_bar_and_last_export_dir(self, main_window, sample_image, qtbot):
        _make_has_image(main_window, sample_image)
        self._set_options(main_window)

        with patch('src.views.main_window.ExportService') as mock_service_cls, \
                patch('src.views.main_window.confirm_overwrite_if_needed', return_value=True), \
                patch.object(main_window._settings_service, 'set_last_export_dir') as mock_set_dir, \
                patch.object(main_window._status_bar, 'showMessage') as mock_status:
            mock_service_instance = MagicMock()
            mock_service_instance.export_image.return_value = True
            mock_service_cls.return_value = mock_service_instance

            _export_and_wait(main_window, qtbot)

        mock_set_dir.assert_called_once()
        assert any("Exported to" in str(call.args[0]) for call in mock_status.call_args_list)

    def test_failure_shows_critical_message_box(self, main_window, sample_image, qtbot):
        _make_has_image(main_window, sample_image)
        self._set_options(main_window)

        with patch('src.views.main_window.ExportService') as mock_service_cls, \
                patch('src.views.main_window.confirm_overwrite_if_needed', return_value=True), \
                patch('src.views.main_window.QMessageBox') as mock_msgbox:
            mock_service_instance = MagicMock()
            mock_service_instance.export_image.return_value = False
            mock_service_cls.return_value = mock_service_instance

            _export_and_wait(main_window, qtbot)

        mock_msgbox.critical.assert_called_once()
