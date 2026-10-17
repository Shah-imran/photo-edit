"""Interactive click-and-drag healing-spot placement overlay.

Meant to be used as a direct child of ``ImageView._image_canvas``, exactly
like :class:`~src.views.widgets.crop_overlay.CropOverlay` and
:class:`~src.views.widgets.mask_overlay.MaskOverlay` (this widget's direct
architectural templates -- see docs/planning/implementation-notes/
2026-10-13-healing-tool-ui.md). Per ``_ImageCanvas.set_pixmap``'s own
contract, the canvas widget's own ``(0, 0)``-to-``(width, height)`` rect IS
the displayed, zoomed pixmap's screen rect at any zoom level. A child
widget resized to match the canvas and positioned at ``(0, 0)`` therefore
has a 1:1 pixel correspondence with the canvas's local coordinates, with no
scroll-offset correction needed.

**v1 scope, deliberately limited** (see the implementation note's
non-goals in full):

- Click-and-drag placement ONLY. Press sets a spot's destination center;
  drag grows/shrinks its radius live; release commits it. There is NO way
  to click an already-placed spot afterward to select, move, resize, or
  edit it individually -- only ``remove_last``/``clear_all`` correct
  mistakes.
- The source point is always auto-computed (a fixed offset from the
  destination, flipped/clamped near an edge -- see
  ``_compute_source_offset``), never separately draggable.
- The toolbar's pending mode/feather/opacity are baked into each spot AT
  THE MOMENT it is placed (see ``set_pending_mode``/``set_pending_feather``/
  ``set_pending_opacity``), not referenced live from a shared value, so
  changing the toolbar's controls after a spot is placed never
  retroactively changes that spot.
"""

from __future__ import annotations

import math
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

_HEAL_MODES = ("heal", "clone")

_MIN_RADIUS_FRACTION = 0.01
_MAX_RADIUS_FRACTION = 0.5
_DEFAULT_RADIUS_FRACTION = 0.05

# How far (in units of the spot's own radius) the auto-computed source
# point is offset from the destination, before the left/right-fallback and
# clamp logic below is applied. See `_compute_source_offset`.
_SOURCE_OFFSET_RADIUS_MULTIPLE = 2.0


