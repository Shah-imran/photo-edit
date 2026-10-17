"""UI tests for MainWindow's interactive Heal tool (slice 2 of the
Healing roadmap bullet -- see docs/planning/implementation-notes/
2026-10-13-healing-tool-ui.md).
"""

from unittest.mock import MagicMock

import numpy as np
import pytest
from PyQt6.QtCore import QPoint, QPointF, QSettings, Qt
from PyQt6.QtGui import QMouseEvent
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


def _make_has_image(main_window, sample_image, heal_spots=None):
    main_window._image_controller.has_image = MagicMock(return_value=True)
    main_window._image_controller.get_export_image = MagicMock(return_value=sample_image)
    main_window._image_controller.get_adjustment_state = MagicMock(
        return_value={
            "crop": {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0},
            "mask": None,
            "heal_spots": heal_spots or [],
        }
    )
    main_window._image_controller.on_crop_changed = MagicMock()
    main_window._image_controller.on_mask_changed = MagicMock()
    main_window._image_controller.on_heal_spots_changed = MagicMock()


@pytest.fixture
def sample_image_file(tmp_path):
    from PIL import Image

    image_path = tmp_path / "test_image.jpg"
    img = Image.new("RGB", (80, 60), color="blue")
    img.save(image_path, "JPEG")
    return str(image_path)


@pytest.fixture
def varied_image_file(tmp_path):
    """A non-uniform image, needed for the heal-tool live-preview test:
    cloning/healing a spot from a FLAT-color source image produces no
    visible pixel change at all, which would make that test meaningless.
    """
    from PIL import Image

    image_path = tmp_path / "varied_test_image.jpg"
    array = np.zeros((60, 80, 3), dtype=np.uint8)
    array[:, :40, :] = [220, 40, 40]
    array[:, 40:, :] = [40, 40, 220]
    img = Image.fromarray(array, mode="RGB")
    img.save(image_path, "JPEG")
    return str(image_path)


def _press(widget, pos, button=Qt.MouseButton.LeftButton):
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(pos),
        QPointF(widget.mapToGlobal(QPoint(int(pos.x()), int(pos.y())))),
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(event)


def _move(widget, pos):
    event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(pos),
        QPointF(widget.mapToGlobal(QPoint(int(pos.x()), int(pos.y())))),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseMoveEvent(event)


def _release(widget, pos, button=Qt.MouseButton.LeftButton):
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(pos),
        QPointF(widget.mapToGlobal(QPoint(int(pos.x()), int(pos.y())))),
        button,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseReleaseEvent(event)


class TestEnterHealingModeNoImage:
    def test_shows_status_message_and_does_not_touch_image_view(self, main_window):
        main_window._image_controller.has_image = MagicMock(return_value=False)
        main_window._image_view.enter_healing_mode = MagicMock()

        main_window._enter_healing_mode()

        assert main_window._status_bar.currentMessage() == "No image to heal"
        main_window._image_view.enter_healing_mode.assert_not_called()


class TestEnterHealingModeWithImage:
    def test_shows_toolbar_and_hides_image_toolbar(self, main_window, sample_image):
        _make_has_image(main_window, sample_image, heal_spots=[])

        main_window._enter_healing_mode()

        assert main_window._image_view.is_in_healing_mode()
        assert main_window._healing_toolbar.isVisible()
        assert not main_window._image_toolbar.isVisible()

    def test_seeds_overlay_with_existing_committed_spots(self, main_window, sample_image):
        existing_spots = [
            {
                "dst_x": 0.3, "dst_y": 0.4, "src_x": 0.46, "src_y": 0.4,
                "radius": 0.08, "feather": 0.3, "opacity": 1.0, "mode": "heal",
            }
        ]
        _make_has_image(main_window, sample_image, heal_spots=existing_spots)

        main_window._enter_healing_mode()

        overlay = main_window._image_view.get_healing_overlay()
        assert overlay.get_spots() == existing_spots


class TestApplyHealing:
    def test_commits_exactly_once_with_overlays_full_spot_list_and_exits(
        self, main_window, sample_image
    ):
        _make_has_image(main_window, sample_image, heal_spots=[])
        main_window._enter_healing_mode()
        overlay = main_window._image_view.get_healing_overlay()

        canvas = main_window._image_view._image_canvas
        overlay.resize(canvas.size())
        press_px = QPointF(0.3 * overlay.width(), 0.3 * overlay.height())
        _press(overlay, press_px)
        drag_px = QPointF(0.35 * overlay.width(), 0.3 * overlay.height())
        _move(overlay, drag_px)
        _release(overlay, drag_px)

        expected_spots = overlay.get_spots()
        assert len(expected_spots) == 1

        main_window._apply_healing()

        main_window._image_controller.on_heal_spots_changed.assert_called_once_with(
            expected_spots
        )
        assert not main_window._image_view.is_in_healing_mode()
        assert not main_window._healing_toolbar.isVisible()
        assert main_window._image_toolbar.isVisible()


