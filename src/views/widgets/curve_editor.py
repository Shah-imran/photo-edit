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
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

from src.utils.curve_math import (
    DEFAULT_CURVE_POINTS,
    MIN_POINT_X_GAP,
    Point,
    build_curve_lut,
    normalize_points,
)

_PICK_RADIUS_PX = 9.0
_MARGIN_PX = 10.0


class CurveEditor(QWidget):
    """Interactive point-curve editor with a histogram backdrop.

    Signals:
        curve_changed: Emitted with the current points (list of ``[x,
            y]`` pairs) whenever the curve shape changes, including during
            a drag.
        curve_released: Emitted once a gesture (drag release, point
            add/delete, or reset) is committed -- the point to trigger a
            full-resolution render, matching ``AdjustmentSlider.
            slider_released``.
    """

    curve_changed = pyqtSignal(list)
    curve_released = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._points: List[Point] = list(DEFAULT_CURVE_POINTS)
        self._histogram: Optional[Sequence[int]] = None
        self._dragging_index: Optional[int] = None
        self.setMinimumHeight(180)
        self.setMouseTracking(False)

    # -- Public API ---------------------------------------------------

    def get_points(self) -> List[Point]:
        """Return a copy of the current control points."""
        return list(self._points)

    def set_points(self, points: Optional[Sequence[Sequence[float]]]) -> None:
        """Programmatically set the curve shape without emitting signals."""
        self._points = list(normalize_points(points))
        self._dragging_index = None
        self.update()

    def set_histogram(self, counts: Optional[Sequence[int]]) -> None:
        """Set the histogram backdrop (256 bin counts, or ``None`` to clear)."""
        self._histogram = counts
        self.update()

    def reset(self) -> None:
        """Reset to the identity curve and notify listeners."""
        self._points = list(DEFAULT_CURVE_POINTS)
        self._dragging_index = None
        self.update()
        self.curve_changed.emit(self.get_points())
        self.curve_released.emit()

    # -- Geometry mapping ----------------------------------------------

    def _plot_rect(self) -> QRectF:
        return QRectF(
            _MARGIN_PX,
            _MARGIN_PX,
            max(1.0, self.width() - 2 * _MARGIN_PX),
            max(1.0, self.height() - 2 * _MARGIN_PX),
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

    def _paint_curve(self, painter: QPainter, rect: QRectF) -> None:
        lut = build_curve_lut(self._points, resolution=128)
        path = QPainterPath()
        for i, y in enumerate(lut):
            x = i / (len(lut) - 1)
            point = self._to_widget(x, float(y), rect)
            if i == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        painter.setPen(QPen(QColor("#0078d4"), 2))
        painter.drawPath(path)

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

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        rect = self._plot_rect()
        pos = event.position()

        if event.button() == Qt.MouseButton.RightButton:
            index = self._nearest_point_index(pos, rect)
            if index is not None and 0 < index < len(self._points) - 1:
                del self._points[index]
                self.update()
                self.curve_changed.emit(self.get_points())
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
        self.curve_changed.emit(self.get_points())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._dragging_index is None:
            return
        rect = self._plot_rect()
        x, y = self._from_widget(event.position(), rect)
        self._points[self._dragging_index] = self._clamp_drag(
            self._dragging_index, x, y
        )
        self.update()
        self.curve_changed.emit(self.get_points())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._dragging_index is not None:
            self._dragging_index = None
            self.curve_released.emit()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging_index = None
        self.reset()
