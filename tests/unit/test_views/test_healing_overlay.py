"""Unit tests for the HealingOverlay widget."""

import math

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from src.views.widgets.healing_overlay import HealingOverlay


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


class TestSetGetSpotsRoundTrip:
    def test_round_trip_does_not_emit(self, qapp):
        overlay = HealingOverlay()
        overlay.resize(400, 300)
        received = []
        overlay.spots_changed.connect(received.append)
        spots = [
            {
                "dst_x": 0.3, "dst_y": 0.4, "src_x": 0.5, "src_y": 0.4,
                "radius": 0.05, "feather": 0.3, "opacity": 1.0, "mode": "heal",
            }
        ]
        overlay.set_spots(spots)
        assert overlay.get_spots() == spots
        assert received == []

    def test_get_spots_is_a_copy(self, qapp):
        overlay = HealingOverlay()
        overlay.resize(400, 300)
        spots = [
            {
                "dst_x": 0.3, "dst_y": 0.4, "src_x": 0.5, "src_y": 0.4,
                "radius": 0.05, "feather": 0.3, "opacity": 1.0, "mode": "heal",
            }
        ]
        overlay.set_spots(spots)
        result = overlay.get_spots()
        result[0]["dst_x"] = 0.99
        assert overlay.get_spots()[0]["dst_x"] == pytest.approx(0.3)


class TestPlacementDragReleaseSimpleCase:
    """A press comfortably away from any edge: the simple right-offset
    source case."""

    def test_placed_spot_has_expected_center_radius_and_right_offset_source(
        self, qapp
    ):
        overlay = HealingOverlay()
        overlay.resize(400, 400)

        press_px = QPointF(0.5 * 400, 0.5 * 400)
        _press(overlay, press_px)
        drag_px = QPointF((0.5 + 0.08) * 400, 0.5 * 400)
        _move(overlay, drag_px)
        _release(overlay, drag_px)

        spots = overlay.get_spots()
        assert len(spots) == 1
        spot = spots[0]
        assert spot["dst_x"] == pytest.approx(0.5, abs=1e-6)
        assert spot["dst_y"] == pytest.approx(0.5, abs=1e-6)
        assert spot["radius"] == pytest.approx(0.08, abs=1e-6)

        # Simple case: source offset directly to the right by 2*radius.
        expected_src_x = 0.5 + 2.0 * 0.08
        assert spot["src_x"] == pytest.approx(expected_src_x, abs=1e-6)
        assert spot["src_y"] == pytest.approx(0.5, abs=1e-6)

    def test_spots_changed_emitted_on_placement(self, qapp):
        overlay = HealingOverlay()
        overlay.resize(400, 400)
        received = []
        overlay.spots_changed.connect(received.append)

        press_px = QPointF(0.5 * 400, 0.5 * 400)
        _press(overlay, press_px)
        drag_px = QPointF((0.5 + 0.05) * 400, 0.5 * 400)
        _move(overlay, drag_px)
        _release(overlay, drag_px)

        assert len(received) == 1
        assert len(received[0]) == 1


class TestPlacementNearRightEdgeFallsBackToLeftOffset:
    def test_source_flips_to_left_when_right_offset_would_overflow(self, qapp):
        overlay = HealingOverlay()
        overlay.resize(400, 400)

        # Destination near the right edge; radius large enough that
        # dst_x + 2*radius + radius > 1.0 (right doesn't fit), but
        # dst_x - 2*radius - radius >= 0.0 (left fits).
        dst_x = 0.9
        radius = 0.08
        press_px = QPointF(dst_x * 400, 0.5 * 400)
        _press(overlay, press_px)
        drag_px = QPointF((dst_x + radius) * 400, 0.5 * 400)
        _move(overlay, drag_px)
        _release(overlay, drag_px)

        spots = overlay.get_spots()
        assert len(spots) == 1
        spot = spots[0]
        assert spot["radius"] == pytest.approx(radius, abs=1e-6)

        # Right offset would overflow (0.9 + 0.16 + 0.08 = 1.14 > 1.0);
        # left offset (0.9 - 0.16 = 0.74, minus radius = 0.66 >= 0) fits.
        expected_src_x = dst_x - 2.0 * radius
        assert spot["src_x"] == pytest.approx(expected_src_x, abs=1e-6)
        assert spot["src_y"] == pytest.approx(0.5, abs=1e-6)


