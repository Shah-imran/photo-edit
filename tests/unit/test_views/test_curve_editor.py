"""Unit tests for the CurveEditor widget."""

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from src.views.widgets.curve_editor import CurveEditor


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


def _double_click(widget, pos):
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonDblClick,
        QPointF(pos),
        QPointF(widget.mapToGlobal(QPoint(int(pos.x()), int(pos.y())))),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mouseDoubleClickEvent(event)


class TestDefaults:
    def test_default_points_are_identity(self, qapp):
        editor = CurveEditor()
        assert editor.get_points() == [(0.0, 0.0), (1.0, 1.0)]


class TestSetPoints:
    def test_set_points_does_not_emit(self, qapp):
        editor = CurveEditor()
        received = []
        editor.curve_changed.connect(received.append)
        editor.curve_released.connect(lambda: received.append("released"))

        editor.set_points([(0.0, 0.1), (1.0, 0.9)])

        assert received == []
        assert editor.get_points() == [(0.0, 0.1), (1.0, 0.9)]


class TestMouseInteraction:
    def test_click_in_empty_area_adds_a_point(self, qapp):
        editor = CurveEditor()
        editor.resize(220, 220)
        received = []
        editor.curve_changed.connect(received.append)

        rect = editor._plot_rect()
        # Click near the middle of the plot, off the identity diagonal.
        pos = editor._to_widget(0.5, 0.2, rect)
        _press(editor, pos)

        assert len(editor.get_points()) == 3
        assert received, "curve_changed should fire on point add"

    def test_dragging_a_point_moves_it(self, qapp):
        editor = CurveEditor()
        editor.resize(220, 220)
        rect = editor._plot_rect()

        start = editor._to_widget(0.0, 0.0, rect)
        _press(editor, start)
        moved = editor._to_widget(0.0, 0.3, rect)
        _move(editor, moved)

        x, y = editor.get_points()[0]
        assert x == 0.0  # endpoint x is pinned
        assert y == pytest.approx(0.3, abs=0.02)

    def test_release_emits_curve_released(self, qapp):
        editor = CurveEditor()
        editor.resize(220, 220)
        released = []
        editor.curve_released.connect(lambda: released.append(True))

        rect = editor._plot_rect()
        pos = editor._to_widget(0.0, 0.0, rect)
        _press(editor, pos)
        _release(editor, pos)

        assert released == [True]

    def test_right_click_deletes_interior_point(self, qapp):
        editor = CurveEditor()
        editor.resize(220, 220)
        editor.set_points([(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)])

        rect = editor._plot_rect()
        pos = editor._to_widget(0.5, 0.7, rect)
        _press(editor, pos, button=Qt.MouseButton.RightButton)

        assert editor.get_points() == [(0.0, 0.0), (1.0, 1.0)]

    def test_right_click_cannot_delete_endpoint(self, qapp):
        editor = CurveEditor()
        editor.resize(220, 220)

        rect = editor._plot_rect()
        pos = editor._to_widget(0.0, 0.0, rect)
        _press(editor, pos, button=Qt.MouseButton.RightButton)

        assert len(editor.get_points()) == 2

    def test_double_click_resets_to_identity(self, qapp):
        editor = CurveEditor()
        editor.resize(220, 220)
        editor.set_points([(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)])
        released = []
        editor.curve_released.connect(lambda: released.append(True))

        rect = editor._plot_rect()
        pos = editor._to_widget(0.5, 0.7, rect)
        _double_click(editor, pos)

        assert editor.get_points() == [(0.0, 0.0), (1.0, 1.0)]
        assert released == [True]


