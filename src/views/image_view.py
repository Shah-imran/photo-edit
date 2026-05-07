"""Image view widget for displaying and manipulating images."""

import logging
from time import perf_counter
from typing import Optional, Union

import numpy as np
from PIL import Image
from PyQt6.QtCore import QEvent, QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPixmap, QWheelEvent
from PyQt6.QtWidgets import (
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.utils.color_pipeline import LinearImage, linear_to_qimage, to_linear
from src.processing.display_frame import DisplayFrame


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
        painter.drawPixmap(self.rect(), self._pixmap, self._pixmap.rect())


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
        self._zoom_factor: float = 1.0
        self._pan_start: Optional[QPoint] = None
        self._is_panning: bool = False
        self._pan_button: Optional[Qt.MouseButton] = None
        
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
            old_size = self._pixmap.size()
            old_w, old_h = old_size.width(), old_size.height()

        qimage_start = perf_counter()
        qimage = frame.to_qimage()
        qimage_ms = _elapsed_ms(qimage_start)

        pixmap_start = perf_counter()
        self._display_frame = frame
        self._pixmap = QPixmap.fromImage(qimage)
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
        """Build a QPixmap from a ``LinearImage`` and update the display."""
        total_start = perf_counter()
        if not preserve_view_scale:
            self._zoom_factor = 1.0
            self._scroll_area.horizontalScrollBar().setValue(0)
            self._scroll_area.verticalScrollBar().setValue(0)

        old_w = old_h = 0
        if preserve_view_scale and self._pixmap is not None:
            old_size = self._pixmap.size()
            old_w, old_h = old_size.width(), old_size.height()

        qimage_start = perf_counter()
        qimage = linear_to_qimage(arr)
        qimage_ms = _elapsed_ms(qimage_start)
        pixmap_start = perf_counter()
        self._display_frame = None
        self._pixmap = QPixmap.fromImage(qimage)
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
        self._zoom_factor = 1.0
        self._scroll_area.horizontalScrollBar().setValue(0)
        self._scroll_area.verticalScrollBar().setValue(0)
        self._image_canvas.clear()

    def has_image(self) -> bool:
        """Check if an image is currently loaded.
        
        Returns:
            True if an image is loaded
        """
        return self._pixmap is not None

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
            self._zoom_factor = factor
            self._update_display()
            self.zoom_changed.emit(self._zoom_factor)

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
        pixmap_size = self._pixmap.size()
        
        # Calculate zoom to fit
        width_ratio = viewport_size.width() / pixmap_size.width()
        height_ratio = viewport_size.height() / pixmap_size.height()
        
        # Use the smaller ratio to ensure the image fits
        self.set_zoom_factor(min(width_ratio, height_ratio) * 0.95)

    def view_100_percent(self) -> None:
        """Set zoom to 100% (actual size)."""
        self.set_zoom_factor(1.0)

    def _update_display(self) -> None:
        """Update the displayed image based on current zoom level."""
        if not self.has_image():
            return
        self._image_canvas.set_pixmap(self._pixmap, self._zoom_factor)

    def _preserve_scale_after_pixmap_swap(
        self,
        old_w: int,
        old_h: int,
        preserve_view_scale: bool,
    ) -> None:
        """Keep visual scale stable when swapping proxy/full frames."""
        if preserve_view_scale and old_w > 0 and old_h > 0 and self._pixmap is not None:
            new_size = self._pixmap.size()
            new_w = new_size.width()
            if new_w > 0:
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