class HealingOverlay(QWidget):
    """Transparent, click-and-drag heal-spot placement overlay.

    State: ``self._spots`` (the full in-progress, not-yet-applied list of
    complete spot dicts, each shaped exactly per ``HealingProcessor``'s own
    contract -- ``dst_x``/``dst_y``/``src_x``/``src_y``/``radius``/
    ``feather``/``opacity``/``mode``), plus ``self._dragging_spot`` (the
    spot currently being placed, with a live radius, or ``None``).

    Signals:
        spots_changed: Emitted with the full in-progress list whenever it
            changes -- a new spot placed (drag release), ``remove_last``,
            or ``clear_all``. Never emitted by ``set_spots`` (programmatic,
            not a user gesture).
    """

    spots_changed = pyqtSignal(list)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self._spots: list = []
        self._dragging_spot: Optional[dict] = None
        self._press_pos: Optional[tuple] = None  # (fx, fy) at mouse-press

        # The toolbar's CURRENT pending values -- baked into the NEXT spot
        # placed, never applied retroactively to an already-placed spot.
        self._pending_mode = "heal"
        self._pending_feather = 0.3
        self._pending_opacity = 1.0

    # -- Public API -----------------------------------------------------

    def set_spots(self, spots: list) -> None:
        """Programmatic bulk-set (e.g. entering heal mode with spots
        already committed from a prior session). Does NOT emit
        ``spots_changed``."""
        self._spots = [dict(spot) for spot in (spots or []) if isinstance(spot, dict)]
        self.update()

    def get_spots(self) -> list:
        """Return the full in-progress list (each spot a complete,
        ``HealingProcessor``-shaped dict)."""
        return [dict(spot) for spot in self._spots]

    def remove_last(self) -> None:
        """Pop the most recently placed spot. No-op if empty."""
        if not self._spots:
            return
        self._spots.pop()
        self.update()
        self.spots_changed.emit(self.get_spots())

    def clear_all(self) -> None:
        """Empty the in-progress list."""
        if not self._spots:
            return
        self._spots = []
        self.update()
        self.spots_changed.emit(self.get_spots())

    def set_pending_mode(self, mode: str) -> None:
        if mode in _HEAL_MODES:
            self._pending_mode = mode

    def set_pending_feather(self, feather: float) -> None:
        self._pending_feather = max(0.0, min(1.0, feather))

    def set_pending_opacity(self, opacity: float) -> None:
        self._pending_opacity = max(0.0, min(1.0, opacity))

    # -- Geometry helpers -------------------------------------------------

    @staticmethod
    def _compute_source_offset(dst_x: float, dst_y: float, radius: float) -> tuple:
        """Return ``(src_x, src_y)`` for a spot at ``(dst_x, dst_y)`` with
        ``radius`` (all normalized fractions).

        Fixed rule: offset directly to the right by ``2 * radius``, unless
        that would push the source circle (even partially) outside
        ``[0, 1]``, in which case flip to directly the LEFT by the same
        amount. If a destination spot is wide enough that NEITHER fits
        (wider than half the image), clamp the offset to whatever keeps
        the source maximally in-bounds, rather than producing a source
        outside ``[0, 1]``.
        """
        offset = _SOURCE_OFFSET_RADIUS_MULTIPLE * radius
        right_x = dst_x + offset
        left_x = dst_x - offset
        if right_x + radius <= 1.0:
            return right_x, dst_y
        if left_x - radius >= 0.0:
            return left_x, dst_y
        # Neither fits cleanly (a destination spot wider than half the
        # image): clamp to whichever side has more room, maximally
        # in-bounds.
        room_right = 1.0 - (dst_x + radius)
        room_left = (dst_x - radius) - 0.0
        if room_right >= room_left:
            src_x = max(0.0 + radius, min(1.0 - radius, dst_x + max(0.0, room_right)))
        else:
            src_x = max(0.0 + radius, min(1.0 - radius, dst_x - max(0.0, room_left)))
        # If the image is narrower than 2*radius (radius > 0.5), there is
        # no in-bounds placement with room for the full circle on either
        # side; fall back to the image center clamped into [0, 1] so the
        # center itself is always valid, even if the circle's edge isn't.
        src_x = max(0.0, min(1.0, src_x))
        return src_x, dst_y

    def _spot_radius_px(self, spot: dict) -> float:
        w, h = max(1, self.width()), max(1, self.height())
        # A single `radius` value scaled by the SAME zoom factor in both
        # axes is already correct without Mask's own separate rx/ry
        # per-axis correction -- see module docstring / implementation
        # note section 3 for the full reasoning. We still render using the
        # min(w, h) scale to mirror HealingProcessor's own
        # `radius * min(width, height)` pixel-space convention exactly.
        return spot.get("radius", _DEFAULT_RADIUS_FRACTION) * min(w, h)

    def _to_px(self, fx: float, fy: float) -> tuple:
        w, h = max(1, self.width()), max(1, self.height())
        return fx * w, fy * h

    # -- Interaction --------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        w, h = max(1, self.width()), max(1, self.height())
        fx = max(0.0, min(1.0, pos.x() / w))
        fy = max(0.0, min(1.0, pos.y() / h))
        self._press_pos = (fx, fy)
        self._dragging_spot = {
            "dst_x": fx,
            "dst_y": fy,
            "src_x": fx,
            "src_y": fy,
            "radius": _DEFAULT_RADIUS_FRACTION,
            "feather": self._pending_feather,
            "opacity": self._pending_opacity,
            "mode": self._pending_mode,
        }
        self.update()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._dragging_spot is None or self._press_pos is None:
            return
        pos = event.position()
        w, h = max(1, self.width()), max(1, self.height())
        fx = pos.x() / w
        fy = pos.y() / h
        press_fx, press_fy = self._press_pos
        radius = math.hypot(fx - press_fx, fy - press_fy)
        radius = max(_MIN_RADIUS_FRACTION, min(_MAX_RADIUS_FRACTION, radius))
        self._dragging_spot["radius"] = radius
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._dragging_spot is None:
            return
        spot = self._dragging_spot
        dst_x, dst_y, radius = spot["dst_x"], spot["dst_y"], spot["radius"]
        src_x, src_y = self._compute_source_offset(dst_x, dst_y, radius)
        spot["src_x"], spot["src_y"] = src_x, src_y
        self._spots.append(spot)
        self._dragging_spot = None
        self._press_pos = None
        self.update()
        self.spots_changed.emit(self.get_spots())
        event.accept()

    # -- Painting ---------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        for spot in self._spots:
            self._paint_spot(painter, spot, dragging=False)
        if self._dragging_spot is not None:
            self._paint_spot(painter, self._dragging_spot, dragging=True)

        painter.end()

    def _paint_spot(self, painter: QPainter, spot: dict, dragging: bool) -> None:
        dst_px = self._to_px(spot.get("dst_x", 0.5), spot.get("dst_y", 0.5))
        radius_px = self._spot_radius_px(spot)
        mode = spot.get("mode", "heal")
        color = QColor("#0078d4") if mode == "heal" else QColor("#d48a00")

        pen = QPen(color, 2)
        if dragging:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(
            QRectF(dst_px[0] - radius_px, dst_px[1] - radius_px, radius_px * 2, radius_px * 2)
        )

        # Source marker + connecting line -- only meaningful once a final
        # src has been computed (release). While still dragging, the
        # in-progress dict's src_x/src_y are just the press point, which
        # isn't the real auto-computed source yet, so skip drawing it to
        # avoid showing a misleading marker.
        if not dragging:
            src_px = self._to_px(spot.get("src_x", 0.5), spot.get("src_y", 0.5))
            small_pen = QPen(color, 1)
            painter.setPen(small_pen)
            small_radius = max(2.0, radius_px * 0.5)
            painter.drawEllipse(
                QRectF(
                    src_px[0] - small_radius,
                    src_px[1] - small_radius,
                    small_radius * 2,
                    small_radius * 2,
                )
            )
            painter.drawLine(QPointF(*dst_px), QPointF(*src_px))
