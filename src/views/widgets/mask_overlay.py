"""Interactive drag-handle mask overlay (linear gradient / radial ellipse).

Meant to be used as a direct child of ``ImageView._image_canvas``, exactly
like :class:`~src.views.widgets.crop_overlay.CropOverlay` (this widget's
direct architectural template -- see docs/planning/implementation-notes/
2026-10-13-mask-tool-ui.md section 3.1). Per ``_ImageCanvas.set_pixmap``'s
own contract, the canvas widget's own ``(0, 0)``-to-``(width, height)``
rect IS the displayed, zoomed pixmap's screen rect at any zoom level. A
child widget resized to match the canvas and positioned at ``(0, 0)``
therefore has a 1:1 pixel correspondence with the canvas's local
coordinates, with no scroll-offset correction needed -- ``local_x /
self.width()`` and ``local_y / self.height()`` are directly the
normalized image-fraction mask coordinates this overlay stores and emits.

Handles BOTH mask shapes via a single ``mask_type`` property:

- ``"linear"``: a draggable 2-endpoint gradient line (``x0,y0`` ->
  ``x1,y1``, normalized fractions).
- ``"radial"``: a draggable, axis-aligned (no rotation -- v1 scope) ellipse
  (``cx,cy,rx,ry``, normalized fractions, plus ``feather``, not
  interactively dragged in this v1 -- only the toolbar's geometry setters
  touch it).

Each type keeps its OWN independent last-known geometry at all times
(``set_mask_type`` never discards the other type's state), so switching
the toolbar's combo back and forth never loses where the user had the
other shape.
"""

from __future__ import annotations

import math
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

_HANDLE_SIZE_PX = 9.0
_HANDLE_HIT_RADIUS_PX = 10.0
_LINE_HIT_TOLERANCE_PX = 8.0

# Degenerate-geometry floors, mirroring CropOverlay's own
# _MIN_RECT_SIZE_FRACTION -- a documented, deliberately simple (not
# pixel-aspect-corrected) usability floor in normalized-fraction space,
# distinct from (and in addition to) MaskProcessor's own zero-length/
# near-zero-radius math guards.
_MIN_LINE_LENGTH_FRACTION = 0.02
_MIN_RADIUS_FRACTION = 0.02

_LINEAR = "linear"
_RADIAL = "radial"