class TestCancelHealingNoNetChange:
    def test_cancel_after_in_progress_placement_leaves_committed_state_unchanged(
        self, main_window, sample_image_file, qtbot
    ):
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)

        committed_spots = [
            {
                "dst_x": 0.5, "dst_y": 0.5, "src_x": 0.66, "src_y": 0.5,
                "radius": 0.08, "feather": 0.3, "opacity": 1.0, "mode": "clone",
            }
        ]
        with qtbot.waitSignal(
            main_window._image_controller.adjustment_state_restored, timeout=2000
        ):
            main_window._image_controller.on_heal_spots_changed(committed_spots)
        before = main_window._image_controller.get_adjustment_state()["heal_spots"]
        assert before

        main_window._enter_healing_mode()
        overlay = main_window._image_view.get_healing_overlay()
        canvas = main_window._image_view._image_canvas
        overlay.resize(canvas.size())

        # Simulate an in-progress placement -- never reaches the committed
        # state before Apply.
        press_px = QPointF(0.2 * overlay.width(), 0.2 * overlay.height())
        _press(overlay, press_px)
        drag_px = QPointF(0.25 * overlay.width(), 0.2 * overlay.height())
        _move(overlay, drag_px)
        _release(overlay, drag_px)
        qtbot.wait(50)

        main_window._cancel_healing()

        after = main_window._image_controller.get_adjustment_state()["heal_spots"]
        assert after == before
        assert not main_window._image_view.is_in_healing_mode()


class TestLivePreviewWhileEditing:
    def test_placing_a_spot_changes_displayed_image_without_committing(
        self, main_window, varied_image_file, qtbot
    ):
        main_window._image_controller.load_image(varied_image_file)
        qtbot.wait(100)

        main_window._enter_healing_mode()
        assert main_window._image_view.is_in_healing_mode()

        before_state = main_window._image_controller.get_adjustment_state()["heal_spots"]
        assert before_state == []
        before_image = main_window._image_view._pixmap.toImage().copy()

        overlay = main_window._image_view.get_healing_overlay()
        canvas = main_window._image_view._image_canvas
        overlay.resize(canvas.size())
        # A clone spot straddling the red/blue boundary: its auto-computed
        # source (offset right by 2*radius) samples visibly different
        # color content from its destination, so Clone's blend is
        # guaranteed to change pixels, unlike a flat-color test image.
        main_window._healing_toolbar._mode_combo.setCurrentText("Clone")
        press_px = QPointF(0.45 * overlay.width(), 0.5 * overlay.height())
        _press(overlay, press_px)
        drag_px = QPointF(0.55 * overlay.width(), 0.5 * overlay.height())
        _move(overlay, drag_px)
        _release(overlay, drag_px)
        qtbot.wait(50)

        after_image = main_window._image_view._pixmap.toImage()
        assert after_image != before_image

        after_state = main_window._image_controller.get_adjustment_state()["heal_spots"]
        assert after_state == before_state


class TestThreeWayMutualExclusivity:
    def test_entering_heal_mode_exits_an_active_crop_mode(
        self, main_window, sample_image
    ):
        _make_has_image(main_window, sample_image)
        main_window._enter_crop_mode()
        assert main_window._image_view.is_in_crop_mode()

        main_window._enter_healing_mode()

        assert not main_window._image_view.is_in_crop_mode()
        assert main_window._image_view.is_in_healing_mode()

    def test_entering_heal_mode_exits_an_active_mask_mode(
        self, main_window, sample_image
    ):
        _make_has_image(main_window, sample_image)
        main_window._enter_mask_mode()
        assert main_window._image_view.is_in_mask_mode()

        main_window._enter_healing_mode()

        assert not main_window._image_view.is_in_mask_mode()
        assert main_window._image_view.is_in_healing_mode()

    def test_entering_crop_mode_exits_an_active_heal_mode(
        self, main_window, sample_image
    ):
        _make_has_image(main_window, sample_image)
        main_window._enter_healing_mode()
        assert main_window._image_view.is_in_healing_mode()

        main_window._enter_crop_mode()

        assert not main_window._image_view.is_in_healing_mode()
        assert main_window._image_view.is_in_crop_mode()

    def test_entering_mask_mode_exits_an_active_heal_mode(
        self, main_window, sample_image
    ):
        _make_has_image(main_window, sample_image)
        main_window._enter_healing_mode()
        assert main_window._image_view.is_in_healing_mode()

        main_window._enter_mask_mode()

        assert not main_window._image_view.is_in_healing_mode()
        assert main_window._image_view.is_in_mask_mode()

    def test_never_more_than_one_mode_active_at_once(self, main_window, sample_image):
        _make_has_image(main_window, sample_image)
        main_window._enter_crop_mode()
        main_window._enter_mask_mode()
        main_window._enter_healing_mode()

        modes_active = [
            main_window._image_view.is_in_crop_mode(),
            main_window._image_view.is_in_mask_mode(),
            main_window._image_view.is_in_healing_mode(),
        ]
        assert sum(modes_active) == 1
        assert modes_active[2] is True