class TestRemoveLastAndClearAll:
    def _place_spot(self, overlay, dst_x=0.5, dst_y=0.5, radius=0.05):
        press_px = QPointF(dst_x * overlay.width(), dst_y * overlay.height())
        _press(overlay, press_px)
        drag_px = QPointF((dst_x + radius) * overlay.width(), dst_y * overlay.height())
        _move(overlay, drag_px)
        _release(overlay, drag_px)

    def test_remove_last_no_op_on_empty(self, qapp):
        overlay = HealingOverlay()
        overlay.resize(400, 400)
        received = []
        overlay.spots_changed.connect(received.append)
        overlay.remove_last()
        assert overlay.get_spots() == []
        assert received == []

    def test_clear_all_no_op_on_empty(self, qapp):
        overlay = HealingOverlay()
        overlay.resize(400, 400)
        received = []
        overlay.spots_changed.connect(received.append)
        overlay.clear_all()
        assert overlay.get_spots() == []
        assert received == []

    def test_remove_last_pops_most_recent(self, qapp):
        overlay = HealingOverlay()
        overlay.resize(400, 400)
        self._place_spot(overlay, 0.3, 0.3)
        self._place_spot(overlay, 0.7, 0.7)
        assert len(overlay.get_spots()) == 2

        received = []
        overlay.spots_changed.connect(received.append)
        overlay.remove_last()

        spots = overlay.get_spots()
        assert len(spots) == 1
        assert spots[0]["dst_x"] == pytest.approx(0.3)
        assert len(received) == 1
        assert len(received[0]) == 1

    def test_clear_all_empties_list(self, qapp):
        overlay = HealingOverlay()
        overlay.resize(400, 400)
        self._place_spot(overlay, 0.3, 0.3)
        self._place_spot(overlay, 0.7, 0.7)

        received = []
        overlay.spots_changed.connect(received.append)
        overlay.clear_all()

        assert overlay.get_spots() == []
        assert len(received) == 1
        assert received[0] == []


class TestMultiplePlacementsAccumulate:
    def test_sequential_placements_accumulate_in_order(self, qapp):
        overlay = HealingOverlay()
        overlay.resize(400, 400)

        for dst_x in (0.2, 0.4, 0.6):
            press_px = QPointF(dst_x * 400, 0.5 * 400)
            _press(overlay, press_px)
            drag_px = QPointF((dst_x + 0.03) * 400, 0.5 * 400)
            _move(overlay, drag_px)
            _release(overlay, drag_px)

        spots = overlay.get_spots()
        assert len(spots) == 3
        assert [round(s["dst_x"], 3) for s in spots] == [0.2, 0.4, 0.6]


class TestPendingValuesBakedInAtPlacementTime:
    """The key proof that toolbar settings apply to the NEXT spot only,
    not retroactively: place one spot with one set of pending values,
    change them, place a second spot, and assert the two spots differ."""

    def test_two_spots_reflect_different_pending_values_at_their_own_placement(
        self, qapp
    ):
        overlay = HealingOverlay()
        overlay.resize(400, 400)

        overlay.set_pending_mode("heal")
        overlay.set_pending_feather(0.2)
        overlay.set_pending_opacity(0.5)

        press_px = QPointF(0.2 * 400, 0.5 * 400)
        _press(overlay, press_px)
        drag_px = QPointF(0.25 * 400, 0.5 * 400)
        _move(overlay, drag_px)
        _release(overlay, drag_px)

        # Change pending values AFTER the first spot is already placed.
        overlay.set_pending_mode("clone")
        overlay.set_pending_feather(0.9)
        overlay.set_pending_opacity(0.1)

        press_px2 = QPointF(0.7 * 400, 0.5 * 400)
        _press(overlay, press_px2)
        drag_px2 = QPointF(0.75 * 400, 0.5 * 400)
        _move(overlay, drag_px2)
        _release(overlay, drag_px2)

        spots = overlay.get_spots()
        assert len(spots) == 2

        first, second = spots
        assert first["mode"] == "heal"
        assert first["feather"] == pytest.approx(0.2)
        assert first["opacity"] == pytest.approx(0.5)

        assert second["mode"] == "clone"
        assert second["feather"] == pytest.approx(0.9)
        assert second["opacity"] == pytest.approx(0.1)

        # Changing pending values after placement never retroactively
        # changed the first, already-placed spot.
        assert first["mode"] != second["mode"]
        assert first["feather"] != second["feather"]
        assert first["opacity"] != second["opacity"]


class TestRadiusClamping:
    def test_radius_clamped_to_minimum_floor(self, qapp):
        overlay = HealingOverlay()
        overlay.resize(400, 400)

        press_px = QPointF(0.5 * 400, 0.5 * 400)
        _press(overlay, press_px)
        # Zero-distance move -- radius would be exactly 0 without a floor.
        _move(overlay, press_px)
        _release(overlay, press_px)

        spots = overlay.get_spots()
        assert len(spots) == 1
        assert spots[0]["radius"] >= 0.01 - 1e-9

    def test_radius_clamped_to_maximum(self, qapp):
        overlay = HealingOverlay()
        overlay.resize(400, 400)

        press_px = QPointF(0.5 * 400, 0.5 * 400)
        _press(overlay, press_px)
        drag_px = QPointF(2000, 2000)
        _move(overlay, drag_px)
        _release(overlay, drag_px)

        spots = overlay.get_spots()
        assert len(spots) == 1
        assert spots[0]["radius"] <= 0.5 + 1e-9