class MaskOverlay(QWidget):
    """Transparent, mouse-draggable mask geometry overlay (both shapes).

    Signals:
        geometry_changed: Emitted with the current type's geometry dict
            (shaped exactly per ``MaskProcessor``'s own contract for that
            type, including ``"type"``/``"invert"``, but never the 4
            adjustment values -- see ``get_geometry``) continuously
            during a user drag. Never emitted by the programmatic setters.
    """

    geometry_changed = pyqtSignal(dict)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self._mask_type = _LINEAR
        self._invert = False

        # Each type's geometry is kept independently, regardless of which
        # is currently active -- see module docstring.
        self._x0, self._y0, self._x1, self._y1 = 0.3, 0.5, 0.7, 0.5
        self._cx, self._cy, self._rx, self._ry, self._feather = 0.5, 0.5, 0.25, 0.25, 0.5

        self._active_handle: Optional[str] = None
        self._drag_anchor: Optional[tuple] = None

    # -- Public API -----------------------------------------------------

    def set_mask_type(self, mask_type: str) -> None:
        """Switch the active shape. Does not touch either shape's state."""
        if mask_type in (_LINEAR, _RADIAL):
            self._mask_type = mask_type
            self.update()

    def get_mask_type(self) -> str:
        return self._mask_type

    def set_linear_geometry(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """Programmatic set of the linear gradient's endpoints. No signal."""
        self._x0, self._y0, self._x1, self._y1 = self._clamp_line(x0, y0, x1, y1)
        self.update()

    def set_radial_geometry(
        self, cx: float, cy: float, rx: float, ry: float, feather: float
    ) -> None:
        """Programmatic set of the radial ellipse's geometry. No signal."""
        self._cx, self._cy, self._rx, self._ry, self._feather = self._clamp_ellipse(
            cx, cy, rx, ry, feather
        )
        self.update()

    def set_invert(self, invert: bool) -> None:
        self._invert = bool(invert)

    def get_invert(self) -> bool:
        return self._invert

    def get_geometry(self) -> dict:
        """Return the CURRENT type's geometry dict, per MaskProcessor's own
        contract: ``"type"``/``"invert"`` plus that type's geometry keys.
        Deliberately excludes the 4 adjustment values -- those live in
        ``MaskToolbar``, assembled by the caller at Apply/preview time.
        """
        if self._mask_type == _LINEAR:
            return {
                "type": _LINEAR,
                "invert": self._invert,
                "x0": self._x0,
                "y0": self._y0,
                "x1": self._x1,
                "y1": self._y1,
            }
        return {
            "type": _RADIAL,
            "invert": self._invert,
            "cx": self._cx,
            "cy": self._cy,
            "rx": self._rx,
            "ry": self._ry,
            "feather": self._feather,
        }

    # -- Geometry helpers -------------------------------------------------

    @staticmethod
    def _clamp_line(x0: float, y0: float, x1: float, y1: float) -> tuple:
        x0 = max(0.0, min(1.0, x0))
        y0 = max(0.0, min(1.0, y0))
        x1 = max(0.0, min(1.0, x1))
        y1 = max(0.0, min(1.0, y1))
        length = math.hypot(x1 - x0, y1 - y0)
        if length < _MIN_LINE_LENGTH_FRACTION:
            # Degenerate (near-zero-length) drag result: push the end point
            # out along whatever direction it still has (or straight right,
            # if the two points coincided exactly) to the minimum floor,
            # rather than collapsing to a single point.
            if length < 1e-9:
                x1 = min(1.0, x0 + _MIN_LINE_LENGTH_FRACTION)
            else:
                scale = _MIN_LINE_LENGTH_FRACTION / length
                x1 = x0 + (x1 - x0) * scale
                y1 = y0 + (y1 - y0) * scale
                x1 = max(0.0, min(1.0, x1))
                y1 = max(0.0, min(1.0, y1))
        return x0, y0, x1, y1

    @staticmethod
    def _clamp_ellipse(cx: float, cy: float, rx: float, ry: float, feather: float) -> tuple:
        cx = max(0.0, min(1.0, cx))
        cy = max(0.0, min(1.0, cy))
        rx = max(_MIN_RADIUS_FRACTION, min(1.0, rx))
        ry = max(_MIN_RADIUS_FRACTION, min(1.0, ry))
        feather = max(0.0, min(1.0, feather))
        return cx, cy, rx, ry, feather

    def _line_px(self) -> tuple:
        w, h = max(1, self.width()), max(1, self.height())
        return (self._x0 * w, self._y0 * h, self._x1 * w, self._y1 * h)

    def _ellipse_rect_px(self) -> QRectF:
        """Bounding rect of the on-screen ellipse, in this widget's own
        local pixel space.

        ``rx``/``ry`` are each scaled by THIS WIDGET's own width/height --
        exactly mirroring ``MaskProcessor._radial_alpha``'s per-axis-
        independent scaling of the same normalized ``rx``/``ry`` fractions
        by the real image's own width/height. Since this widget's pixel
        size always has the same aspect ratio as the displayed image (see
        module docstring), the two are mathematically the same scaling,
        just expressed against two differently-sized but same-aspect-ratio
        canvases -- this is the property
        ``test_mask_overlay.py``'s aspect-ratio-correctness test verifies
        directly against ``MaskProcessor``'s own math, not just visually.
        """
        w, h = max(1, self.width()), max(1, self.height())
        cx_px, cy_px = self._cx * w, self._cy * h
        rx_px, ry_px = self._rx * w, self._ry * h
        return QRectF(cx_px - rx_px, cy_px - ry_px, rx_px * 2.0, ry_px * 2.0)

    @staticmethod
    def _point_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
        """Shortest distance from ``(px, py)`` to segment ``(a, b)``."""
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        if length_sq < 1e-9:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
        proj_x, proj_y = ax + t * dx, ay + t * dy
        return math.hypot(px - proj_x, py - proj_y)

    def _hit_test(self, pos) -> Optional[str]:
        """Return a handle name, ``"move"``, or ``None``, for ``pos`` (a
        point-like object with ``.x()``/``.y()`` in local pixel coords)."""
        px, py = pos.x(), pos.y()
        if self._mask_type == _LINEAR:
            x0, y0, x1, y1 = self._line_px()
            if math.hypot(px - x0, py - y0) <= _HANDLE_HIT_RADIUS_PX:
                return "start"
            if math.hypot(px - x1, py - y1) <= _HANDLE_HIT_RADIUS_PX:
                return "end"
            if self._point_segment_distance(px, py, x0, y0, x1, y1) <= _LINE_HIT_TOLERANCE_PX:
                return "move"
            return None

        rect = self._ellipse_rect_px()
        cx_px, cy_px = rect.center().x(), rect.center().y()
        edge_handles = {
            "top": (cx_px, rect.top()),
            "bottom": (cx_px, rect.bottom()),
            "left": (rect.left(), cy_px),
            "right": (rect.right(), cy_px),
        }
        for name, (hx, hy) in edge_handles.items():
            if math.hypot(px - hx, py - hy) <= _HANDLE_HIT_RADIUS_PX:
                return name
        if math.hypot(px - cx_px, py - cy_px) <= _HANDLE_HIT_RADIUS_PX:
            return "move"
        # Inside the ellipse (not on a handle): also a move-drag.
        rx_px, ry_px = rect.width() / 2.0, rect.height() / 2.0
        if rx_px > 0 and ry_px > 0:
            dx, dy = (px - cx_px) / rx_px, (py - cy_px) / ry_px
            if dx * dx + dy * dy <= 1.0:
                return "move"
        return None

    def _apply_drag(self, handle: str, pos: QPointF) -> None:
        w, h = max(1, self.width()), max(1, self.height())
        fx = pos.x() / w
        fy = pos.y() / h

        if self._mask_type == _LINEAR:
            self._apply_linear_drag(handle, fx, fy)
        else:
            self._apply_radial_drag(handle, fx, fy)

    def _apply_linear_drag(self, handle: str, fx: float, fy: float) -> None:
        if handle == "start":
            x0, y0, x1, y1 = self._clamp_line(fx, fy, self._x1, self._y1)
        elif handle == "end":
            x0, y0, x1, y1 = self._clamp_line(self._x0, self._y0, fx, fy)
        elif handle == "move":
            if self._drag_anchor is None:
                return
            start_fx, start_fy, x0_origin, y0_origin, x1_origin, y1_origin = self._drag_anchor
            dx, dy = fx - start_fx, fy - start_fy
            x0, y0 = x0_origin + dx, y0_origin + dy
            x1, y1 = x1_origin + dx, y1_origin + dy
            # Clamp without re-deriving length (a plain clamp could distort
            # the line's length at the edge, which _clamp_line's own
            # min-length floor would otherwise silently "fix" mid-move) --
            # clamp each point independently, which is sufficient since a
            # move-drag never intends to change length.
            x0, x1 = max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))
            y0, y1 = max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))
        else:
            return

        self._x0, self._y0, self._x1, self._y1 = x0, y0, x1, y1
        self.update()
        self.geometry_changed.emit(self.get_geometry())

    def _apply_radial_drag(self, handle: str, fx: float, fy: float) -> None:
        if handle == "move":
            if self._drag_anchor is None:
                return
            start_fx, start_fy, cx_origin, cy_origin = self._drag_anchor
            dx, dy = fx - start_fx, fy - start_fy
            cx, cy = cx_origin + dx, cy_origin + dy
            rx, ry = self._rx, self._ry
        elif handle == "top":
            cx, cy, rx = self._cx, self._cy, self._rx
            ry = self._cy - fy
        elif handle == "bottom":
            cx, cy, rx = self._cx, self._cy, self._rx
            ry = fy - self._cy
        elif handle == "left":
            cx, cy, ry = self._cx, self._cy, self._ry
            rx = self._cx - fx
        elif handle == "right":
            cx, cy, ry = self._cx, self._cy, self._ry
            rx = fx - self._cx
        else:
            return

        self._cx, self._cy, self._rx, self._ry, self._feather = self._clamp_ellipse(
            cx, cy, rx, ry, self._feather
        )
        self.update()
        self.geometry_changed.emit(self.get_geometry())

    # -- Painting ---------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self._mask_type == _LINEAR:
            self._paint_linear(painter)
        else:
            self._paint_radial(painter)

        painter.end()

    def _paint_linear(self, painter: QPainter) -> None:
        x0, y0, x1, y1 = self._line_px()

        # A few faint guide lines perpendicular to the gradient direction,
        # evenly spaced along it -- a cheap, honest visual touch for the
        # ramp. A plain line+2-handles is an acceptable v1 without this;
        # kept simple (fixed short half-length, not image-size-relative)
        # rather than risking added complexity for a purely decorative
        # detail. See docs/planning/implementation-notes/
        # 2026-10-13-mask-tool-ui.md.
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length > 1e-6:
            ux, uy = dx / length, dy / length
            perp_x, perp_y = -uy, ux
            guide_pen = QPen(QColor(255, 255, 255, 70), 1)
            painter.setPen(guide_pen)
            half = 18.0
            for frac in (0.25, 0.5, 0.75):
                gx = x0 + dx * frac
                gy = y0 + dy * frac
                painter.drawLine(
                    QPointF(gx - perp_x * half, gy - perp_y * half),
                    QPointF(gx + perp_x * half, gy + perp_y * half),
                )

        painter.setPen(QPen(QColor("#0078d4"), 2))
        painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))

        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.setBrush(QColor("#ffffff"))
        half_h = _HANDLE_SIZE_PX / 2.0
        for hx, hy in ((x0, y0), (x1, y1)):
            painter.drawEllipse(QRectF(hx - half_h, hy - half_h, _HANDLE_SIZE_PX, _HANDLE_SIZE_PX))

    def _paint_radial(self, painter: QPainter) -> None:
        rect = self._ellipse_rect_px()
        painter.setPen(QPen(QColor("#0078d4"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect)

        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.setBrush(QColor("#ffffff"))
        half = _HANDLE_SIZE_PX / 2.0
        cx_px, cy_px = rect.center().x(), rect.center().y()
        for hx, hy in (
            (cx_px, rect.top()),
            (cx_px, rect.bottom()),
            (rect.left(), cy_px),
            (rect.right(), cy_px),
        ):
            painter.drawRect(QRectF(hx - half, hy - half, _HANDLE_SIZE_PX, _HANDLE_SIZE_PX))
        # Center handle (move), drawn slightly smaller to distinguish it
        # from the 4 resize handles.
        center_half = half * 0.7
        painter.drawEllipse(QRectF(cx_px - center_half, cy_px - center_half, center_half * 2, center_half * 2))

    # -- Interaction --------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        handle = self._hit_test(pos)
        if handle is None:
            return
        self._active_handle = handle
        w, h = max(1, self.width()), max(1, self.height())
        if handle == "move" and self._mask_type == _LINEAR:
            self._drag_anchor = (
                pos.x() / w,
                pos.y() / h,
                self._x0,
                self._y0,
                self._x1,
                self._y1,
            )
        elif handle == "move" and self._mask_type == _RADIAL:
            self._drag_anchor = (pos.x() / w, pos.y() / h, self._cx, self._cy)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._active_handle is None:
            return
        self._apply_drag(self._active_handle, event.position())
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._active_handle = None
        self._drag_anchor = None
        event.accept()
