"""Image view widget for displaying and manipulating images."""

import logging
from time import perf_counter
from typing import Optional, Union

import numpy as np
from PIL import Image
from PyQt6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PyQt6.QtWidgets import (
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.utils.color_pipeline import LinearImage, to_linear
from src.processing.display_frame import DisplayFrame, linear_to_display_rgb
from src.views.widgets.crop_overlay import CropOverlay
from src.views.widgets.healing_overlay import HealingOverlay
from src.views.widgets.mask_overlay import MaskOverlay


logger = logging.getLogger(__name__)


def _elapsed_ms(start: float) -> float:
    return (perf_counter() - start) * 1000.0


class _ImageCanvas(QWidget):
    """Paints the current pixmap at the requested zoom without scaling copies."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self._scaled_size = QSize(1, 1)
        self._placeholder = "No image loaded"
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setStyleSheet("background-color: #1a1a1a; color: #606060;")

    def set_pixmap(self, pixmap: QPixmap, zoom_factor: float) -> None:
        self._pixmap = pixmap
        self._placeholder = ""
        self.set_zoom_factor(zoom_factor)

    def set_zoom_factor(self, zoom_factor: float) -> None:
        if self._pixmap is None:
            self._scaled_size = QSize(1, 1)
        else:
            original_size = self._pixmap.size()
            self._scaled_size = QSize(
                max(1, int(original_size.width() * zoom_factor)),
                max(1, int(original_size.height() * zoom_factor)),
            )
        self.resize(self._scaled_size)
        self.updateGeometry()
        self.update()

    def clear(self) -> None:
        self._pixmap = None
        self._scaled_size = QSize(1, 1)
        self._placeholder = "No image loaded"
        self.resize(self._scaled_size)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return self._scaled_size

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1a1a1a"))
        if self._pixmap is None:
            painter.setPen(Qt.GlobalColor.gray)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder)
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # Scale only the exposed part. Drawing the whole pixmap into a
        # zoomed-in canvas (thousands of px wide) costs hundreds of ms per
        # repaint, which made zooming and panning stutter.
        target = event.rect().intersected(self.rect())
        if target.isEmpty():
            return
        scale_x = self._pixmap.width() / max(1, self.width())
        scale_y = self._pixmap.height() / max(1, self.height())
        source = QRectF(
            target.x() * scale_x,
            target.y() * scale_y,
            target.width() * scale_x,
            target.height() * scale_y,
        )
        painter.drawPixmap(QRectF(target), self._pixmap, source)


class _LoadingOverlay(QWidget):
    """Simple centered spinner overlay for image transitions."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._advance)
        self.hide()

    def set_loading(self, loading: bool) -> None:
        if loading:
            self._angle = 0
            self.show()
            self.raise_()
            self._timer.start()
            self.update()
            return
        self._timer.stop()
        self.hide()

    def _advance(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 55))

        spinner_rect = QRect(0, 0, 44, 44)
        spinner_rect.moveCenter(self.rect().center())
        pen = QPen(QColor("#d8ecff"), 4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(spinner_rect, self._angle * 16, 220 * 16)


class ImageView(QWidget):
    """Widget for displaying images with zoom and pan functionality.
    
    Signals:
        image_loaded: Emitted when an image is successfully loaded
        zoom_changed: Emitted when zoom level changes (zoom_factor)
    """
    
    image_loaded = pyqtSignal()
    zoom_changed = pyqtSignal(float)

    # Zoom constants
    MIN_ZOOM = 0.05
    MAX_ZOOM = 10.0
    ZOOM_STEP = 0.05  # 5% steps for smoother zoom
    ZOOM_WHEEL_FACTOR = 1.1  # 10% per wheel notch

    def __init__(self, parent: Optional[QWidget] = None):
        """Initialize the ImageView widget.
        
        Args:
            parent: Optional parent widget
        """
        super().__init__(parent)
        
        self._pixmap: Optional[QPixmap] = None
        self._display_frame: Optional[DisplayFrame] = None
        # Full-resolution (width, height) the current pixmap stands for.
        # Zoom is relative to this, so 100% means true 1:1 whether the
        # pixmap is a 600 px drag preview or the full image.
        self._source_size: Optional[tuple[int, int]] = None
        self._zoom_factor: float = 1.0
        self._pan_start: Optional[QPoint] = None
        self._is_panning: bool = False
        self._pan_button: Optional[Qt.MouseButton] = None
        self._loading_overlay: Optional[_LoadingOverlay] = None
        self._crop_overlay: Optional[CropOverlay] = None
        self._mask_overlay: Optional[MaskOverlay] = None
        self._healing_overlay: Optional[HealingOverlay] = None

        self._setup_ui()

    def _setup_ui(self):
        """Set up the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Scroll area for panning
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(False)
        self._scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll_area.setStyleSheet("background-color: #1a1a1a; border: none;")
        
        self._image_canvas = _ImageCanvas()
        self._scroll_area.setWidget(self._image_canvas)
        layout.addWidget(self._scroll_area)
        self._loading_overlay = _LoadingOverlay(self)
        self._loading_overlay.resize(self.size())
        
        # Set mouse tracking for panning
        self._scroll_area.viewport().installEventFilter(self)

    def set_image(
        self,
        image: Union[LinearImage, Image.Image],
        emit_loaded: bool = True,
        preserve_view_scale: bool = False,
    ) -> None:
        """Set the image to display.

        Accepts either a ``LinearImage`` (canonical pipeline format) or
        a ``PIL.Image`` (transitional convenience for callers that have
        not yet been migrated). Future code should pass arrays directly.
        """
        arr = to_linear(image)
        self._set_array(arr, preserve_view_scale=preserve_view_scale)
        if emit_loaded:
            self.image_loaded.emit()

    def clear(self) -> None:
        """Reset to the "No image loaded" placeholder state -- the same
        empty state ``_ImageCanvas`` starts in before ``set_image``/
        ``set_display_frame`` has ever been called (see
        ``ImageController.clear_image``, used after the currently-open
        image's library entry is removed or deleted from disk)."""
        self._pixmap = None
        self._display_frame = None
        self._source_size = None
        self._image_canvas.clear()

    def set_display_frame(
        self,
        frame: DisplayFrame,
        emit_loaded: bool = False,
        preserve_view_scale: bool = True,
    ) -> None:
        """Present a worker-produced display frame without float conversion."""
        total_start = perf_counter()
        if not preserve_view_scale:
            self._zoom_factor = 1.0
            self._scroll_area.horizontalScrollBar().setValue(0)
            self._scroll_area.verticalScrollBar().setValue(0)

        old_w = old_h = 0
        if preserve_view_scale and self._pixmap is not None:
            old_w, old_h = self._base_size()

        qimage_start = perf_counter()
        qimage = frame.to_qimage()
        qimage_ms = _elapsed_ms(qimage_start)

        pixmap_start = perf_counter()
        self._display_frame = frame
        self._pixmap = QPixmap.fromImage(qimage)
        self._source_size = frame.source_size or (
            self._pixmap.width(), self._pixmap.height()
        )
        pixmap_ms = _elapsed_ms(pixmap_start)

        self._preserve_scale_after_pixmap_swap(
            old_w=old_w,
            old_h=old_h,
            preserve_view_scale=preserve_view_scale,
        )

        update_start = perf_counter()
        self._update_display()
        update_ms = _elapsed_ms(update_start)
        logger.info(
            "PERF view.set_display_frame request=%s tier=%s shape=%s "
            "preserve_scale=%s qimage_wrap_ms=%.2f pixmap_ms=%.2f "
            "update_display_ms=%.2f total_ms=%.2f",
            frame.request_id,
            frame.tier,
            frame.shape,
            preserve_view_scale,
            qimage_ms,
            pixmap_ms,
            update_ms,
            _elapsed_ms(total_start),
        )

        if emit_loaded:
            self.image_loaded.emit()

    def _set_array(self, arr: LinearImage, preserve_view_scale: bool = False) -> None:
        """Build a QPixmap from a ``LinearImage`` and update the display.

        Uses the same LUT-based ``linear_to_display_rgb`` encode the
        background processing worker already uses for every adjustment
        preview, instead of the exact but per-pixel-``power()``
        ``linear_to_qimage``. This path runs synchronously on the UI
        thread (there is no worker hop for the initial decode or a raw
        ``set_image`` call), so on a full-resolution image it was a
        measurable synchronous hitch on every image load/switch -- the
        intermittent "micro freeze" between images. The LUT trades
        imperceptible quantization error (already accepted for every
        other on-screen redraw in the app) for an O(1)-per-pixel lookup.
        """
        total_start = perf_counter()
        if not preserve_view_scale:
            self._zoom_factor = 1.0
            self._scroll_area.horizontalScrollBar().setValue(0)
            self._scroll_area.verticalScrollBar().setValue(0)

        old_w = old_h = 0
        if preserve_view_scale and self._pixmap is not None:
            old_w, old_h = self._base_size()

        qimage_start = perf_counter()
        rgb = np.ascontiguousarray(linear_to_display_rgb(arr))
        height, width, _ = rgb.shape
        qimage = QImage(
            rgb.data,
            width,
            height,
            rgb.strides[0],
            QImage.Format.Format_RGB888,
        ).copy()
        qimage_ms = _elapsed_ms(qimage_start)
        pixmap_start = perf_counter()
        self._display_frame = None
        self._pixmap = QPixmap.fromImage(qimage)
        self._source_size = (self._pixmap.width(), self._pixmap.height())
        pixmap_ms = _elapsed_ms(pixmap_start)

        self._preserve_scale_after_pixmap_swap(
            old_w=old_w,
            old_h=old_h,
            preserve_view_scale=preserve_view_scale,
        )
        update_start = perf_counter()
        self._update_display()
        update_ms = _elapsed_ms(update_start)
        logger.info(
            "PERF view.set_array shape=%s preserve_scale=%s qimage_ms=%.2f "
            "pixmap_ms=%.2f update_display_ms=%.2f total_ms=%.2f",
            arr.shape,
            preserve_view_scale,
            qimage_ms,
            pixmap_ms,
            update_ms,
            _elapsed_ms(total_start),
        )

    def clear_image(self) -> None:
        """Clear the currently displayed image."""
        self._pixmap = None
        self._display_frame = None
        self._source_size = None
        self._zoom_factor = 1.0
        self._scroll_area.horizontalScrollBar().setValue(0)
        self._scroll_area.verticalScrollBar().setValue(0)
        self._image_canvas.clear()

    def set_cached_preview_image(
        self,
        image: QImage,
        zoom_factor: Optional[float] = None,
    ) -> None:
        """Show a cached preview image immediately during navigation."""
        self._display_frame = None
        self._pixmap = QPixmap.fromImage(image)
        self._source_size = None
        self._scroll_area.horizontalScrollBar().setValue(0)
        self._scroll_area.verticalScrollBar().setValue(0)
        if zoom_factor is None:
            self._zoom_factor = 1.0
        else:
            self._zoom_factor = max(self.MIN_ZOOM, min(self.MAX_ZOOM, zoom_factor))
        self._update_display()

    def has_image(self) -> bool:
        """Check if an image is currently loaded.

        Returns:
            True if an image is loaded
        """
        return self._pixmap is not None

    def get_pixmap_size(self) -> Optional[tuple[int, int]]:
        """Return the displayed pixmap's ``(width, height)``, or None."""
        if self._pixmap is None:
            return None
        return self._pixmap.width(), self._pixmap.height()

    def get_display_image(self) -> Optional[QImage]:
        """The image currently on screen (before zoom), or None."""
        if self._pixmap is None:
            return None
        return self._pixmap.toImage()

    def _base_size(self) -> tuple[int, int]:
        """Full-resolution size zoom is measured against."""
        if self._source_size is not None:
            return self._source_size
        if self._pixmap is None:
            return (0, 0)
        return self._pixmap.width(), self._pixmap.height()

    def _canvas_scale(self) -> float:
        """Canvas pixels per pixmap pixel at the current zoom."""
        if self._pixmap is None or self._pixmap.width() == 0:
            return self._zoom_factor
        return self._zoom_factor * self._base_size()[0] / self._pixmap.width()

    def display_scale(self) -> float:
        """Physical screen pixels per pixmap pixel. Above ~1 the pixmap is
        being magnified and a higher-resolution frame would add detail."""
        return self._canvas_scale() * self.devicePixelRatioF()

    def set_loading(self, loading: bool) -> None:
        """Show or hide the transition loading overlay."""
        if self._loading_overlay is None:
            return
        self._loading_overlay.set_loading(loading)

    def is_loading(self) -> bool:
        """Whether the loading overlay is currently visible."""
        return bool(self._loading_overlay is not None and self._loading_overlay.isVisible())

    def get_zoom_factor(self) -> float:
        """Get the current zoom factor.
        
        Returns:
            Current zoom factor (1.0 = 100%)
        """
        return self._zoom_factor

    def set_zoom_factor(self, factor: float) -> None:
        """Set the zoom factor.
        
        Args:
            factor: Zoom factor (1.0 = 100%)
        """
        factor = max(self.MIN_ZOOM, min(self.MAX_ZOOM, factor))
        if factor != self._zoom_factor:
            # Keep the image point under the viewport centre in place (the
            # wheel handler re-anchors on the cursor afterwards). Without
            # this, 100% jumped to the image's top-left corner.
            center = self._viewport_center_in_image()
            self._zoom_factor = factor
            self._update_display()
            if center is not None:
                viewport = self._scroll_area.viewport()
                self._scroll_area.horizontalScrollBar().setValue(
                    int(round(center[0] * factor - viewport.width() / 2))
                )
                self._scroll_area.verticalScrollBar().setValue(
                    int(round(center[1] * factor - viewport.height() / 2))
                )
            self.zoom_changed.emit(self._zoom_factor)

    def _viewport_center_in_image(self) -> Optional[tuple[float, float]]:
        """Full-resolution image coordinates under the viewport centre."""
        if self._pixmap is None or self._zoom_factor <= 0:
            return None
        viewport = self._scroll_area.viewport()
        canvas = self._image_canvas
        base_w, base_h = self._base_size()
        if canvas.width() <= viewport.width():
            cx = base_w / 2.0
        else:
            h_bar = self._scroll_area.horizontalScrollBar()
            cx = (h_bar.value() + viewport.width() / 2.0) / self._zoom_factor
        if canvas.height() <= viewport.height():
            cy = base_h / 2.0
        else:
            v_bar = self._scroll_area.verticalScrollBar()
            cy = (v_bar.value() + viewport.height() / 2.0) / self._zoom_factor
        return cx, cy

    def zoom_in(self) -> None:
        """Zoom in by one step."""
        self.set_zoom_factor(self._zoom_factor * self.ZOOM_WHEEL_FACTOR)

    def zoom_out(self) -> None:
        """Zoom out by one step."""
        self.set_zoom_factor(self._zoom_factor / self.ZOOM_WHEEL_FACTOR)

    def fit_to_window(self) -> None:
        """Fit the image to the window size."""
        if not self.has_image():
            return
        
        viewport_size = self._scroll_area.viewport().size()
        base_w, base_h = self._base_size()

        # Calculate zoom to fit
        width_ratio = viewport_size.width() / base_w
        height_ratio = viewport_size.height() / base_h
        
        # Use the smaller ratio to ensure the image fits
        self.set_zoom_factor(min(width_ratio, height_ratio) * 0.95)

    def view_100_percent(self) -> None:
        """Set zoom to 100% (actual size)."""
        self.set_zoom_factor(1.0)

    def _update_display(self) -> None:
        """Update the displayed image based on current zoom level."""
        if not self.has_image():
            return
        self._image_canvas.set_pixmap(self._pixmap, self._canvas_scale())
        if self._crop_overlay is not None and self._crop_overlay.isVisible():
            self._crop_overlay.resize(self._image_canvas.size())
        if self._mask_overlay is not None and self._mask_overlay.isVisible():
            self._mask_overlay.resize(self._image_canvas.size())
        if self._healing_overlay is not None and self._healing_overlay.isVisible():
            self._healing_overlay.resize(self._image_canvas.size())

    # -- Crop mode --------------------------------------------------------

    def enter_crop_mode(self, initial_rect: dict) -> None:
        """Show the interactive crop overlay over the canvas.

        The caller (``MainWindow``) is responsible for having already
        displayed the full, uncropped image (via
        ``ImageController.get_export_image(apply_crop=False)``) before
        calling this -- ``ImageView`` itself has no opinion about
        adjustment state.
        """
        if self._crop_overlay is None:
            self._crop_overlay = CropOverlay(self._image_canvas)
        self._crop_overlay.resize(self._image_canvas.size())
        self._crop_overlay.move(0, 0)
        self._crop_overlay.set_rect(
            initial_rect.get("x0", 0.0),
            initial_rect.get("y0", 0.0),
            initial_rect.get("x1", 1.0),
            initial_rect.get("y1", 1.0),
        )
        self._crop_overlay.show()
        self._crop_overlay.raise_()

    def exit_crop_mode(self) -> None:
        """Hide the crop overlay (kept alive, not destroyed, for reuse)."""
        if self._crop_overlay is not None:
            self._crop_overlay.hide()

    def is_in_crop_mode(self) -> bool:
        return self._crop_overlay is not None and self._crop_overlay.isVisible()

    def get_crop_overlay(self) -> Optional[CropOverlay]:
        return self._crop_overlay

    # -- Mask mode --------------------------------------------------------

    def enter_mask_mode(self, initial_type: str, initial_geometry: dict) -> None:
        """Show the interactive mask overlay over the canvas.

        Mirrors ``enter_crop_mode`` exactly. Unlike crop mode, the caller
        does NOT need to have swapped in an "unmasked" display image
        first -- the canvas keeps showing whatever it was already
        showing (the normal, fully-adjusted image); only the overlay
        itself is new. See docs/planning/implementation-notes/
        2026-10-13-mask-tool-ui.md section 3.5 for why.
        """
        if self._mask_overlay is None:
            self._mask_overlay = MaskOverlay(self._image_canvas)
        self._mask_overlay.resize(self._image_canvas.size())
        self._mask_overlay.move(0, 0)
        self._mask_overlay.set_mask_type(initial_type)
        self._mask_overlay.set_invert(bool(initial_geometry.get("invert", False)))
        if initial_type == "radial":
            self._mask_overlay.set_radial_geometry(
                initial_geometry.get("cx", 0.5),
                initial_geometry.get("cy", 0.5),
                initial_geometry.get("rx", 0.25),
                initial_geometry.get("ry", 0.25),
                initial_geometry.get("feather", 0.5),
            )
        else:
            self._mask_overlay.set_linear_geometry(
                initial_geometry.get("x0", 0.3),
                initial_geometry.get("y0", 0.5),
                initial_geometry.get("x1", 0.7),
                initial_geometry.get("y1", 0.5),
            )
        self._mask_overlay.show()
        self._mask_overlay.raise_()

    def exit_mask_mode(self) -> None:
        """Hide the mask overlay (kept alive, not destroyed, for reuse)."""
        if self._mask_overlay is not None:
            self._mask_overlay.hide()

    def is_in_mask_mode(self) -> bool:
        return self._mask_overlay is not None and self._mask_overlay.isVisible()

    def get_mask_overlay(self) -> Optional[MaskOverlay]:
        return self._mask_overlay

    # -- Healing mode -------------------------------------------------------

    def enter_healing_mode(self, initial_spots: list) -> None:
        """Show the interactive healing overlay over the canvas.

        Mirrors ``enter_crop_mode``/``enter_mask_mode`` exactly. Like mask
        mode (and unlike crop mode), the caller does NOT need to have
        swapped in any different display image first -- the canvas keeps
        showing whatever it was already showing; only the overlay itself
        is new.
        """
        if self._healing_overlay is None:
            self._healing_overlay = HealingOverlay(self._image_canvas)
        self._healing_overlay.resize(self._image_canvas.size())
        self._healing_overlay.move(0, 0)
        self._healing_overlay.set_spots(initial_spots)
        self._healing_overlay.show()
        self._healing_overlay.raise_()

    def exit_healing_mode(self) -> None:
        """Hide the healing overlay (kept alive, not destroyed, for reuse)."""
        if self._healing_overlay is not None:
            self._healing_overlay.hide()

    def is_in_healing_mode(self) -> bool:
        return self._healing_overlay is not None and self._healing_overlay.isVisible()

    def get_healing_overlay(self) -> Optional[HealingOverlay]:
        return self._healing_overlay

    def _preserve_scale_after_pixmap_swap(
        self,
        old_w: int,
        old_h: int,
        preserve_view_scale: bool,
    ) -> None:
        """Keep visual scale stable when swapping proxy/full frames."""
        if preserve_view_scale and old_w > 0 and old_h > 0 and self._pixmap is not None:
            new_w = self._base_size()[0]
            if new_w > 0 and new_w != old_w:
                self._zoom_factor *= old_w / float(new_w)
                self._zoom_factor = max(
                    self.MIN_ZOOM, min(self.MAX_ZOOM, self._zoom_factor)
                )


    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handle mouse wheel events for cursor-anchored zooming."""
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and self.has_image():
            delta = event.angleDelta().y()
            if delta == 0:
                return

            old_zoom = self._zoom_factor
            if delta > 0:
                new_zoom = old_zoom * self.ZOOM_WHEEL_FACTOR
            else:
                new_zoom = old_zoom / self.ZOOM_WHEEL_FACTOR
            new_zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, new_zoom))
            if new_zoom == old_zoom:
                return

            viewport = self._scroll_area.viewport()
            pos = viewport.mapFromGlobal(event.globalPosition().toPoint())
            h_bar = self._scroll_area.horizontalScrollBar()
            v_bar = self._scroll_area.verticalScrollBar()

            img_x = (h_bar.value() + pos.x()) / old_zoom
            img_y = (v_bar.value() + pos.y()) / old_zoom

            self.set_zoom_factor(new_zoom)

            h_bar.setValue(int(round(img_x * new_zoom - pos.x())))
            v_bar.setValue(int(round(img_y * new_zoom - pos.y())))
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse press events for panning.
        
        Args:
            event: Mouse event
        """
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._is_panning = True
            self._pan_start = event.pos()
            self._pan_button = event.button()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Handle mouse move events for panning.
        
        Args:
            event: Mouse event
        """
        if self._is_panning and self._pan_start:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            
            # Scroll the view
            h_bar = self._scroll_area.horizontalScrollBar()
            v_bar = self._scroll_area.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Handle mouse release events.
        
        Args:
            event: Mouse event
        """
        if self._is_panning and event.button() == self._pan_button:
            self._is_panning = False
            self._pan_start = None
            self._pan_button = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def eventFilter(self, watched, event):
        """Handle viewport mouse events for panning and zoom behavior."""
        if watched == self._scroll_area.viewport():
            et = event.type()
            if et == QEvent.Type.Wheel:
                if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                    self.wheelEvent(event)
                    return True
                return False
            if et == QEvent.Type.MouseButtonPress:
                self.mousePressEvent(event)
                return True
            if et == QEvent.Type.MouseMove:
                self.mouseMoveEvent(event)
                return True
            if et == QEvent.Type.MouseButtonRelease:
                self.mouseReleaseEvent(event)
                return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._loading_overlay is not None:
            self._loading_overlay.resize(self.size())
