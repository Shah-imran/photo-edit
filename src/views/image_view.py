"""Image view widget for displaying and manipulating images."""

from typing import Optional, Union

import numpy as np
from PIL import Image
from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QMouseEvent, QPainter, QPixmap, QWheelEvent
from PyQt6.QtWidgets import (
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.utils.color_pipeline import LinearImage, linear_to_qimage, to_linear


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
        self._zoom_factor: float = 1.0
        self._pan_start: Optional[QPoint] = None
        self._is_panning: bool = False
        
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
        
        # Image label
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._image_label.setStyleSheet("background-color: #1a1a1a;")
        
        self._scroll_area.setWidget(self._image_label)
        layout.addWidget(self._scroll_area)
        
        # Set mouse tracking for panning
        self._scroll_area.viewport().installEventFilter(self)

    def set_image(
        self,
        image: Union[LinearImage, Image.Image],
        emit_loaded: bool = True,
    ) -> None:
        """Set the image to display.

        Accepts either a ``LinearImage`` (canonical pipeline format) or
        a ``PIL.Image`` (transitional convenience for callers that have
        not yet been migrated). Future code should pass arrays directly.
        """
        arr = to_linear(image)
        self._set_array(arr)
        if emit_loaded:
            self.image_loaded.emit()

    def _set_array(self, arr: LinearImage) -> None:
        """Build a QPixmap from a ``LinearImage`` and update the display."""
        qimage = linear_to_qimage(arr)
        self._pixmap = QPixmap.fromImage(qimage)
        self._update_display()

    def clear_image(self) -> None:
        """Clear the currently displayed image."""
        self._pixmap = None
        self._image_label.clear()
        self._image_label.setText("No image loaded")
        self._image_label.setStyleSheet("background-color: #1a1a1a; color: #606060;")

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
        
        # Scale the pixmap
        original_size = self._pixmap.size()
        scaled_width = int(original_size.width() * self._zoom_factor)
        scaled_height = int(original_size.height() * self._zoom_factor)
        scaled_size = QSize(scaled_width, scaled_height)
        
        scaled_pixmap = self._pixmap.scaled(
            scaled_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        self._image_label.setPixmap(scaled_pixmap)
        self._image_label.resize(scaled_pixmap.size())


    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handle mouse wheel events for zooming.
        
        Args:
            event: Wheel event
        """
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            # Zoom with Ctrl+Wheel
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse press events for panning.
        
        Args:
            event: Mouse event
        """
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = True
            self._pan_start = event.pos()
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
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = False
            self._pan_start = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)
