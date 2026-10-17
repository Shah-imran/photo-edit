"""Unit tests for the MaskOverlay widget."""

import math

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from src.processors.mask_processor import MaskProcessor
from src.views.widgets.mask_overlay import MaskOverlay


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


class TestLinearGeometryRoundTrip:
    def test_set_get_round_trip(self, qapp):
        overlay = MaskOverlay()
        overlay.resize(400, 300)
        overlay.set_mask_type("linear")
        overlay.set_linear_geometry(0.1, 0.2, 0.8, 0.9)
        geometry = overlay.get_geometry()
        assert geometry["type"] == "linear"
        assert geometry["invert"] is False
        assert geometry["x0"] == pytest.approx(0.1)
        assert geometry["y0"] == pytest.approx(0.2)
        assert geometry["x1"] == pytest.approx(0.8)
        assert geometry["y1"] == pytest.approx(0.9)

    def test_set_linear_geometry_does_not_emit(self, qapp):
        overlay = MaskOverlay()
        overlay.resize(400, 300)
        received = []
        overlay.geometry_changed.connect(received.append)
        overlay.set_linear_geometry(0.1, 0.2, 0.8, 0.9)
        assert received == []


class TestRadialGeometryRoundTrip:
    def test_set_get_round_trip(self, qapp):
        overlay = MaskOverlay()
        overlay.resize(400, 300)
        overlay.set_mask_type("radial")
        overlay.set_radial_geometry(0.4, 0.6, 0.2, 0.3, 0.7)
        geometry = overlay.get_geometry()
        assert geometry["type"] == "radial"
        assert geometry["cx"] == pytest.approx(0.4)
        assert geometry["cy"] == pytest.approx(0.6)
        assert geometry["rx"] == pytest.approx(0.2)
        assert geometry["ry"] == pytest.approx(0.3)
        assert geometry["feather"] == pytest.approx(0.7)

    def test_set_radial_geometry_does_not_emit(self, qapp):
        overlay = MaskOverlay()
        overlay.resize(400, 300)
        received = []
        overlay.geometry_changed.connect(received.append)
        overlay.set_radial_geometry(0.4, 0.6, 0.2, 0.3, 0.7)
        assert received == []

    def test_set_invert(self, qapp):
        overlay = MaskOverlay()
        overlay.set_invert(True)
        assert overlay.get_invert() is True
        assert overlay.get_geometry()["invert"] is True


class TestTypeSwitchPreservesEachShapesOwnGeometry:
    def test_switching_back_and_forth_keeps_both_geometries(self, qapp):
        overlay = MaskOverlay()
        overlay.resize(400, 300)
        overlay.set_mask_type("linear")
        overlay.set_linear_geometry(0.1, 0.1, 0.9, 0.1)
        overlay.set_mask_type("radial")
        overlay.set_radial_geometry(0.3, 0.3, 0.15, 0.15, 0.4)

        overlay.set_mask_type("linear")
        assert overlay.get_geometry() == {
            "type": "linear",
            "invert": False,
            "x0": pytest.approx(0.1),
            "y0": pytest.approx(0.1),
            "x1": pytest.approx(0.9),
            "y1": pytest.approx(0.1),
        }

        overlay.set_mask_type("radial")
        geometry = overlay.get_geometry()
        assert geometry["cx"] == pytest.approx(0.3)
        assert geometry["cy"] == pytest.approx(0.3)
        assert geometry["rx"] == pytest.approx(0.15)
        assert geometry["ry"] == pytest.approx(0.15)
        assert geometry["feather"] == pytest.approx(0.4)


