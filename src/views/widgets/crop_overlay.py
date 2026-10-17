"""Interactive drag-handle crop overlay.

Meant to be used as a direct child of ``ImageView._image_canvas``. Per
``_ImageCanvas.set_pixmap``'s own contract (it resizes itself to exactly
``pixmap_size * zoom_factor`` and paints the pixmap filling its own
``rect()`` with no internal margin or centering), the canvas widget's own
``(0, 0)``-to-``(width, height)`` rect IS the displayed, zoomed pixmap's
screen rect. A child widget resized to match the canvas's size and
positioned at ``(0, 0)`` therefore has a 1:1 pixel correspondence with the
canvas's local coordinates at ANY zoom level, with no scroll-offset
correction needed -- ``local_x / self.width()`` and
``local_y / self.height()`` are directly the normalized image-fraction
crop coordinates this overlay stores and emits. This is the one property
that makes the whole widget's coordinate math trivial; see
docs/planning/implementation-notes/2026-10-13-crop-tool-ui.md section 4.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

# Handle names, in a fixed, documented order -- 4 corners + 4 edge
# midpoints. Each name says which of x0/y0/x1/y1 a drag on it updates.
_HANDLES = (
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
    "top",
    "bottom",
    "left",
    "right",
)

_HANDLE_SIZE_PX = 9.0
_HANDLE_HIT_RADIUS_PX = 10.0
_MIN_RECT_SIZE_FRACTION = 0.02


class CropOverlay(QWidget):
    """Transparent, mouse-draggable crop rectangle drawn over the canvas.

    State (``self._x0/_y0/_x1/_y1``) is always kept normalized to
    ``[0.0, 1.0]`` with ``x1 > x0`` and ``y1 > y0``.

    Signals:
        rect_changed: Emitted with ``{"x0", "y0", "x1", "y1"}`` continuously
            during a user drag (press/move/move/.../release). Never emitted
            by ``set_rect`` (programmatic set, not a user gesture).
    """

    rect_changed = pyqtSignal(dict)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._x0, self._y0, self._x1, self._y1 = 0.0, 0.0, 1.0, 1.0
        self._locked_aspect: Optional[float] = None
        # Active drag state.
        self._active_handle: Optional[str] = None
        self._drag_anchor: Optional[tuple] = None  # (fixed_x, fixed_y) opposite corner

    # -- Public API -----------------------------------------------------

    def set_rect(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """Programmatically set the crop rectangle. Does NOT emit rect_changed."""
        self._x0, self._y0, self._x1, self._y1 = self._clamp_rect(x0, y0, x1, y1)
        self.update()

    def get_rect(self) -> dict:
        return {"x0": self._x0, "y0": self._y0, "x1": self._x1, "y1": self._y1}

    def set_locked_aspect(self, ratio: Optional[float]) -> None:
        """Set (or clear, with None) the W/H ratio the NEXT drag-resize honors."""
        self._locked_aspect = ratio

    # -- Geometry helpers -------------------------------------------------

    @staticmethod
    def _clamp_rect(x0: float, y0: float, x1: float, y1: float) -> tuple:
        x0, x1 = sorted((max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))))
        y0, y1 = sorted((max(0.0, min(1.0, y0)), max(0.0, min(1.0, y1))))
        if x1 - x0 < _MIN_RECT_SIZE_FRACTION:
            x1 = min(1.0, x0 + _MIN_RECT_SIZE_FRACTION)
            x0 = max(0.0, x1 - _MIN_RECT_SIZE_FRACTION)
        if y1 - y0 < _MIN_RECT_SIZE_FRACTION:
            y1 = min(1.0, y0 + _MIN_RECT_SIZE_FRACTION)
            y0 = max(0.0, y1 - _MIN_RECT_SIZE_FRACTION)
        return x0, y0, x1, y1

    def _rect_px(self) -> QRectF:
        w, h = max(1, self.width()), max(1, self.height())
        return QRectF(self._x0 * w, self._y0 * h, (self._x1 - self._x0) * w, (self._y1 - self._y0) * h)

    def _handle_positions_px(self) -> dict:
        r = self._rect_px()
        mid_x = (r.left() + r.right()) / 2.0
        mid_y = (r.top() + r.bottom()) / 2.0
        return {
            "top_left": (r.left(), r.top()),
            "top_right": (r.right(), r.top()),
            "bottom_left": (r.left(), r.bottom()),
            "bottom_right": (r.right(), r.bottom()),
            "top": (mid_x, r.top()),
            "bottom": (mid_x, r.bottom()),
            "left": (r.left(), mid_y),
            "right": (r.right(), mid_y),
        }

    def _hit_test(self, pos) -> Optional[str]:
        """Return the handle name under ``pos``, ``"move"``, or ``None``.

        ``pos`` is a point-like object with ``.x()``/``.y()`` in this
        widget's local pixel coordinates (a ``QPointF``/``QPoint``).
        """
        px, py = pos.x(), pos.y()
        best_handle = None
        best_distance = _HANDLE_HIT_RADIUS_PX
        for name, (hx, hy) in self._handle_positions_px().items():
            distance = ((hx - px) ** 2 + (hy - py) ** 2) ** 0.5
            if distance <= best_distance:
                best_distance = distance
                best_handle = name
        if best_handle is not None:
            return best_handle
        if self._rect_px().contains(px, py):
            return "move"
        return None

    def _apply_drag(self, handle: str, pos) -> None:
        """Update the crop rect in response to a drag of ``handle`` to ``pos``."""
        w, h = max(1, self.width()), max(1, self.height())
        fx = max(0.0, min(1.0, pos.x() / w))
        fy = max(0.0, min(1.0, pos.y() / h))

        if handle == "move":
            if self._drag_anchor is None:
                return
            start_fx, start_fy, rect_w, rect_h = self._drag_anchor
            dx = fx - start_fx
            dy = fy - start_fy
            x0 = self._drag_rect_origin[0] + dx
            y0 = self._drag_rect_origin[1] + dy
            x0 = max(0.0, min(1.0 - rect_w, x0))
            y0 = max(0.0, min(1.0 - rect_h, y0))
            self._x0, self._y0, self._x1, self._y1 = x0, y0, x0 + rect_w, y0 + rect_h
            self.update()
            self.rect_changed.emit(self.get_rect())
            return

        x0, y0, x1, y1 = self._x0, self._y0, self._x1, self._y1
        if "left" in handle or handle == "left":
            x0 = fx
        if "right" in handle or handle == "right":
            x1 = fx
        if "top" in handle or handle == "top":
            y0 = fy
        if "bottom" in handle or handle == "bottom":
            y1 = fy

        if self._locked_aspect:
            x0, y0, x1, y1 = self._apply_aspect_lock(handle, x0, y0, x1, y1)

        x0, y0, x1, y1 = self._clamp_rect(x0, y0, x1, y1)
        self._x0, self._y0, self._x1, self._y1 = x0, y0, x1, y1
        self.update()
        self.rect_changed.emit(self.get_rect())

    def _apply_aspect_lock(
        self, handle: str, x0: float, y0: float, x1: float, y1: float
    ) -> tuple:
        """Recompute one dimension from ``self._locked_aspect`` (W/H).

        Anchored at the fixed opposite edge/corner: whichever edge the
        handle does NOT touch stays put, and the dimension not directly
        dragged by a corner handle is derived from the other.
        """
        ratio = self._locked_aspect
        w = max(1, self.width())
        h = max(1, self.height())
        width_frac = x1 - x0
        height_frac = y1 - y0
        if handle in ("top", "bottom"):
            # Only height changed; derive width from it, anchored at center-x
            # of the existing rect (simplest sensible behavior for an
            # edge-midpoint handle under a locked aspect).
            new_width_frac = height_frac * ratio * (h / w)
            cx = (x0 + x1) / 2.0
            x0 = cx - new_width_frac / 2.0
            x1 = cx + new_width_frac / 2.0
        elif handle in ("left", "right"):
            new_height_frac = width_frac / ratio * (w / h) if ratio else height_frac
            cy = (y0 + y1) / 2.0
            y0 = cy - new_height_frac / 2.0
            y1 = cy + new_height_frac / 2.0
        else:
            # Corner handle: derive height from the dragged width, anchored
            # at the opposite (fixed) corner.
            new_height_frac = width_frac / ratio * (w / h) if ratio else height_frac
            if "top" in handle:
                y0 = y1 - new_height_frac
            else:
                y1 = y0 + new_height_frac
        # Clamp back into [0, 1] by shrinking from the dragged edge, keeping
        # the fixed opposite edge in place.
        if x0 < 0.0:
            x0 = 0.0
        if x1 > 1.0:
            x1 = 1.0
        if y0 < 0.0:
            y0 = 0.0
        if y1 > 1.0:
            y1 = 1.0
        return x0, y0, x1, y1

    # -- Painting ---------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        full = QRectF(0, 0, self.width(), self.height())
        crop = self._rect_px()

        # Dim only the area outside the crop rect. (Clearing a "hole" with
        # CompositionMode_Clear erased the photo underneath to black: a
        # child widget shares its parent's backing store.)
        outside = QPainterPath()
        outside.setFillRule(Qt.FillRule.OddEvenFill)
        outside.addRect(full)
        outside.addRect(crop)
        painter.fillPath(outside, QColor(0, 0, 0, 150))

        # Border.
        painter.setPen(QPen(QColor("#0078d4"), 2))
        painter.drawRect(crop)

        # Rule-of-thirds grid, inside the crop rect only.
        grid_pen = QPen(QColor(255, 255, 255, 80), 1)
        painter.setPen(grid_pen)
        for i in (1, 2):
            x = crop.left() + crop.width() * i / 3.0
            painter.drawLine(int(x), int(crop.top()), int(x), int(crop.bottom()))
            y = crop.top() + crop.height() * i / 3.0
            painter.drawLine(int(crop.left()), int(y), int(crop.right()), int(y))

        # Handles.
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.setBrush(QColor("#ffffff"))
        half = _HANDLE_SIZE_PX / 2.0
        for hx, hy in self._handle_positions_px().values():
            painter.drawRect(QRectF(hx - half, hy - half, _HANDLE_SIZE_PX, _HANDLE_SIZE_PX))

        painter.end()

    # -- Interaction --------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        handle = self._hit_test(pos)
        if handle is None:
            # Click outside the rect and not on a handle: a simple, documented
            # v1 no-op (does not start a brand-new rectangle). See the crop
            # tool UI implementation note's "non-goals" section.
            return
        self._active_handle = handle
        if handle == "move":
            w, h = max(1, self.width()), max(1, self.height())
            self._drag_anchor = (pos.x() / w, pos.y() / h, self._x1 - self._x0, self._y1 - self._y0)
            self._drag_rect_origin = (self._x0, self._y0)
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
