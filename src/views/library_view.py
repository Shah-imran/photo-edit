"""Thin library view for browsing named libraries in an accordion."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.services.file_service import FileService
from src.views.widgets.collapsible_section import CollapsibleSection


class ResponsiveLibraryGrid(QListWidget):
    """Thumbnail grid that stretches its cells to fill the viewport width."""

    def __init__(
        self,
        min_cell_width: int,
        cell_height: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._min_cell_width = min_cell_width
        self._cell_height = cell_height

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self.refresh_layout_metrics()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self.refresh_layout_metrics()

    def refresh_layout_metrics(self) -> None:
        """Resize cells so the current column count fills the viewport width."""
        available_width = self.viewport().width()
        if available_width <= 0:
            return

        spacing = max(0, self.spacing())
        min_column_span = max(1, self._min_cell_width + spacing)
        column_count = max(1, (available_width + spacing) // min_column_span)
        cell_width = max(
            self._min_cell_width,
            (available_width - spacing * (column_count - 1)) // column_count,
        )
        grid_size = QSize(cell_width, self._cell_height)
        if self.gridSize() == grid_size:
            return

        self.setGridSize(grid_size)
        for index in range(self.count()):
            self.item(index).setSizeHint(grid_size)


class LibraryView(QWidget):
    """Presentation-only accordion library dock UI."""

    image_selected = pyqtSignal(str)
    import_requested = pyqtSignal()
    library_selected = pyqtSignal(str)
    create_library_requested = pyqtSignal(str)
    remove_library_requested = pyqtSignal(str)

    THUMBNAIL_SIZE = 80
    THUMB_CELL_WIDTH = 112
    THUMB_CELL_HEIGHT = 118

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._file_service = FileService()
        self._item_by_path: dict[str, QListWidgetItem] = {}
        self._current_library_id = ""
        self._library_sections: dict[str, CollapsibleSection] = {}
        self._grid_by_library_id: dict[str, QListWidget] = {}
        self._delete_button_by_library_id: dict[str, QPushButton] = {}
        self._suppress_section_signal = False

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 0, 8)
        layout.setSpacing(8)

        header_layout = QHBoxLayout()
        title = QLabel("Library")
        title.setStyleSheet("color: #a0a0a0; font-weight: bold; font-size: 12px;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self._import_button = QPushButton("+ Import")
        self._import_button.setStyleSheet(
            """
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 4px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #0086f0;
            }
            """
        )
        header_layout.addWidget(self._import_button)

        self._add_library_button = QPushButton("+ Library")
        self._add_library_button.setStyleSheet(
            """
            QPushButton {
                background-color: #3a3a3a;
                color: #e0e0e0;
                border: none;
                border-radius: 3px;
                padding: 4px 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
            """
        )
        header_layout.addWidget(self._add_library_button)
        layout.addLayout(header_layout)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll_area.setStyleSheet(
            """
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            """
        )
        self._content_widget = QWidget()
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(10)
        self._scroll_area.setWidget(self._content_widget)
        layout.addWidget(self._scroll_area, 1)

        self._info_label = QLabel("No images")
        self._info_label.setStyleSheet("color: #606060; font-size: 10px;")
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._info_label)

    def _connect_signals(self) -> None:
        self._import_button.clicked.connect(self.import_requested)
        self._add_library_button.clicked.connect(self._on_create_library_clicked)

    def set_libraries(self, libraries: list[dict], current_library_id: str) -> None:
        self._current_library_id = current_library_id
        self._suppress_section_signal = True
        try:
            self._clear_library_sections()
            for index, library in enumerate(libraries):
                library_id = str(library["id"])
                section = CollapsibleSection(
                    str(library["name"]),
                    expanded=(library_id == current_library_id),
                )
                delete_button = QPushButton("−")
                delete_button.setFlat(True)
                delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
                delete_button.setToolTip("Remove library")
                delete_button.setStyleSheet(
                    """
                    QPushButton {
                        background: transparent;
                        border: none;
                        color: #7faed6;
                        font-size: 16px;
                        font-weight: bold;
                        padding: 0 4px 4px 4px;
                    }
                    QPushButton:hover {
                        color: #b7d9f7;
                    }
                    """
                )
                delete_button.clicked.connect(
                    lambda _checked=False, lid=library_id: self._on_remove_library_clicked(
                        lid
                    )
                )
                section.add_header_widget(delete_button)
                grid = self._create_image_grid()
                section.set_content_widget(grid)
                section.toggled.connect(
                    lambda expanded, lid=library_id: self._on_library_section_toggled(
                        lid, expanded
                    )
                )
                self._library_sections[library_id] = section
                self._grid_by_library_id[library_id] = grid
                self._delete_button_by_library_id[library_id] = delete_button
                self._content_layout.insertWidget(index, section)
            self._apply_active_section_layout()
        finally:
            self._suppress_section_signal = False

    def set_entries(self, entries: list[dict]) -> None:
        self._item_by_path.clear()
        grid = self._grid_by_library_id.get(self._current_library_id)
        if grid is None:
            self._update_info_label()
            return
        grid.clear()
        for payload in entries:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, payload["path"])
            item.setData(Qt.ItemDataRole.UserRole + 1, payload["status"])
            item.setSizeHint(grid.gridSize())
            self._apply_entry_payload(item, payload)
            grid.addItem(item)
            self._item_by_path[payload["path"]] = item
        grid.refresh_layout_metrics()
        self._update_info_label()

    def _create_image_grid(self) -> ResponsiveLibraryGrid:
        grid = ResponsiveLibraryGrid(
            min_cell_width=self.THUMB_CELL_WIDTH,
            cell_height=self.THUMB_CELL_HEIGHT,
        )
        grid.setViewMode(QListWidget.ViewMode.IconMode)
        grid.setIconSize(QSize(self.THUMBNAIL_SIZE, self.THUMBNAIL_SIZE))
        grid.setSpacing(8)
        grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        grid.setWrapping(True)
        grid.setWordWrap(True)
        grid.setGridSize(QSize(self.THUMB_CELL_WIDTH, self.THUMB_CELL_HEIGHT))
        grid.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        grid.setStyleSheet(
            """
            QListWidget {
                background-color: #1a1a1a;
                border: none;
            }
            QListWidget::item {
                background-color: #2d2d2d;
                border: 2px solid transparent;
                border-radius: 4px;
                padding: 4px;
            }
            QListWidget::item:selected {
                border-color: #0078d4;
                background-color: #2d2d2d;
            }
            QListWidget::item:hover {
                background-color: #3a3a3a;
            }
            """
        )
        grid.itemClicked.connect(self._on_item_clicked)
        grid.itemDoubleClicked.connect(self._on_item_double_clicked)
        return grid

    def _clear_library_sections(self) -> None:
        for section in self._library_sections.values():
            section.setParent(None)
        self._library_sections.clear()
        self._grid_by_library_id.clear()
        self._delete_button_by_library_id.clear()

    def _on_library_section_toggled(self, library_id: str, expanded: bool) -> None:
        if self._suppress_section_signal:
            return
        if expanded:
            self._suppress_section_signal = True
            try:
                for other_id, other_section in self._library_sections.items():
                    if other_id != library_id and other_section.is_expanded():
                        other_section.set_expanded(False)
            finally:
                self._suppress_section_signal = False
            self._current_library_id = library_id
            self._apply_active_section_layout()
            self.library_selected.emit(library_id)
            return

        if library_id == self._current_library_id:
            self._apply_active_section_layout()

    def update_entry_thumbnail(self, path: str, payload: dict) -> None:
        item = self._item_by_path.get(path)
        if item is None:
            return
        self._apply_entry_payload(item, payload)

    def _apply_entry_payload(self, item: QListWidgetItem, payload: dict) -> None:
        pixmap = None
        thumbnail = payload.get("thumbnail")
        if thumbnail is not None:
            pixmap = QPixmap.fromImage(thumbnail)
        else:
            placeholder = payload.get("placeholder")
            if placeholder == "missing":
                pixmap = self._build_state_pixmap("Missing", "#5a2d2d", "#d46a6a")
            else:
                pixmap = self._build_state_pixmap("Loading", "#243544", "#84b9e6")

        item.setIcon(QIcon(pixmap))
        item.setText(str(payload["text"]))
        item.setTextAlignment(
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        )
        item.setToolTip(str(payload["tooltip"]))
        item.setData(Qt.ItemDataRole.UserRole + 1, payload["status"])

    def _build_state_pixmap(self, label: str, fill: str, stroke: str) -> QPixmap:
        pixmap = QPixmap(self.THUMBNAIL_SIZE, self.THUMBNAIL_SIZE)
        pixmap.fill(QColor(fill))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(stroke), 2))
        painter.drawRect(1, 1, self.THUMBNAIL_SIZE - 3, self.THUMBNAIL_SIZE - 3)
        painter.setPen(QColor("#e8e8e8"))
        painter.drawText(
            pixmap.rect(),
            int(Qt.AlignmentFlag.AlignCenter),
            label,
        )
        painter.end()
        return pixmap

    def _on_create_library_clicked(self) -> None:
        default_name = self._default_library_name()
        self.create_library_requested.emit(default_name)

    def _on_remove_library_clicked(self, library_id: str) -> None:
        self.remove_library_requested.emit(library_id)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        file_path = item.data(Qt.ItemDataRole.UserRole)
        status = item.data(Qt.ItemDataRole.UserRole + 1)
        if file_path and status == "available":
            self.image_selected.emit(file_path)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self._on_item_clicked(item)

    def _default_library_name(self) -> str:
        existing_names = {
            section.title() for section in self._library_sections.values()
        }
        index = 1
        while True:
            candidate = f"Library {index}"
            if candidate not in existing_names:
                return candidate
            index += 1

    def _update_info_label(self) -> None:
        grid = self._grid_by_library_id.get(self._current_library_id)
        count = grid.count() if grid is not None else 0
        if count == 0:
            self._info_label.setText("No images")
        elif count == 1:
            self._info_label.setText("1 image")
        else:
            self._info_label.setText(f"{count} images")

    def get_image_count(self) -> int:
        grid = self._grid_by_library_id.get(self._current_library_id)
        return grid.count() if grid is not None else 0

    def get_library_count(self) -> int:
        return len(self._library_sections)

    def get_selected_path(self) -> Optional[str]:
        grid = self._grid_by_library_id.get(self._current_library_id)
        if grid is None:
            return None
        current = grid.currentItem()
        if current is None:
            return None
        if current.data(Qt.ItemDataRole.UserRole + 1) != "available":
            return None
        return current.data(Qt.ItemDataRole.UserRole)

    def get_current_library_id(self) -> str:
        return self._current_library_id

    def is_library_section_expanded(self) -> bool:
        section = self._library_sections.get(self._current_library_id)
        return section.is_expanded() if section is not None else False

    def set_library_section_expanded(self, expanded: bool) -> None:
        section = self._library_sections.get(self._current_library_id)
        if section is None:
            return
        self._suppress_section_signal = True
        try:
            section.set_expanded(expanded)
            self._apply_active_section_layout()
        finally:
            self._suppress_section_signal = False

    def import_folder(self, folder_path: str, recursive: bool = False) -> list[str]:
        return self._file_service.get_image_files_from_directory(
            folder_path,
            recursive=recursive,
        )

    def cleanup(self) -> None:
        """No-op cleanup hook so MainWindow can treat panels uniformly."""
        return None

    def _apply_active_section_layout(self) -> None:
        for library_id, section in self._library_sections.items():
            is_active = library_id == self._current_library_id and section.is_expanded()
            section.set_fill_available_space(is_active)
            if is_active:
                grid = self._grid_by_library_id.get(library_id)
                if grid is not None:
                    grid.refresh_layout_metrics()
        self._content_widget.updateGeometry()