class TestLinearDrag:
    def test_endpoint_handle_drag_updates_fraction(self, qapp):
        overlay = MaskOverlay()
        overlay.resize(400, 200)
        overlay.set_mask_type("linear")
        overlay.set_linear_geometry(0.1, 0.5, 0.9, 0.5)

        start_px = QPointF(0.1 * 400, 0.5 * 200)
        _press(overlay, start_px)
        assert overlay._active_handle == "start"
        new_pos = QPointF(0.2 * 400, 0.3 * 200)
        _move(overlay, new_pos)
        _release(overlay, new_pos)

        geometry = overlay.get_geometry()
        assert geometry["x0"] == pytest.approx(0.2, abs=1e-6)
        assert geometry["y0"] == pytest.approx(0.3, abs=1e-6)
        # The untouched endpoint is unchanged.
        assert geometry["x1"] == pytest.approx(0.9)
        assert geometry["y1"] == pytest.approx(0.5)

    def test_endpoint_drag_emits_geometry_changed(self, qapp):
        overlay = MaskOverlay()
        overlay.resize(400, 200)
        overlay.set_mask_type("linear")
        overlay.set_linear_geometry(0.1, 0.5, 0.9, 0.5)
        received = []
        overlay.geometry_changed.connect(received.append)

        start_px = QPointF(0.9 * 400, 0.5 * 200)
        _press(overlay, start_px)
        assert overlay._active_handle == "end"
        new_pos = QPointF(0.95 * 400, 0.55 * 200)
        _move(overlay, new_pos)
        _release(overlay, new_pos)

        assert len(received) == 1
        assert received[0]["x1"] == pytest.approx(0.95, abs=1e-6)

    def test_move_drag_translates_both_endpoints_by_same_delta(self, qapp):
        overlay = MaskOverlay()
        overlay.resize(400, 200)
        overlay.set_mask_type("linear")
        overlay.set_linear_geometry(0.3, 0.4, 0.5, 0.6)

        mid_px = QPointF(0.4 * 400, 0.5 * 200)
        _press(overlay, mid_px)
        assert overlay._active_handle == "move"
        new_pos = QPointF(0.5 * 400, 0.6 * 200)
        _move(overlay, new_pos)
        _release(overlay, new_pos)

        geometry = overlay.get_geometry()
        dx = geometry["x0"] - 0.3
        dy = geometry["y0"] - 0.4
        assert geometry["x1"] - 0.5 == pytest.approx(dx, abs=1e-6)
        assert geometry["y1"] - 0.6 == pytest.approx(dy, abs=1e-6)
        assert dx == pytest.approx(0.1, abs=1e-6)
        assert dy == pytest.approx(0.1, abs=1e-6)

    def test_degenerate_drag_cannot_collapse_to_zero_length(self, qapp):
        overlay = MaskOverlay()
        overlay.resize(400, 200)
        overlay.set_mask_type("linear")
        overlay.set_linear_geometry(0.3, 0.5, 0.7, 0.5)

        start_px = QPointF(0.3 * 400, 0.5 * 200)
        _press(overlay, start_px)
        # Drag the start handle on top of the end handle.
        same_as_end = QPointF(0.7 * 400, 0.5 * 200)
        _move(overlay, same_as_end)
        _release(overlay, same_as_end)

        geometry = overlay.get_geometry()
        length = math.hypot(geometry["x1"] - geometry["x0"], geometry["y1"] - geometry["y0"])
        assert length > 0.0


class TestRadialDrag:
    def test_edge_handle_resizes_one_radius_only(self, qapp):
        overlay = MaskOverlay()
        overlay.resize(400, 200)
        overlay.set_mask_type("radial")
        overlay.set_radial_geometry(0.5, 0.5, 0.2, 0.2, 0.5)

        right_px = QPointF((0.5 + 0.2) * 400, 0.5 * 200)
        _press(overlay, right_px)
        assert overlay._active_handle == "right"
        new_pos = QPointF((0.5 + 0.3) * 400, 0.5 * 200)
        _move(overlay, new_pos)
        _release(overlay, new_pos)

        geometry = overlay.get_geometry()
        assert geometry["rx"] == pytest.approx(0.3, abs=1e-6)
        assert geometry["ry"] == pytest.approx(0.2, abs=1e-6)
        assert geometry["cx"] == pytest.approx(0.5)
        assert geometry["cy"] == pytest.approx(0.5)

    def test_move_drag_translates_center_radii_unchanged(self, qapp):
        overlay = MaskOverlay()
        overlay.resize(400, 200)
        overlay.set_mask_type("radial")
        overlay.set_radial_geometry(0.5, 0.5, 0.2, 0.2, 0.5)

        center_px = QPointF(0.5 * 400, 0.5 * 200)
        _press(overlay, center_px)
        assert overlay._active_handle == "move"
        new_pos = QPointF(0.6 * 400, 0.55 * 200)
        _move(overlay, new_pos)
        _release(overlay, new_pos)

        geometry = overlay.get_geometry()
        assert geometry["cx"] == pytest.approx(0.6, abs=1e-6)
        assert geometry["cy"] == pytest.approx(0.55, abs=1e-6)
        assert geometry["rx"] == pytest.approx(0.2)
        assert geometry["ry"] == pytest.approx(0.2)

    def test_degenerate_drag_cannot_collapse_radius_to_zero(self, qapp):
        overlay = MaskOverlay()
        overlay.resize(400, 200)
        overlay.set_mask_type("radial")
        overlay.set_radial_geometry(0.5, 0.5, 0.2, 0.2, 0.5)

        right_px = QPointF((0.5 + 0.2) * 400, 0.5 * 200)
        _press(overlay, right_px)
        # Drag the right handle on top of the center.
        at_center = QPointF(0.5 * 400, 0.5 * 200)
        _move(overlay, at_center)
        _release(overlay, at_center)

        geometry = overlay.get_geometry()
        assert geometry["rx"] > 0.0


