"""Interactive tone-curve editor widget.

Draws a point curve over an optional histogram backdrop and lets the user
add, drag, and delete control points. Mirrors ``AdjustmentSlider``'s
signal shape (``value_changed``/``slider_released``) so ``ToolsPanel`` can
wire it into the same "continuous during drag, commit on release" pattern:
``curve_changed`` fires continuously, ``curve_released`` fires once the
gesture (drag, add, delete, or reset) is committed.

No adjustment math lives here beyond point bookkeeping: the curve shape
itself is computed by :mod:`src.utils.curve_math`, the same module
``CurveProcessor`` uses, so the drawn curve and the applied curve are
always identical (INCREMENTAL_WORKFLOW.md section 5.1: no adjustment math
in widgets).

Per-channel editing (PDF section 12, Phase E)
----------------------------------------------
There are FOUR independent curves -- "master" (RGB) plus "red"/"green"/
"blue" -- each its own list of ``(x, y)`` control points, defaulting to
the identity diagonal. A small channel-selector bar ("RGB"/"R"/"G"/"B")
at the top of the widget switches which one is currently being edited;
all the existing drag/add/delete/reset interaction keeps working exactly
as before, just against whichever channel is "active". The other three
channels' curves are drawn faintly, tinted in their own channel color,
behind the active curve -- similar to Lightroom's own point-curve editor
-- so the user can see all four curves at a glance without losing track
of which one responds to the mouse.

``get_points()``/``set_points()`` keep their original, pre-channel
meaning: with no ``channel`` argument, they read/write whichever channel
is currently active (``"master"`` by default, since that is the editor's
initial active channel) -- this is what lets
``tests/unit/test_views/test_curve_editor.py`` and
``tests/unit/test_views/test_tools_panel.py``'s existing master-curve
assertions keep passing unchanged. ``get_all_points()``/``set_all_points()``
are the new channel-aware entry points for the other three channels.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from src.utils.curve_math import (
    DEFAULT_CURVE_POINTS,
    MIN_POINT_X_GAP,
    Point,
    build_curve_lut,
    normalize_points,
)

_PICK_RADIUS_PX = 9.0
_MARGIN_PX = 10.0
_CHANNEL_BAR_HEIGHT = 26

#: The four editable curves, in the order their selector buttons appear.
CHANNELS = ("master", "red", "green", "blue")

#: Button/curve-overlay label and tint color for each channel. The active
#: channel's own curve is always drawn in the usual accent color
#: (``#0078d4``, see ``_paint_curve``); these are only for the dim,
#: inactive overlay lines and the selector buttons.
_CHANNEL_LABELS = {"master": "RGB", "red": "R", "green": "G", "blue": "B"}
_CHANNEL_COLORS = {
    "master": QColor(224, 224, 224),
    "red": QColor(255, 90, 90),
    "green": QColor(90, 220, 90),
    "blue": QColor(90, 150, 255),
}


class CurveEditor(QWidget):
    """Interactive point-curve editor with a histogram backdrop and a
    channel selector (RGB/R/G/B).

    Signals:
        curve_changed: Emitted with the ACTIVE channel's current points
            (list of ``[x, y]`` pairs) whenever its shape changes,
            including during a drag. Kept to its original, pre-channel
            payload shape for backward compatibility.
        curve_released: Emitted once a gesture (drag release, point
            add/delete, or reset) is committed -- the point to trigger a
            full-resolution render, matching ``AdjustmentSlider.
            slider_released``.
        channel_curve_changed: New in the per-channel slice. Emitted
            alongside ``curve_changed`` with ``(channel, points)``, so a
            listener that cares which of the 4 curves actually changed
            (``ToolsPanel``, for the real multi-channel wiring) doesn't
            have to guess from ``curve_changed`` alone.
        active_channel_changed: New in the per-channel slice. Emitted
            when the user switches the channel selector.
    """

    curve_changed = pyqtSignal(list)
    curve_released = pyqtSignal()
    channel_curve_changed = pyqtSignal(str, list)
    active_channel_changed = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._channel_points: Dict[str, List[Point]] = {
            channel: list(DEFAULT_CURVE_POINTS) for channel in CHANNELS
        }
        self._active_channel: str = "master"
        self._histogram: Optional[Sequence[int]] = None
        self._dragging_index: Optional[int] = None

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self._channel_bar = QWidget(self)
        self._channel_bar.setFixedHeight(_CHANNEL_BAR_HEIGHT)
        bar_layout = QHBoxLayout(self._channel_bar)
        bar_layout.setContentsMargins(0, 0, 0, 4)
        bar_layout.setSpacing(4)
        self._channel_buttons: Dict[str, QPushButton] = {}
        self._channel_button_group = QButtonGroup(self)
        self._channel_button_group.setExclusive(True)
        for channel in CHANNELS:
            button = QPushButton(_CHANNEL_LABELS[channel])
            button.setCheckable(True)
            button.setChecked(channel == self._active_channel)
            button.setFixedHeight(_CHANNEL_BAR_HEIGHT - 4)
            tint = _CHANNEL_COLORS[channel]
            button.setStyleSheet(
                "QPushButton {"
                f"  color: rgb({tint.red()}, {tint.green()}, {tint.blue()});"
                "  background-color: #2d2d2d;"
                "  border: 1px solid #3a3a3a;"
                "  border-radius: 3px;"
                "  padding: 1px 8px;"
                "}"
                "QPushButton:checked {"
                "  background-color: #0078d4;"
                "  color: #ffffff;"
                "  border: 1px solid #0078d4;"
                "}"
            )
            bar_layout.addWidget(button)
            self._channel_button_group.addButton(button)
            self._channel_buttons[channel] = button
            button.clicked.connect(
                lambda _checked=False, c=channel: self.set_active_channel(c)
            )
        bar_layout.addStretch(1)
        outer_layout.addWidget(self._channel_bar)
        outer_layout.addStretch(1)

        self.setMinimumHeight(180 + _CHANNEL_BAR_HEIGHT)
        self.setMouseTracking(False)

    # -- Channel selection ---------------------------------------------

    def get_active_channel(self) -> str:
        """Return the channel currently being edited/displayed."""
        return self._active_channel

    def set_active_channel(self, channel: str) -> None:
        """Switch which channel's curve subsequent interaction edits.

        Does not itself change any curve's shape, and does not emit
        ``curve_changed``/``curve_released`` -- only ``active_channel_
        changed``, matching ``set_points``'s own "programmatic state
        changes don't emit curve signals" convention.
        """
        if channel not in CHANNELS or channel == self._active_channel:
            return
        self._active_channel = channel
        self._dragging_index = None
        button = self._channel_buttons.get(channel)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        self.update()
        self.active_channel_changed.emit(channel)

    # -- Public API ---------------------------------------------------

    @property
    def _points(self) -> List[Point]:
        """The ACTIVE channel's point list (by reference, not a copy) --
        every existing paint/mouse-handling method below reads and
        mutates this in place exactly as it did before per-channel
        support existed.
        """
        return self._channel_points[self._active_channel]

    @_points.setter
    def _points(self, value: List[Point]) -> None:
        self._channel_points[self._active_channel] = value

    def get_points(self, channel: Optional[str] = None) -> List[Point]:
        """Return a copy of ``channel``'s control points.

        ``channel`` defaults to whichever channel is currently active
        (``"master"`` right after construction), preserving this
        method's original, pre-channel meaning for existing callers.
        """
        key = channel if channel is not None else self._active_channel
        return list(self._channel_points.get(key, DEFAULT_CURVE_POINTS))

    def set_points(
        self, points: Optional[Sequence[Sequence[float]]], channel: Optional[str] = None
    ) -> None:
        """Programmatically set ``channel``'s curve shape without
        emitting signals.

        ``channel`` defaults to the currently active channel, preserving
        this method's original, pre-channel meaning for existing
        callers.
        """
        key = channel if channel is not None else self._active_channel
        if key not in CHANNELS:
            return
        self._channel_points[key] = list(normalize_points(points))
        if key == self._active_channel:
            self._dragging_index = None
        self.update()

    def get_all_points(self) -> Dict[str, List[Point]]:
        """Return a copy of every channel's control points, keyed by
        channel name (``"master"``/``"red"``/``"green"``/``"blue"``).
        """
        return {
            channel: list(points) for channel, points in self._channel_points.items()
        }

    def set_all_points(
        self, points_by_channel: Optional[Dict[str, Sequence[Sequence[float]]]]
    ) -> None:
        """Programmatically set every channel's curve shape at once,
        without emitting signals. Any channel missing from
        ``points_by_channel`` (or the whole argument being falsy) resets
        to the identity curve.
        """
        points_by_channel = points_by_channel or {}
        for channel in CHANNELS:
            self._channel_points[channel] = list(
                normalize_points(points_by_channel.get(channel))
            )
        self._dragging_index = None
        self.update()

    def set_histogram(self, counts: Optional[Sequence[int]]) -> None:
        """Set the histogram backdrop (256 bin counts, or ``None`` to clear)."""
        self._histogram = counts
        self.update()

    def reset(self) -> None:
        """Reset the ACTIVE channel to the identity curve and notify
        listeners (standard curve-editor UX: a per-channel "Reset"
        touches only the channel currently being edited, matching
        Lightroom's own behavior).
        """
        self._points = list(DEFAULT_CURVE_POINTS)
        self._dragging_index = None
        self.update()
        points = self.get_points()
        self.curve_changed.emit(points)
        self.channel_curve_changed.emit(self._active_channel, points)
        self.curve_released.emit()

    def reset_all_channels(self) -> None:
        """Reset every one of the 4 curves (master + R/G/B) to identity."""
        for channel in CHANNELS:
            self._channel_points[channel] = list(DEFAULT_CURVE_POINTS)
        self._dragging_index = None
        self.update()
        points = self.get_points()
        self.curve_changed.emit(points)
        for channel in CHANNELS:
            self.channel_curve_changed.emit(channel, list(DEFAULT_CURVE_POINTS))
        self.curve_released.emit()

    # -- Geometry mapping ----------------------------------------------

    def _plot_rect(self) -> QRectF:
        top = _MARGIN_PX + _CHANNEL_BAR_HEIGHT
        return QRectF(
            _MARGIN_PX,
            top,
            max(1.0, self.width() - 2 * _MARGIN_PX),
            max(1.0, self.height() - top - _MARGIN_PX),
        )

    @staticmethod
    def _to_widget(x: float, y: float, rect: QRectF) -> QPointF:
        return QPointF(
            rect.left() + x * rect.width(),
            rect.bottom() - y * rect.height(),
        )

    @staticmethod
    def _from_widget(pos: QPointF, rect: QRectF) -> Point:
        x = (pos.x() - rect.left()) / rect.width()
        y = (rect.bottom() - pos.y()) / rect.height()
        return (min(1.0, max(0.0, x)), min(1.0, max(0.0, y)))

    # -- Painting --------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self._plot_rect()

        painter.fillRect(self.rect(), QColor("#2d2d2d"))
        painter.setPen(QPen(QColor("#3a3a3a"), 1))
        painter.drawRect(rect)

        self._paint_histogram(painter, rect)
        self._paint_grid(painter, rect)
        self._paint_diagonal(painter, rect)
        self._paint_inactive_curves(painter, rect)
        self._paint_curve(painter, rect)
        self._paint_points(painter, rect)

        painter.end()

    def _paint_histogram(self, painter: QPainter, rect: QRectF) -> None:
        if self._histogram is None or len(self._histogram) == 0:
            return
        counts = list(self._histogram)
        peak = max(counts) if counts else 0
        if peak <= 0:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(160, 160, 160, 70))
        bin_width = rect.width() / len(counts)
        for i, count in enumerate(counts):
            bar_height = (count / peak) * rect.height()
            x = rect.left() + i * bin_width
            painter.drawRect(
                QRectF(x, rect.bottom() - bar_height, bin_width + 0.5, bar_height)
            )

    def _paint_grid(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(QColor("#3a3a3a"), 1))
        for fraction in (0.25, 0.5, 0.75):
            x = rect.left() + fraction * rect.width()
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            y = rect.top() + fraction * rect.height()
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

    def _paint_diagonal(self, painter: QPainter, rect: QRectF) -> None:
        pen = QPen(QColor("#4a4a4a"), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(
            self._to_widget(0.0, 0.0, rect), self._to_widget(1.0, 1.0, rect)
        )

    def _curve_path(self, points: Sequence[Point], rect: QRectF) -> QPainterPath:
        lut = build_curve_lut(points, resolution=128)
        path = QPainterPath()
        for i, y in enumerate(lut):
            x = i / (len(lut) - 1)
            point = self._to_widget(x, float(y), rect)
            if i == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        return path

    def _paint_inactive_curves(self, painter: QPainter, rect: QRectF) -> None:
        """Draw the 3 non-active channels' curves faintly, tinted in
        their own channel color, behind the active curve -- so the user
        can see all 4 curves at a glance (Lightroom's own point-curve
        editor does the same) without losing track of which one the
        mouse edits.
        """
        for channel in CHANNELS:
            if channel == self._active_channel:
                continue
            points = self._channel_points[channel]
            if normalize_points(points) == DEFAULT_CURVE_POINTS:
                continue
            tint = _CHANNEL_COLORS[channel]
            dim = QColor(tint.red(), tint.green(), tint.blue(), 110)
            painter.setPen(QPen(dim, 1.5))
            painter.drawPath(self._curve_path(points, rect))

    def _paint_curve(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(QColor("#0078d4"), 2))
        painter.drawPath(self._curve_path(self._points, rect))

    def _paint_points(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(QColor("#e0e0e0"), 1.5))
        painter.setBrush(QColor("#0078d4"))
        for x, y in self._points:
            center = self._to_widget(x, y, rect)
            painter.drawEllipse(center, 4.5, 4.5)

    # -- Interaction -------------------------------------------------

    def _nearest_point_index(self, pos: QPointF, rect: QRectF) -> Optional[int]:
        best_index = None
        best_distance = _PICK_RADIUS_PX
        for i, (x, y) in enumerate(self._points):
            widget_pos = self._to_widget(x, y, rect)
            distance = (
                (widget_pos.x() - pos.x()) ** 2 + (widget_pos.y() - pos.y()) ** 2
            ) ** 0.5
            if distance <= best_distance:
                best_distance = distance
                best_index = i
        return best_index

    def _clamp_drag(self, index: int, x: float, y: float) -> Point:
        if index == 0:
            return (0.0, y)
        if index == len(self._points) - 1:
            return (1.0, y)
        lower = self._points[index - 1][0] + MIN_POINT_X_GAP
        upper = self._points[index + 1][0] - MIN_POINT_X_GAP
        if upper < lower:
            x = lower
        else:
            x = min(upper, max(lower, x))
        return (x, y)

    def _emit_changed(self) -> None:
        points = self.get_points()
        self.curve_changed.emit(points)
        self.channel_curve_changed.emit(self._active_channel, points)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        rect = self._plot_rect()
        pos = event.position()
        if pos.y() < rect.top() - _MARGIN_PX:
            # Click landed on the channel-selector bar; let the button
            # widgets (real Qt children) handle it themselves.
            return

        if event.button() == Qt.MouseButton.RightButton:
            index = self._nearest_point_index(pos, rect)
            if index is not None and 0 < index < len(self._points) - 1:
                del self._points[index]
                self.update()
                self._emit_changed()
                self.curve_released.emit()
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        index = self._nearest_point_index(pos, rect)
        if index is None:
            x, y = self._from_widget(pos, rect)
            insert_at = 0
            while insert_at < len(self._points) and self._points[insert_at][0] < x:
                insert_at += 1
            self._points.insert(insert_at, (x, y))
            index = insert_at

        self._dragging_index = index
        self.update()
        self._emit_changed()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._dragging_index is None:
            return
        rect = self._plot_rect()
        x, y = self._from_widget(event.position(), rect)
        self._points[self._dragging_index] = self._clamp_drag(
            self._dragging_index, x, y
        )
        self.update()
        self._emit_changed()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._dragging_index is not None:
            self._dragging_index = None
            self.curve_released.emit()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        rect = self._plot_rect()
        if event.position().y() < rect.top() - _MARGIN_PX:
            return
        self._dragging_index = None
        self.reset()
