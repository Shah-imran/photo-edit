"""Unit tests for LibraryView widget."""

from __future__ import annotations

import pytest
from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QSizePolicy

from src.views.library_view import LibraryView


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def view(qapp, qtbot):
    widget = LibraryView()
    qtbot.addWidget(widget)
    yield widget
    widget.close()


class TestLibraryView:
    def test_library_view_initialization(self, view):
        assert view is not None
        assert view.get_image_count() == 0
        assert view.get_library_count() == 0
        assert view.is_library_section_expanded() is False

    def test_set_libraries_renders_sections_and_current_selection(self, view):
        view.set_libraries(
            [
                {"id": "one", "name": "Library 1"},
                {"id": "two", "name": "Travel"},
            ],
            current_library_id="two",
        )

        assert view.get_library_count() == 2
        assert view.get_current_library_id() == "two"
        assert set(view._library_sections.keys()) == {"one", "two"}
        assert view._library_sections["two"].is_expanded() is True
        assert view._library_sections["one"].is_expanded() is False
        assert (
            view._library_sections["two"].sizePolicy().verticalPolicy()
            == QSizePolicy.Policy.Expanding
        )

    def test_set_entries_renders_grid(self, view, sample_image_path):
        view.set_libraries(
            [{"id": "one", "name": "Library 1"}],
            current_library_id="one",
        )
        view.set_entries(
            [
                {
                    "path": sample_image_path,
                    "filename": "test_image.jpg",
                    "status": "available",
                    "text": "test_image.jpg",
                    "tooltip": "test_image.jpg",
                    "thumbnail": None,
                    "placeholder": "loading",
                }
            ]
        )

        assert view.get_image_count() == 1

    def test_grid_cells_expand_to_fill_available_width(self, view, sample_image_path, qtbot):
        view.resize(340, 640)
        view.show()
        qtbot.waitExposed(view)
        view.set_libraries(
            [{"id": "one", "name": "Library 1"}],
            current_library_id="one",
        )
        view.set_entries(
            [
                {
                    "path": sample_image_path,
                    "filename": "test_image.jpg",
                    "status": "available",
                    "text": "test_image.jpg",
                    "tooltip": "test_image.jpg",
                    "thumbnail": None,
                    "placeholder": "loading",
                }
            ]
        )

        grid = view._grid_by_library_id["one"]

        def has_responsive_width() -> bool:
            viewport_width = grid.viewport().width()
            spacing = grid.spacing()
            column_count = max(
                1,
                (viewport_width + spacing)
                // (view.THUMB_CELL_WIDTH + spacing),
            )
            expected_width = max(
                view.THUMB_CELL_WIDTH,
                (viewport_width - spacing * (column_count - 1)) // column_count,
            )
            return grid.gridSize().width() == expected_width

        qtbot.waitUntil(has_responsive_width, timeout=1000)
        assert grid.gridSize().width() > view.THUMB_CELL_WIDTH

    def test_get_selected_path_no_selection(self, view):
        view.set_libraries(
            [{"id": "one", "name": "Library 1"}],
            current_library_id="one",
        )
        assert view.get_selected_path() is None

    def test_image_selected_signal(self, view, sample_image_path):
        view.set_libraries(
            [{"id": "one", "name": "Library 1"}],
            current_library_id="one",
        )
        view.set_entries(
            [
                {
                    "path": sample_image_path,
                    "filename": "test_image.jpg",
                    "status": "available",
                    "text": "test_image.jpg",
                    "tooltip": "test_image.jpg",
                    "thumbnail": None,
                    "placeholder": "loading",
                }
            ]
        )
        signal_received = []
        view.image_selected.connect(lambda p: signal_received.append(p))

        grid = view._grid_by_library_id["one"]
        item = grid.item(0)
        grid.setCurrentItem(item)
        view._on_item_clicked(item)

        assert signal_received == [sample_image_path]

    def test_missing_entry_does_not_emit_image_selected(self, view, sample_image_path):
        view.set_libraries(
            [{"id": "one", "name": "Library 1"}],
            current_library_id="one",
        )
        view.set_entries(
            [
                {
                    "path": sample_image_path,
                    "filename": "test_image.jpg",
                    "status": "missing",
                    "text": "test_image.jpg\nMissing",
                    "tooltip": sample_image_path,
                    "thumbnail": None,
                    "placeholder": "missing",
                }
            ]
        )
        signal_received = []
        view.image_selected.connect(lambda p: signal_received.append(p))

        item = view._grid_by_library_id["one"].item(0)
        view._on_item_clicked(item)

        assert signal_received == []

    def test_import_button_emits_signal(self, view, qtbot):
        with qtbot.waitSignal(view.import_requested, timeout=1000):
            view._import_button.click()

    def test_library_selected_signal(self, view, qtbot):
        view.set_libraries(
            [
                {"id": "one", "name": "Library 1"},
                {"id": "two", "name": "Travel"},
            ],
            current_library_id="one",
        )

        with qtbot.waitSignal(view.library_selected, timeout=1000) as catcher:
            view._library_sections["two"].set_expanded(True)

        assert catcher.args == ["two"]
        assert view._library_sections["one"].is_expanded() is False
        assert view._library_sections["two"].is_expanded() is True

    def test_current_library_can_be_collapsed(self, view):
        view.set_libraries(
            [{"id": "one", "name": "Library 1"}],
            current_library_id="one",
        )

        view._library_sections["one"].set_expanded(False)

        assert view.get_current_library_id() == "one"
        assert view.is_library_section_expanded() is False

    def test_create_library_button_emits_default_name(self, view, qtbot):
        view.set_libraries(
            [{"id": "one", "name": "Library 1"}],
            current_library_id="one",
        )

        with qtbot.waitSignal(view.create_library_requested, timeout=1000) as catcher:
            view._add_library_button.click()

        assert catcher.args == ["Library 2"]

    def test_inline_remove_library_button_emits_row_id(self, view, qtbot):
        view.set_libraries(
            [
                {"id": "one", "name": "Library 1"},
                {"id": "two", "name": "Travel"},
            ],
            current_library_id="one",
        )
        assert view._delete_button_by_library_id["two"].text() == "−"

        with qtbot.waitSignal(view.remove_library_requested, timeout=1000) as catcher:
            view._delete_button_by_library_id["two"].click()

        assert catcher.args == ["two"]

    def test_libraries_section_can_be_collapsed(self, view):
        view.set_libraries(
            [{"id": "one", "name": "Library 1"}],
            current_library_id="one",
        )
        view.set_library_section_expanded(False)
        assert view.is_library_section_expanded() is False
        assert view._grid_by_library_id["one"].isVisible() is False

        view.set_library_section_expanded(True)
        assert view.is_library_section_expanded() is True

    def test_import_folder(self, view, tmp_path):
        for i in range(3):
            Image.new("RGB", (50, 50), color="blue").save(tmp_path / f"test_{i}.jpg")

        imported = view.import_folder(str(tmp_path))

        assert len(imported) == 3
