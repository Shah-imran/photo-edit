"""Overlays must draw over the photo, never erase it.

These render the real ImageView (photo + overlay) to an image and read
pixels back. The crop overlay once "punched a hole" with
CompositionMode_Clear, which wiped the photo to black inside the crop box;
its geometry tests all passed because none of them looked at pixels.
"""

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


@pytest.fixture
def white_view(qapp, qtbot):
    view = ImageView()
    view.resize(420, 320)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    white = np.ones((200, 300, 3), dtype=np.float32)
    view.set_display_frame(DisplayFrame.from_linear(1, "quality", (), white), preserve_view_scale=False)
    view.set_zoom_factor(1.0)
    qtbot.wait(20)
    return view


def _canvas_pixel(view, fx, fy):
    """RGB of the canvas at fractional position (fx, fy)."""
    canvas = view._image_canvas
    image = canvas.grab().toImage()
    color = image.pixelColor(int(image.width() * fx), int(image.height() * fy))
    return color.red(), color.green(), color.blue()


def test_crop_overlay_keeps_photo_visible_inside_and_dims_outside(white_view, qtbot):
    white_view.enter_crop_mode({"x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.75})
    qtbot.wait(20)

    inside = _canvas_pixel(white_view, 0.4, 0.4)
    outside = _canvas_pixel(white_view, 0.1, 0.1)

    assert min(inside) > 240, f"photo hidden inside crop box: {inside}"
    assert 60 < max(outside) < 200, f"outside not dimmed: {outside}"


def test_mask_overlay_keeps_photo_visible(white_view, qtbot):
    white_view.enter_mask_mode("radial", {"cx": 0.5, "cy": 0.5, "rx": 0.2, "ry": 0.2})
    qtbot.wait(20)

    away_from_handles = _canvas_pixel(white_view, 0.1, 0.9)

    assert min(away_from_handles) > 200, f"mask overlay hides photo: {away_from_handles}"


def test_healing_overlay_keeps_photo_visible(white_view, qtbot):
    white_view.enter_healing_mode([])
    qtbot.wait(20)

    assert min(_canvas_pixel(white_view, 0.5, 0.5)) > 240
