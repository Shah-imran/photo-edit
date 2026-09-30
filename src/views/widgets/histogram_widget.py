"""Compact RGB histogram for the Develop panel."""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget


class HistogramWidget(QWidget):
    """Draw overlaid red, green, blue, and luminance distributions."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("histogramWidget")
        self.setMinimumHeight(112)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._channels: list[np.ndarray] = []
        self.setToolTip("RGB histogram of the current edited image")

    def sizeHint(self) -> QSize:
        return QSize(300, 128)

    def set_image(self, image: np.ndarray | None) -> None:
        if image is None or not isinstance(image, np.ndarray) or image.ndim != 3:
            self._channels = []
            self.update()
            return
        sample = np.clip(image[::4, ::4, :3], 0.0, 1.0)
        channels = []
        for index in range(3):
            counts, _ = np.histogram(sample[..., index], bins=128, range=(0.0, 1.0))
            channels.append(counts.astype(np.float32))
        self._channels = channels
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#171a1e"))
        painter.setPen(QPen(QColor("#30363d"), 1))
        for fraction in (.25, .5, .75):
            x = int(self.width() * fraction)
            painter.drawLine(x, 0, x, self.height())
        if not self._channels:
            painter.setPen(QColor("#69717b"))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "No image")
            painter.end()
            return

        peak = max(float(np.percentile(channel, 98)) for channel in self._channels)
        peak = max(1.0, peak)
        colors = (QColor(255, 72, 72, 125), QColor(70, 222, 105, 125), QColor(72, 130, 255, 125))
        for channel, color in zip(self._channels, colors):
            path = QPainterPath()
            path.moveTo(0, self.height())
            for index, value in enumerate(channel):
                x = index / max(1, len(channel) - 1) * (self.width() - 1)
                y = self.height() - min(1.0, float(value) / peak) * (self.height() - 4)
                path.lineTo(x, y)
            path.lineTo(self.width(), self.height())
            path.closeSubpath()
            painter.fillPath(path, color)
        painter.end()
