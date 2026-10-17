"""Zoom is measured against the full-resolution image, not the preview."""

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from src.processing.display_frame import DisplayFrame
from src.views.image_view import ImageView


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _frame(width, height, source_size=None):
    linear = np.full((height, width, 3), 0.5, dtype=np.float32)
    return DisplayFrame.from_linear(1, "quality", (), linear, source_size=source_size)


def test_100_percent_shows_full_resolution_size_for_a_preview(qapp):
    view = ImageView()
    view.set_display_frame(_frame(150, 100, source_size=(600, 400)), preserve_view_scale=False)

    view.set_zoom_factor(1.0)

    assert view._image_canvas.width() == 600
    assert view.display_scale() == pytest.approx(4.0 * view.devicePixelRatioF())


def test_swapping_preview_for_full_frame_keeps_zoom_and_on_screen_size(qapp):
    view = ImageView()
    view.set_display_frame(_frame(150, 100, source_size=(600, 400)), preserve_view_scale=False)
    view.set_zoom_factor(0.5)
    canvas_width = view._image_canvas.width()

    view.set_display_frame(_frame(600, 400), preserve_view_scale=True)

    assert view.get_zoom_factor() == pytest.approx(0.5)
    assert view._image_canvas.width() == canvas_width


def test_fit_to_window_uses_full_resolution_size(qapp):
    view = ImageView()
    view.resize(400, 300)
    view.set_display_frame(_frame(150, 100, source_size=(6000, 4000)), preserve_view_scale=False)

    view.fit_to_window()

    # Fit is relative to 6000 px, not the 150 px preview.
    assert view.get_zoom_factor() < 1.0
    assert view._image_canvas.width() <= view._scroll_area.viewport().width()


def test_zooming_keeps_the_viewport_centre_on_the_same_image_point(qapp, qtbot):
    view = ImageView()
    view.resize(400, 300)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    view.set_display_frame(_frame(600, 400, source_size=(6000, 4000)), preserve_view_scale=False)
    view.fit_to_window()

    view.set_zoom_factor(1.0)

    viewport = view._scroll_area.viewport()
    cx = (view._scroll_area.horizontalScrollBar().value() + viewport.width() / 2)
    cy = (view._scroll_area.verticalScrollBar().value() + viewport.height() / 2)
    # Fit -> 100% lands on the middle of the photo, not its top-left corner.
    assert cx == pytest.approx(3000, abs=2)
    assert cy == pytest.approx(2000, abs=2)
