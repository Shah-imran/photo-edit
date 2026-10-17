"""UI tests for MainWindow's interactive Crop tool (slice 2 of the Crop
tool roadmap bullet -- see docs/planning/implementation-notes/
2026-10-13-crop-tool-ui.md).
"""

from unittest.mock import MagicMock

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
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def main_window(qapp, qtbot, tmp_path):
    settings = SettingsService(
        QSettings(str(tmp_path / "main-window.ini"), QSettings.Format.IniFormat)
    )
    catalog = LibraryCatalogService(catalog_path=tmp_path / "catalog.json")
    cache = LibraryThumbnailCacheService(cache_dir=tmp_path / "cache")
    preview_cache = LibraryImagePreviewCacheService(
        cache_dir=tmp_path / "preview-cache"
    )
    window = MainWindow(
        settings_service=settings,
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
    return np.full((20, 10, 3), 0.5, dtype=np.float32)


def _make_has_image(main_window, sample_image):
    main_window._image_controller.has_image = MagicMock(return_value=True)
    main_window._image_controller.get_export_image = MagicMock(return_value=sample_image)
    main_window._image_controller.preview_uncropped = MagicMock(
        return_value=(sample_image.shape[1], sample_image.shape[0])
    )
    main_window._image_controller.refresh_view = MagicMock()
    main_window._image_controller.get_adjustment_state = MagicMock(
        return_value={"crop": {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}}
    )
    main_window._image_controller.on_crop_changed = MagicMock()


class TestEnterCropModeNoImage:
    def test_shows_status_message_and_does_not_touch_image_view(self, main_window):
        main_window._image_controller.has_image = MagicMock(return_value=False)
        main_window._image_view.enter_crop_mode = MagicMock()

        main_window._enter_crop_mode()

        assert main_window._status_bar.currentMessage() == "No image to crop"
        main_window._image_view.enter_crop_mode.assert_not_called()


class TestEnterCropModeWithImage:
    def test_displays_uncropped_export_and_enters_crop_mode(
        self, main_window, sample_image
    ):
        _make_has_image(main_window, sample_image)

        main_window._enter_crop_mode()

        # The uncropped frame is rendered by the controller (off the UI
        # thread when threaded), not by a synchronous get_export_image call.
        main_window._image_controller.preview_uncropped.assert_called_once_with()
        main_window._image_controller.get_export_image.assert_not_called()
        assert main_window._image_view.is_in_crop_mode()
        overlay = main_window._image_view.get_crop_overlay()
        assert overlay is not None
        assert overlay.get_rect() == {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
        assert main_window._crop_toolbar.isVisible()
        # Lightroom keeps the photo toolbar; the tool opens in the drawer.
        assert main_window._image_toolbar.isVisible()
        assert main_window._tools_panel.tool_drawer.isVisible()

    def test_uses_current_crop_state_as_initial_rect(self, main_window, sample_image):
        _make_has_image(main_window, sample_image)
        main_window._image_controller.get_adjustment_state = MagicMock(
            return_value={"crop": {"x0": 0.1, "y0": 0.2, "x1": 0.8, "y1": 0.9}}
        )

        main_window._enter_crop_mode()

        overlay = main_window._image_view.get_crop_overlay()
        assert overlay.get_rect() == {"x0": 0.1, "y0": 0.2, "x1": 0.8, "y1": 0.9}


class TestApplyCrop:
    def test_calls_on_crop_changed_with_overlay_rect_and_exits_crop_mode(
        self, main_window, sample_image
    ):
        _make_has_image(main_window, sample_image)
        main_window._enter_crop_mode()
        overlay = main_window._image_view.get_crop_overlay()
        overlay.set_rect(0.1, 0.1, 0.9, 0.9)

        main_window._apply_crop()

        main_window._image_controller.on_crop_changed.assert_called_once_with(
            {"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.9}
        )
        assert not main_window._image_view.is_in_crop_mode()
        assert not main_window._crop_toolbar.isVisible()
        assert main_window._image_toolbar.isVisible()


class TestCancelCrop:
    def test_exits_crop_mode_without_calling_on_crop_changed(
        self, main_window, sample_image
    ):
        _make_has_image(main_window, sample_image)
        main_window._enter_crop_mode()
        overlay = main_window._image_view.get_crop_overlay()
        overlay.set_rect(0.1, 0.1, 0.9, 0.9)

        main_window._cancel_crop()

        main_window._image_controller.on_crop_changed.assert_not_called()
        assert not main_window._image_view.is_in_crop_mode()
        assert not main_window._crop_toolbar.isVisible()
        assert main_window._image_toolbar.isVisible()


class TestDimensionsLabelUpdatesAfterCrop:
    def test_status_bar_reflects_new_cropped_dimensions(
        self, main_window, sample_image_file, qtbot
    ):
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        width0, height0 = main_window._image_controller.get_output_size()
        assert main_window._dimensions_label.text() == f"{width0} × {height0}"

        with qtbot.waitSignal(
            main_window._image_controller.adjustment_state_restored, timeout=2000
        ):
            main_window._image_controller.on_crop_changed(
                {"x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5}
            )

        # The label reports the full-resolution output size, which no
        # longer depends on which preview frame happens to be on screen.
        new_width, new_height = main_window._image_controller.get_output_size()
        assert new_width < width0
        assert new_height < height0
        assert main_window._dimensions_label.text() == f"{new_width} × {new_height}"


@pytest.fixture
def sample_image_file(tmp_path):
    from PIL import Image

    image_path = tmp_path / "test_image.jpg"
    img = Image.new("RGB", (800, 600), color="blue")
    img.save(image_path, "JPEG")
    return str(image_path)
