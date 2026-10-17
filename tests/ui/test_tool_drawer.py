"""Lightroom-style tool strip + drawer (docs/UI_UX.md placement spec).

Tool options open in a drawer under the tool strip in the right panel;
clicking the active tool again (or its shortcut) is Done, picking another
tool commits the current one, Esc cancels. Driven through the real
widgets and keyboard on a real (small) photo.
"""

import numpy as np
import pytest
from PIL import Image
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtTest import QTest
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
def window(qapp, qtbot, tmp_path):
    photo = tmp_path / "photo.jpg"
    gradient = np.linspace(20, 230, 300, dtype=np.uint8)
    Image.fromarray(np.dstack([np.tile(gradient, (200, 1))] * 3)).save(photo)
    window = MainWindow(
        settings_service=SettingsService(
            QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
        ),
        catalog_service=LibraryCatalogService(catalog_path=tmp_path / "c.json"),
        thumbnail_cache_service=LibraryThumbnailCacheService(cache_dir=tmp_path / "t"),
        image_preview_cache_service=LibraryImagePreviewCacheService(cache_dir=tmp_path / "p"),
    )
    qtbot.addWidget(window)
    window.resize(1300, 850)
    window.show()
    qtbot.waitExposed(window)
    window._image_controller.load_image(str(photo))
    qtbot.wait(100)
    window.activateWindow()
    yield window
    window.close()


def _strip_button(window, tool):
    strip = window._tools_panel._editing_tool_strip
    return {"crop": strip._crop_button, "heal": strip._heal_button, "mask": strip._mask_button}[tool]


def _assert_active(window, tool):
    drawer = window._tools_panel.tool_drawer
    assert drawer.active == tool
    assert drawer.isVisible() == (tool is not None)
    for name in ("crop", "heal", "mask"):
        assert _strip_button(window, name).isChecked() == (name == tool)
        assert drawer.page(name).isVisible() == (name == tool)


@pytest.mark.parametrize("tool", ["crop", "heal", "mask"])
def test_strip_button_opens_its_drawer_and_clicking_again_closes_it(window, qtbot, tool):
    _assert_active(window, None)

    _strip_button(window, tool).click()
    _assert_active(window, tool)
    # The tool's options are in the right panel; the photo toolbar stays.
    assert window._image_toolbar.isVisible()

    _strip_button(window, tool).click()
    _assert_active(window, None)


def test_photo_keeps_its_height_while_a_tool_is_open(window, qtbot):
    height_before = window._image_view.height()
    _strip_button(window, "mask").click()
    qtbot.wait(50)
    assert window._image_view.height() == height_before


def test_clicking_crop_again_is_done_and_commits_the_crop(window, qtbot):
    _strip_button(window, "crop").click()
    window._image_view.get_crop_overlay().set_rect(0.1, 0.1, 0.6, 0.6)

    _strip_button(window, "crop").click()

    assert window._image_controller.get_adjustment_state()["crop"] == {
        "x0": 0.1, "y0": 0.1, "x1": 0.6, "y1": 0.6,
    }


def test_switching_tools_commits_the_current_one(window, qtbot):
    _strip_button(window, "crop").click()
    window._image_view.get_crop_overlay().set_rect(0.2, 0.2, 0.8, 0.8)

    _strip_button(window, "mask").click()

    _assert_active(window, "mask")
    assert window._image_controller.get_adjustment_state()["crop"]["x0"] == 0.2


def test_escape_cancels_without_committing(window, qtbot):
    _strip_button(window, "crop").click()
    window._image_view.get_crop_overlay().set_rect(0.3, 0.3, 0.7, 0.7)

    QTest.keyClick(window, Qt.Key.Key_Escape)

    _assert_active(window, None)
    crop = window._image_controller.get_adjustment_state()["crop"]
    assert crop in (None, {}, {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0})


@pytest.mark.parametrize(
    "key,modifier,tool",
    [
        (Qt.Key.Key_R, Qt.KeyboardModifier.NoModifier, "crop"),
        (Qt.Key.Key_Q, Qt.KeyboardModifier.NoModifier, "heal"),
        (Qt.Key.Key_W, Qt.KeyboardModifier.ShiftModifier, "mask"),
    ],
)
def test_lightroom_shortcuts_toggle_tools(window, qtbot, key, modifier, tool):
    QTest.keyClick(window, key, modifier)
    _assert_active(window, tool)

    QTest.keyClick(window, key, modifier)
    _assert_active(window, None)


def test_typing_in_search_box_does_not_trigger_tool_shortcuts(window, qtbot):
    from PyQt6.QtWidgets import QLineEdit

    box = window._filmstrip_view.findChild(QLineEdit)
    assert box is not None
    box.setFocus()
    QTest.keyClicks(box, "rq")

    assert box.text() == "rq"
    _assert_active(window, None)


def test_tools_with_edits_show_a_dot(window, qtbot):
    strip_button = lambda tool: _strip_button(window, tool)  # noqa: E731
    assert not any(strip_button(t).is_edited() for t in ("crop", "heal", "mask"))

    strip_button("crop").click()
    window._image_view.get_crop_overlay().set_rect(0.1, 0.1, 0.9, 0.9)
    strip_button("crop").click()  # Done
    assert strip_button("crop").is_edited()
    assert not strip_button("mask").is_edited()

    window._image_controller.undo()
    qtbot.wait(50)
    assert not strip_button("crop").is_edited()


def test_ctrl_shift_r_resets_all_settings(window, qtbot):
    controller = window._image_controller
    controller.on_adjustments_changed({"exposure": 1.0})
    controller.on_slider_released()

    QTest.keyClick(window, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)

    assert controller.get_adjustment_state()["exposure"] == 0.0


def _rect_in_window(window, widget):
    """Widget geometry in main-window coordinates."""
    from PyQt6.QtCore import QPoint, QRect

    top_left = widget.mapTo(window, QPoint(0, 0))
    return QRect(top_left, widget.size())


@pytest.mark.parametrize("tool", ["crop", "heal", "mask"])
def test_placement_matches_lightroom_spec(window, qtbot, tool):
    """docs/UI_UX.md placement spec, as geometry: histogram, then the tool
    strip, then the open tool's drawer, stacked at the top of the right
    panel; the photo and its zoom toolbar keep the centre; no tool options
    under the photo."""
    _strip_button(window, tool).click()
    qtbot.wait(50)
    panel = window._tools_panel
    strip = _rect_in_window(window, panel._editing_tool_strip)
    drawer = _rect_in_window(window, panel.tool_drawer)
    histogram = _rect_in_window(window, panel._histogram_widget)
    photo = _rect_in_window(window, window._image_view)
    zoom_bar = _rect_in_window(window, window._image_toolbar)

    # Right panel: histogram above the strip, drawer directly under it.
    assert histogram.bottom() < strip.top()
    assert abs(drawer.top() - (strip.bottom() + 1)) <= 2
    assert strip.left() > photo.right() and drawer.left() > photo.right()
    # Centre: the zoom toolbar sits right under the photo.
    assert abs(zoom_bar.top() - (photo.bottom() + 1)) <= 2
    # Every tool page lives in the drawer, never in the central area.
    central = window.centralWidget()
    for page in ("crop", "heal", "mask"):
        assert not central.isAncestorOf(panel.tool_drawer.page(page))