class TestPerChannel:
    """Per-channel curve editing (PDF section 12, Phase E) -- channel
    switching, per-channel point editing, and the new signals' payload
    shape.
    """

    def test_active_channel_defaults_to_master(self, qapp):
        editor = CurveEditor()
        assert editor.get_active_channel() == "master"

    def test_set_active_channel_switches_and_emits(self, qapp):
        editor = CurveEditor()
        received = []
        editor.active_channel_changed.connect(received.append)

        editor.set_active_channel("red")

        assert editor.get_active_channel() == "red"
        assert received == ["red"]

    def test_set_active_channel_to_unknown_name_is_ignored(self, qapp):
        editor = CurveEditor()
        editor.set_active_channel("cyan")
        assert editor.get_active_channel() == "master"

    def test_get_set_points_default_to_active_channel(self, qapp):
        editor = CurveEditor()
        editor.set_active_channel("blue")
        editor.set_points([(0.0, 0.1), (1.0, 0.8)])

        assert editor.get_points() == [(0.0, 0.1), (1.0, 0.8)]
        assert editor.get_points("blue") == [(0.0, 0.1), (1.0, 0.8)]
        # Switching channels changes what the no-argument form reads.
        editor.set_active_channel("master")
        assert editor.get_points() == [(0.0, 0.0), (1.0, 1.0)]

    def test_set_points_with_explicit_channel_does_not_touch_active(self, qapp):
        editor = CurveEditor()  # active channel is "master"
        editor.set_points([(0.0, 0.2), (1.0, 0.9)], channel="green")

        assert editor.get_points("green") == [(0.0, 0.2), (1.0, 0.9)]
        assert editor.get_points() == [(0.0, 0.0), (1.0, 1.0)]  # master untouched

    def test_get_all_points_reports_every_channel(self, qapp):
        editor = CurveEditor()
        editor.set_points([(0.0, 0.3), (1.0, 0.6)], channel="red")

        all_points = editor.get_all_points()

        assert set(all_points.keys()) == {"master", "red", "green", "blue"}
        assert all_points["red"] == [(0.0, 0.3), (1.0, 0.6)]
        assert all_points["green"] == [(0.0, 0.0), (1.0, 1.0)]

    def test_set_all_points_replaces_every_channel(self, qapp):
        editor = CurveEditor()
        editor.set_all_points(
            {
                "master": [(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)],
                "red": [(0.0, 0.1), (1.0, 0.9)],
            }
        )

        all_points = editor.get_all_points()
        assert all_points["master"] == [(0.0, 0.0), (0.5, 0.6), (1.0, 1.0)]
        assert all_points["red"] == [(0.0, 0.1), (1.0, 0.9)]
        # Channels missing from the argument fall back to identity.
        assert all_points["green"] == [(0.0, 0.0), (1.0, 1.0)]
        assert all_points["blue"] == [(0.0, 0.0), (1.0, 1.0)]

    def test_dragging_edits_only_the_active_channel(self, qapp):
        editor = CurveEditor()
        editor.resize(220, 220 + 26)
        editor.set_active_channel("red")

        rect = editor._plot_rect()
        start = editor._to_widget(0.0, 0.0, rect)
        _press(editor, start)
        moved = editor._to_widget(0.0, 0.4, rect)
        _move(editor, moved)

        x, y = editor.get_points("red")[0]
        assert y == pytest.approx(0.4, abs=0.02)
        # The other 3 channels are untouched.
        assert editor.get_points("master") == [(0.0, 0.0), (1.0, 1.0)]
        assert editor.get_points("green") == [(0.0, 0.0), (1.0, 1.0)]
        assert editor.get_points("blue") == [(0.0, 0.0), (1.0, 1.0)]

    def test_channel_curve_changed_emits_active_channel_and_points(self, qapp):
        editor = CurveEditor()
        editor.resize(220, 220 + 26)
        editor.set_active_channel("green")
        received = []
        editor.channel_curve_changed.connect(
            lambda channel, points: received.append((channel, points))
        )

        rect = editor._plot_rect()
        pos = editor._to_widget(0.0, 0.0, rect)
        _press(editor, pos)

        assert received, "channel_curve_changed should fire on point press"
        channel, points = received[-1]
        assert channel == "green"
        assert points == editor.get_points("green")

    def test_curve_changed_still_fires_for_active_channel(self, qapp):
        """``curve_changed`` keeps its original, pre-channel payload
        shape (just a points list) regardless of which channel is
        active -- backward compatibility for existing listeners.
        """
        editor = CurveEditor()
        editor.resize(220, 220 + 26)
        editor.set_active_channel("blue")
        received = []
        editor.curve_changed.connect(received.append)

        rect = editor._plot_rect()
        pos = editor._to_widget(0.0, 0.0, rect)
        _press(editor, pos)

        assert received
        assert received[-1] == editor.get_points("blue")

    def test_reset_resets_only_active_channel(self, qapp):
        editor = CurveEditor()
        editor.set_points([(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)], channel="master")
        editor.set_points([(0.0, 0.2), (1.0, 0.9)], channel="red")
        editor.set_active_channel("master")

        editor.reset()

        assert editor.get_points("master") == [(0.0, 0.0), (1.0, 1.0)]
        assert editor.get_points("red") == [(0.0, 0.2), (1.0, 0.9)]

    def test_reset_all_channels_resets_every_curve(self, qapp):
        editor = CurveEditor()
        editor.set_all_points(
            {
                "master": [(0.0, 0.0), (0.5, 0.7), (1.0, 1.0)],
                "red": [(0.0, 0.2), (1.0, 0.9)],
                "green": [(0.0, 0.1), (1.0, 0.8)],
                "blue": [(0.0, 0.3), (1.0, 0.6)],
            }
        )
        released = []
        editor.curve_released.connect(lambda: released.append(True))

        editor.reset_all_channels()

        all_points = editor.get_all_points()
        for channel in ("master", "red", "green", "blue"):
            assert all_points[channel] == [(0.0, 0.0), (1.0, 1.0)]
        assert released == [True]
