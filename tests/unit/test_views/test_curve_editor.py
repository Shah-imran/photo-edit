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