class TestHitTestNoOp:
    def test_click_outside_shape_is_a_no_op(self, qapp):
        overlay = MaskOverlay()
        overlay.resize(400, 200)
        overlay.set_mask_type("radial")
        overlay.set_radial_geometry(0.5, 0.5, 0.1, 0.1, 0.5)
        received = []
        overlay.geometry_changed.connect(received.append)

        far_away = QPointF(5, 5)
        _press(overlay, far_away)
        assert overlay._active_handle is None
        _move(overlay, QPointF(50, 50))
        _release(overlay, QPointF(50, 50))

        assert received == []
        assert overlay.get_geometry()["cx"] == pytest.approx(0.5)


class TestRadialOverlayMatchesProcessorMath:
    """The single most important correctness test in this slice: the
    overlay's on-screen ellipse geometry must use EXACTLY the same
    per-axis-independent (rx scaled by width, ry scaled by height)
    aspect-ratio-correct scaling MaskProcessor._radial_alpha uses, so what
    the user drags is exactly what gets rendered.
    """

    @pytest.mark.parametrize("width,height", [(400, 400), (800, 200), (150, 600)])
    def test_overlay_ellipse_bounds_match_processor_alpha_boundary(
        self, qapp, width, height
    ):
        mask = {
            "type": "radial",
            "invert": False,
            "cx": 0.5,
            "cy": 0.5,
            "rx": 0.25,
            "ry": 0.15,
            "feather": 1e-6,  # Near-hard edge, so the alpha transition is tight.
        }

        overlay = MaskOverlay()
        overlay.resize(width, height)
        overlay.set_mask_type("radial")
        overlay.set_radial_geometry(
            mask["cx"], mask["cy"], mask["rx"], mask["ry"], mask["feather"]
        )
        rect = overlay._ellipse_rect_px()

        # The overlay's own pixel-space ellipse bounding box.
        expected_left = (mask["cx"] - mask["rx"]) * width
        expected_top = (mask["cy"] - mask["ry"]) * height
        expected_width = 2 * mask["rx"] * width
        expected_height = 2 * mask["ry"] * height
        assert rect.left() == pytest.approx(expected_left, abs=1e-3)
        assert rect.top() == pytest.approx(expected_top, abs=1e-3)
        assert rect.width() == pytest.approx(expected_width, abs=1e-3)
        assert rect.height() == pytest.approx(expected_height, abs=1e-3)

        # Cross-check directly against MaskProcessor's own alpha field at
        # the same image size: alpha should be ~1 (inside) just inside the
        # overlay's computed boundary and ~0 (outside) just outside it,
        # independently along BOTH axes -- proving the per-axis scaling
        # (not a single shared/diagonal radius) matches exactly.
        alpha = MaskProcessor._compute_alpha(height, width, mask)

        # Along the horizontal axis through the center (tests rx vs width).
        cy_row = int(mask["cy"] * height)
        inside_x = int(rect.left() + rect.width() * 0.5 - 2)
        outside_x = int(rect.right() + 2)
        assert alpha[cy_row, max(0, inside_x)] > 0.9
        assert alpha[cy_row, min(width - 1, outside_x)] < 0.1

        # Along the vertical axis through the center (tests ry vs height).
        cx_col = int(mask["cx"] * width)
        inside_y = int(rect.top() + rect.height() * 0.5 - 2)
        outside_y = int(rect.bottom() + 2)
        assert alpha[max(0, inside_y), cx_col] > 0.9
        assert alpha[min(height - 1, outside_y), cx_col] < 0.1
