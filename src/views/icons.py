"""Small code-drawn icons used by the PhotoEdit workspace shell."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def line_icon(name: str, color: str = "#cbd3dc", size: int = 18) -> QIcon:
    """Return a crisp, dependency-free outline icon for a named action."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), max(1.2, size / 12.0))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    s = float(size)

    if name == "folder":
        path = QPainterPath()
        path.moveTo(.12 * s, .32 * s)
        path.lineTo(.38 * s, .32 * s)
        path.lineTo(.46 * s, .23 * s)
        path.lineTo(.86 * s, .23 * s)
        path.lineTo(.9 * s, .76 * s)
        path.lineTo(.12 * s, .76 * s)
        path.closeSubpath()
        painter.drawPath(path)
    elif name == "heart":
        path = QPainterPath(QPointF(.5 * s, .82 * s))
        path.cubicTo(.42 * s, .7 * s, .14 * s, .53 * s, .18 * s, .32 * s)
        path.cubicTo(.22 * s, .13 * s, .43 * s, .16 * s, .5 * s, .3 * s)
        path.cubicTo(.57 * s, .16 * s, .78 * s, .13 * s, .82 * s, .32 * s)
        path.cubicTo(.86 * s, .53 * s, .58 * s, .7 * s, .5 * s, .82 * s)
        painter.drawPath(path)
    elif name == "clock":
        painter.drawEllipse(QRectF(.16 * s, .16 * s, .68 * s, .68 * s))
        painter.drawLine(QPointF(.5 * s, .28 * s), QPointF(.5 * s, .52 * s))
        painter.drawLine(QPointF(.5 * s, .52 * s), QPointF(.66 * s, .61 * s))
    elif name in {"undo", "redo"}:
        left = name == "undo"
        x0, x1 = ((.2, .78) if left else (.8, .22))
        painter.drawArc(QRectF(.18 * s, .24 * s, .64 * s, .55 * s), 25 * 16, 245 * 16)
        tip = QPointF(x0 * s, .37 * s)
        painter.drawLine(tip, QPointF((x0 + (.18 if left else -.18)) * s, .2 * s))
        painter.drawLine(tip, QPointF((x0 + (.2 if left else -.2)) * s, .45 * s))
    elif name == "curve":
        painter.drawLine(QPointF(.16 * s, .82 * s), QPointF(.16 * s, .18 * s))
        painter.drawLine(QPointF(.16 * s, .82 * s), QPointF(.84 * s, .82 * s))
        path = QPainterPath(QPointF(.2 * s, .75 * s))
        path.cubicTo(.34 * s, .72 * s, .52 * s, .32 * s, .8 * s, .22 * s)
        painter.drawPath(path)
    elif name == "crop":
        painter.drawLine(QPointF(.25 * s, .12 * s), QPointF(.25 * s, .72 * s))
        painter.drawLine(QPointF(.12 * s, .25 * s), QPointF(.72 * s, .25 * s))
        painter.drawLine(QPointF(.75 * s, .88 * s), QPointF(.75 * s, .3 * s))
        painter.drawLine(QPointF(.3 * s, .75 * s), QPointF(.88 * s, .75 * s))
    elif name == "reset":
        painter.drawArc(QRectF(.2 * s, .2 * s, .62 * s, .62 * s), 35 * 16, 285 * 16)
        painter.drawLine(QPointF(.2 * s, .46 * s), QPointF(.18 * s, .2 * s))
        painter.drawLine(QPointF(.2 * s, .46 * s), QPointF(.42 * s, .34 * s))
    elif name == "export":
        painter.drawRect(QRectF(.18 * s, .38 * s, .64 * s, .48 * s))
        painter.drawLine(QPointF(.5 * s, .62 * s), QPointF(.5 * s, .12 * s))
        painter.drawLine(QPointF(.5 * s, .12 * s), QPointF(.34 * s, .3 * s))
        painter.drawLine(QPointF(.5 * s, .12 * s), QPointF(.66 * s, .3 * s))
    elif name == "compare":
        painter.drawRect(QRectF(.15 * s, .2 * s, .7 * s, .6 * s))
        painter.drawLine(QPointF(.5 * s, .2 * s), QPointF(.5 * s, .8 * s))
    elif name == "filter":
        path = QPainterPath(QPointF(.14 * s, .2 * s))
        path.lineTo(.86 * s, .2 * s)
        path.lineTo(.58 * s, .5 * s)
        path.lineTo(.58 * s, .78 * s)
        path.lineTo(.42 * s, .86 * s)
        path.lineTo(.42 * s, .5 * s)
        path.closeSubpath()
        painter.drawPath(path)
    elif name == "sort":
        for y, width in ((.28, .62), (.5, .44), (.72, .26)):
            painter.drawLine(QPointF(.2 * s, y * s), QPointF((.2 + width) * s, y * s))
    elif name == "heal":
        painter.drawLine(QPointF(.24 * s, .72 * s), QPointF(.72 * s, .24 * s))
        painter.drawEllipse(QRectF(.16 * s, .55 * s, .28 * s, .28 * s))
        painter.drawEllipse(QRectF(.56 * s, .16 * s, .28 * s, .28 * s))
    elif name == "mask":
        painter.drawEllipse(QRectF(.18 * s, .18 * s, .64 * s, .64 * s))
        painter.setBrush(QColor(color))
        painter.drawChord(QRectF(.18 * s, .18 * s, .64 * s, .64 * s), 90 * 16, 180 * 16)
    elif name == "transform":
        painter.drawRect(QRectF(.24 * s, .24 * s, .52 * s, .52 * s))
        for x, y in ((.18, .18), (.82, .18), (.18, .82), (.82, .82)):
            painter.drawRect(QRectF((x - .05) * s, (y - .05) * s, .1 * s, .1 * s))
    elif name in {"color", "mixer", "effects"}:
        colors = ("#ff5c5c", "#52d273", "#4da3ff")
        for index, fill in enumerate(colors):
            painter.setPen(QPen(QColor(fill), max(1.2, size / 12.0)))
            painter.setBrush(QColor(fill) if name == "color" else Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF((.18 + index * .2) * s, (.28 + (index % 2) * .2) * s, .3 * s, .3 * s))
    else:
        painter.drawEllipse(QRectF(.2 * s, .2 * s, .6 * s, .6 * s))

    painter.end()
    return QIcon(pixmap)
