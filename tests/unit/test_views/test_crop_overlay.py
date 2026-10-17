"""Unit tests for the CropOverlay widget."""

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from src.views.widgets.crop_overlay import CropOverlay


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


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


class TestSetGetRect:
    def test_round_trip(self, qapp):
        overlay = CropOverlay()
        overlay.resize(400, 300)
        overlay.set_rect(0.1, 0.2, 0.8, 0.9)
        assert overlay.get_rect() == {"x0": 0.1, "y0": 0.2, "x1": 0.8, "y1": 0.9}

    def test_set_rect_does_not_emit(self, qapp):
        overlay = CropOverlay()
        overlay.resize(400, 300)
        received = []
        overlay.rect_changed.connect(received.append)
        overlay.set_rect(0.1, 0.2, 0.8, 0.9)
        assert received == []

    def test_set_rect_clamps_and_swaps(self, qapp):
        overlay = CropOverlay()
        overlay.resize(400, 300)
        overlay.set_rect(0.9, 0.9, 0.1, 0.1)
        rect = overlay.get_rect()
        assert rect["x0"] < rect["x1"]
        assert rect["y0"] < rect["y1"]
        assert 0.0 <= rect["x0"] <= 1.0
        assert 0.0 <= rect["x1"] <= 1.0


class TestHitTest:
    def _overlay(self):
        overlay = CropOverlay()
        overlay.resize(400, 300)
        overlay.set_rect(0.25, 0.25, 0.75, 0.75)  # px: (100,75)-(300,225)
        return overlay

    @pytest.mark.parametrize(
        "handle,point",
        [
            ("top_left", (100, 75)),
            ("top_right", (300, 75)),
            ("bottom_left", (100, 225)),
            ("bottom_right", (300, 225)),
            ("top", (200, 75)),
            ("bottom", (200, 225)),
            ("left", (100, 150)),
            ("right", (300, 150)),
        ],
    )
    def test_each_handle_detected(self, qapp, handle, point):
        overlay = self._overlay()
        assert overlay._hit_test(QPointF(*point)) == handle

    def test_inside_click_is_move(self, qapp):
        overlay = self._overlay()
        assert overlay._hit_test(QPointF(200, 150)) == "move"

    def test_outside_click_is_none(self, qapp):
        overlay = self._overlay()
        assert overlay._hit_test(QPointF(10, 10)) is None


class TestDrag:
    def test_corner_drag_resizes(self, qapp):
        overlay = CropOverlay()
        overlay.resize(400, 300)
        overlay.set_rect(0.0, 0.0, 0.5, 0.5)  # px: (0,0)-(200,150)
        received = []
        overlay.rect_changed.connect(received.append)

        _press(overlay, QPointF(200, 150))  # bottom_right handle
        _move(overlay, QPointF(300, 225))
        _release(overlay, QPointF(300, 225))

        rect = overlay.get_rect()
        assert rect["x1"] == pytest.approx(300 / 400, abs=0.01)
        assert rect["y1"] == pytest.approx(225 / 300, abs=0.01)
        assert len(received) >= 1

    def test_move_drag_translates_without_resizing(self, qapp):
        overlay = CropOverlay()
        overlay.resize(400, 300)
        overlay.set_rect(0.2, 0.2, 0.5, 0.5)  # px: (80,60)-(200,150)
        width = 0.5 - 0.2
        height = 0.5 - 0.2

        _press(overlay, QPointF(140, 105))  # inside, not on a handle
        _move(overlay, QPointF(180, 145))  # +40,+40 px -> +0.1,+0.1333 frac
        _release(overlay, QPointF(180, 145))

        rect = overlay.get_rect()
        assert rect["x1"] - rect["x0"] == pytest.approx(width, abs=0.01)
        assert rect["y1"] - rect["y0"] == pytest.approx(height, abs=0.01)
        assert rect["x0"] == pytest.approx(0.3, abs=0.02)
        assert rect["y0"] == pytest.approx(0.333, abs=0.02)

    def test_aspect_lock_forces_square(self, qapp):
        overlay = CropOverlay()
        overlay.resize(400, 400)
        overlay.set_rect(0.0, 0.0, 0.5, 0.5)  # px: (0,0)-(200,200), square
        overlay.set_locked_aspect(1.0)

        _press(overlay, QPointF(200, 200))  # bottom_right
        _move(overlay, QPointF(300, 220))  # would be non-square without lock
        _release(overlay, QPointF(300, 220))

        rect = overlay.get_rect()
        width_px = (rect["x1"] - rect["x0"]) * 400
        height_px = (rect["y1"] - rect["y0"]) * 400
        assert width_px == pytest.approx(height_px, abs=1.0)

    def test_drag_outside_bounds_stays_clamped_and_non_degenerate(self, qapp):
        overlay = CropOverlay()
        overlay.resize(400, 300)
        overlay.set_rect(0.5, 0.5, 0.9, 0.9)

        _press(overlay, QPointF(0.9 * 400, 0.9 * 300))  # bottom_right handle
        _move(overlay, QPointF(1000, 1000))  # far outside bounds
        _release(overlay, QPointF(1000, 1000))

        rect = overlay.get_rect()
        assert 0.0 <= rect["x1"] <= 1.0
        assert 0.0 <= rect["y1"] <= 1.0
        assert rect["x1"] > rect["x0"]
        assert rect["y1"] > rect["y0"]

    def test_outside_click_not_on_handle_is_a_no_op(self, qapp):
        overlay = CropOverlay()
        overlay.resize(400, 300)
        overlay.set_rect(0.25, 0.25, 0.75, 0.75)
        before = overlay.get_rect()
        received = []
        overlay.rect_changed.connect(received.append)

        _press(overlay, QPointF(5, 5))  # far outside rect, no handle nearby
        _move(overlay, QPointF(50, 50))
        _release(overlay, QPointF(50, 50))

        assert overlay.get_rect() == before
        assert received == []
