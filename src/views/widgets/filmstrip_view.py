"""Horizontal thumbnail strip synchronized with the active library."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


class FilmstripView(QWidget):
    """A compact view of the active library's images."""

    image_selected = pyqtSignal(str)
    THUMBNAIL_SIZE = QSize(88, 62)
    CELL_SIZE = QSize(104, 78)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("filmstripView")
        self.setMinimumHeight(112)
        self.setMaximumHeight(132)
        self._item_by_path: dict[str, QListWidgetItem] = {}
        self._suppress_selection = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 6)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.setSpacing(8)
        self._source_label = QLabel("Library")
        self._source_label.setObjectName("filmstripSourceLabel")
        self._source_label.setStyleSheet("font-weight: 600; color: #e7e9ec;")
        self._count_label = QLabel("0 photos")
        self._count_label.setObjectName("filmstripCountLabel")
        self._count_label.setStyleSheet("color: #92979f;")
        header.addWidget(self._source_label)
        header.addWidget(self._count_label)
        header.addStretch(1)
        self._sort_label = QLabel("Date added")
        self._sort_label.setObjectName("filmstripSortLabel")
        self._sort_label.setStyleSheet("color: #92979f;")
        self._sort_label.setToolTip("Library order")
        header.addWidget(self._sort_label)
        layout.addLayout(header)

        self._list = QListWidget()
        self._list.setObjectName("filmstripList")
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setFlow(QListWidget.Flow.LeftToRight)
        self._list.setWrapping(False)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Static)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setIconSize(self.THUMBNAIL_SIZE)
        self._list.setGridSize(self.CELL_SIZE)
        self._list.setSpacing(4)
        self._list.setStyleSheet(
            """
            QListWidget#filmstripList { background: #202020; border: none; }
            QListWidget#filmstripList::item {
                border: 2px solid transparent;
                border-radius: 3px;
                padding: 2px;
            }
            QListWidget#filmstripList::item:hover { background: #343434; }
            QListWidget#filmstripList::item:selected {
                background: #2d2d2d;
                border-color: #0086f0;
            }
            """
        )
        self._list.setToolTip("Current library filmstrip")
        self._list.currentItemChanged.connect(self._on_current_item_changed)
        layout.addWidget(self._list)

    def set_context(self, source_name: str) -> None:
        """Update the active library name shown above the thumbnails."""
        self._source_label.setText(source_name or "Library")

    def set_entries(self, entries: list[dict]) -> None:
        current_path = self.current_path()
        self._suppress_selection = True
        try:
            self._list.clear()
            self._item_by_path.clear()
            for payload in entries:
                path = str(payload["path"])
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, path)
                item.setData(Qt.ItemDataRole.UserRole + 1, payload.get("status"))
                item.setSizeHint(self.CELL_SIZE)
                self._apply_entry_payload(item, payload)
                self._list.addItem(item)
                self._item_by_path[path] = item
            self.set_current_path(current_path)
        finally:
            self._suppress_selection = False
        count = len(entries)
        self._count_label.setText("1 photo" if count == 1 else f"{count} photos")

    def update_entry_thumbnail(self, path: str, payload: dict) -> None:
        item = self._item_by_path.get(path)
        if item is not None:
            self._apply_entry_payload(item, payload)

    def set_current_path(self, path: str | None) -> None:
        item = self._item_by_path.get(path or "")
        self._suppress_selection = True
        try:
            self._list.setCurrentItem(item)
            if item is not None:
                self._list.scrollToItem(item)
        finally:
            self._suppress_selection = False

    def current_path(self) -> str | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def count(self) -> int:
        return self._list.count()

    def _apply_entry_payload(self, item: QListWidgetItem, payload: dict) -> None:
        thumbnail = payload.get("thumbnail")
        if thumbnail is not None:
            pixmap = QPixmap.fromImage(thumbnail)
        else:
            missing = payload.get("placeholder") == "missing"
            pixmap = self._placeholder_pixmap(missing)
        item.setIcon(QIcon(pixmap))
        item.setText("")
        item.setToolTip(str(payload.get("tooltip") or Path(str(payload["path"])).name))
        item.setData(Qt.ItemDataRole.UserRole + 1, payload.get("status"))

    def _placeholder_pixmap(self, missing: bool) -> QPixmap:
        pixmap = QPixmap(self.THUMBNAIL_SIZE)
        pixmap.fill(QColor("#4a2929" if missing else "#263746"))
        painter = QPainter(pixmap)
        painter.setPen(QPen(QColor("#d46a6a" if missing else "#84b9e6"), 1))
        painter.drawRect(pixmap.rect().adjusted(0, 0, -1, -1))
        painter.setPen(QColor("#d8d8d8"))
        painter.drawText(
            pixmap.rect(),
            int(Qt.AlignmentFlag.AlignCenter),
            "Missing" if missing else "Loading",
        )
        painter.end()
        return pixmap

    def _on_current_item_changed(self, current, previous) -> None:
        del previous
        if self._suppress_selection or current is None:
            return
        if current.data(Qt.ItemDataRole.UserRole + 1) != "available":
            return
        path = current.data(Qt.ItemDataRole.UserRole)
        if path:
            self.image_selected.emit(path)
