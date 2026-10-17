"""UI tests for MainWindow's interactive Mask tool (slice 2 of the
Masking roadmap bullet -- see docs/planning/implementation-notes/
2026-10-13-mask-tool-ui.md).
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


def _make_has_image(main_window, sample_image, mask=None):
    main_window._image_controller.has_image = MagicMock(return_value=True)
    main_window._image_controller.get_export_image = MagicMock(return_value=sample_image)
    main_window._image_controller.preview_uncropped = MagicMock(
        return_value=(sample_image.shape[1], sample_image.shape[0])
    )
    main_window._image_controller.refresh_view = MagicMock()
    main_window._image_controller.get_adjustment_state = MagicMock(
        return_value={
            "crop": {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0},
            "mask": mask,
        }
    )
    main_window._image_controller.on_crop_changed = MagicMock()
    main_window._image_controller.on_mask_changed = MagicMock()


@pytest.fixture
def sample_image_file(tmp_path):
    from PIL import Image

    image_path = tmp_path / "test_image.jpg"
    img = Image.new("RGB", (80, 60), color="blue")
    img.save(image_path, "JPEG")
    return str(image_path)


class TestEnterMaskModeNoImage:
    def test_shows_status_message_and_does_not_touch_image_view(self, main_window):
        main_window._image_controller.has_image = MagicMock(return_value=False)
        main_window._image_view.enter_mask_mode = MagicMock()

        main_window._enter_mask_mode()

        assert main_window._status_bar.currentMessage() == "No image to mask"
        main_window._image_view.enter_mask_mode.assert_not_called()


class TestEnterMaskModeWithImage:
    def test_sensible_defaults_when_no_mask_exists_yet(self, main_window, sample_image):
        _make_has_image(main_window, sample_image, mask=None)

        main_window._enter_mask_mode()

        assert main_window._image_view.is_in_mask_mode()
        overlay = main_window._image_view.get_mask_overlay()
        assert overlay.get_mask_type() == "linear"
        assert overlay.get_invert() is False
        assert main_window._mask_toolbar.get_mask_type() == "linear"
        assert main_window._mask_toolbar.get_invert() is False
        assert main_window._mask_toolbar.get_adjustments() == {
            "exposure": 0.0,
            "contrast": 0.0,
            "saturation": 0.0,
            "clarity": 0.0,
        }
        assert main_window._mask_toolbar.isVisible()
        # Lightroom keeps the photo toolbar; the tool opens in the drawer.
        assert main_window._image_toolbar.isVisible()
        assert main_window._tools_panel.tool_drawer.isVisible()

    def test_initializes_overlay_and_toolbar_from_existing_mask(
        self, main_window, sample_image
    ):
        existing_mask = {
            "type": "radial",
            "invert": True,
            "cx": 0.4,
            "cy": 0.4,
            "rx": 0.2,
            "ry": 0.2,
            "feather": 0.3,
            "exposure": 1.0,
            "contrast": -5.0,
            "saturation": 10.0,
            "clarity": -10.0,
        }
        _make_has_image(main_window, sample_image, mask=existing_mask)

        main_window._enter_mask_mode()

        overlay = main_window._image_view.get_mask_overlay()
        assert overlay.get_mask_type() == "radial"
        assert overlay.get_invert() is True
        geometry = overlay.get_geometry()
        assert geometry["cx"] == pytest.approx(0.4)
        assert geometry["rx"] == pytest.approx(0.2)
        assert main_window._mask_toolbar.get_mask_type() == "radial"
        assert main_window._mask_toolbar.get_adjustments() == {
            "exposure": pytest.approx(1.0),
            "contrast": pytest.approx(-5.0),
            "saturation": pytest.approx(10.0),
            "clarity": pytest.approx(-10.0),
        }


class TestApplyMask:
    def test_commits_once_with_assembled_geometry_and_adjustments_and_exits(
        self, main_window, sample_image
    ):
        _make_has_image(main_window, sample_image, mask=None)
        main_window._enter_mask_mode()
        overlay = main_window._image_view.get_mask_overlay()
        overlay.set_linear_geometry(0.2, 0.3, 0.8, 0.3)
        main_window._mask_toolbar._exposure_slider.set_value(1.0)
        main_window._mask_toolbar._contrast_slider.set_value(10.0)

        main_window._apply_mask()

        main_window._image_controller.on_mask_changed.assert_called_once()
        committed = main_window._image_controller.on_mask_changed.call_args[0][0]
        assert committed["type"] == "linear"
        assert committed["invert"] is False
        assert committed["x0"] == pytest.approx(0.2)
        assert committed["y0"] == pytest.approx(0.3)
        assert committed["x1"] == pytest.approx(0.8)
        assert committed["exposure"] == pytest.approx(1.0)
        assert committed["contrast"] == pytest.approx(10.0)
        assert not main_window._image_view.is_in_mask_mode()
        assert not main_window._mask_toolbar.isVisible()
        assert main_window._image_toolbar.isVisible()


class TestRemoveMask:
    def test_commits_none_and_exits(self, main_window, sample_image):
        _make_has_image(main_window, sample_image, mask=None)
        main_window._enter_mask_mode()

        main_window._remove_mask()

        main_window._image_controller.on_mask_changed.assert_called_once_with(None)
        assert not main_window._image_view.is_in_mask_mode()
        assert not main_window._mask_toolbar.isVisible()
        assert main_window._image_toolbar.isVisible()


class TestCropMaskMutualExclusivity:
    def test_entering_mask_mode_exits_an_active_crop_mode(
        self, main_window, sample_image
    ):
        _make_has_image(main_window, sample_image, mask=None)
        main_window._enter_crop_mode()
        assert main_window._image_view.is_in_crop_mode()
        assert not main_window._image_view.is_in_mask_mode()

        main_window._enter_mask_mode()

        assert not main_window._image_view.is_in_crop_mode()
        assert main_window._image_view.is_in_mask_mode()
        # Never both at once.
        assert not (
            main_window._image_view.is_in_crop_mode()
            and main_window._image_view.is_in_mask_mode()
        )

    def test_entering_crop_mode_exits_an_active_mask_mode(
        self, main_window, sample_image
    ):
        _make_has_image(main_window, sample_image, mask=None)
        main_window._enter_mask_mode()
        assert main_window._image_view.is_in_mask_mode()
        assert not main_window._image_view.is_in_crop_mode()

        main_window._enter_crop_mode()

        assert not main_window._image_view.is_in_mask_mode()
        assert main_window._image_view.is_in_crop_mode()
        assert not (
            main_window._image_view.is_in_crop_mode()
            and main_window._image_view.is_in_mask_mode()
        )


class TestCancelMaskNoNetChange:
    def test_cancel_after_in_progress_editing_leaves_committed_mask_unchanged(
        self, main_window, sample_image_file, qtbot
    ):
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)

        committed_mask = {
            "type": "radial",
            "invert": False,
            "cx": 0.5,
            "cy": 0.5,
            "rx": 0.3,
            "ry": 0.3,
            "feather": 0.4,
            "exposure": 0.5,
            "contrast": 5.0,
            "saturation": 0.0,
            "clarity": 0.0,
        }
        with qtbot.waitSignal(
            main_window._image_controller.adjustment_state_restored, timeout=2000
        ):
            main_window._image_controller.on_mask_changed(committed_mask)
        before = main_window._image_controller.get_adjustment_state()["mask"]
        assert before is not None

        main_window._enter_mask_mode()
        # Simulate some in-progress editing: a slider tweak AND a geometry
        # drag's programmatic equivalent -- neither should ever reach the
        # committed state before Apply is clicked.
        main_window._mask_toolbar._exposure_slider.set_value(3.0)
        overlay = main_window._image_view.get_mask_overlay()
        overlay.set_radial_geometry(0.2, 0.2, 0.1, 0.1, 0.1)
        main_window._on_mask_editing_changed()
        qtbot.wait(50)

        main_window._cancel_mask()

        after = main_window._image_controller.get_adjustment_state()["mask"]
        assert after == before
        assert not main_window._image_view.is_in_mask_mode()


class TestLivePreviewWhileEditing:
    def test_slider_tweak_changes_displayed_image_without_committing(
        self, main_window, sample_image_file, qtbot
    ):
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)

        main_window._enter_mask_mode()
        assert main_window._image_view.is_in_mask_mode()

        before_mask_state = main_window._image_controller.get_adjustment_state()["mask"]
        assert before_mask_state is None  # No mask ever committed.
        before_image = main_window._image_view._pixmap.toImage().copy()

        main_window._mask_toolbar._exposure_slider.set_value(4.0)
        qtbot.wait(50)

        after_image = main_window._image_view._pixmap.toImage()
        assert after_image != before_image

        # Still fully uncommitted -- the real adjustment state is untouched.
        after_mask_state = main_window._image_controller.get_adjustment_state()["mask"]
        assert after_mask_state == before_mask_state
