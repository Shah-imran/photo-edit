"""Unit tests for FilmstripView's "Remove Photo" context-menu wiring.

See docs/planning/implementation-notes/2026-10-13-remove-delete-photo.md.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from src.views.widgets.filmstrip_view import FilmstripView


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def view(qapp, qtbot):
    widget = FilmstripView()
    qtbot.addWidget(widget)
    yield widget
    widget.close()


def _entry(path: str) -> dict:
    return {
        "path": path,
        "filename": path.rsplit("/", 1)[-1],
        "status": "available",
        "text": path,
        "tooltip": path,
        "thumbnail": None,
        "placeholder": "loading",
        "favorite": False,
        "rating": 0,
        "flag": "none",
        "keywords": [],
        "collection_ids": [],
        "captured_at": "",
    }


class TestPromptRemoveConfirmation:
    """``_prompt_remove_confirmation`` mediates the 3-way "Remove from
    Library" / "Delete from Disk" / "Cancel" dialog -- these tests mock
    ``QMessageBox.exec``/``clickedButton`` to drive each outcome without
    a real modal popping up, mirroring how this codebase already mocks
    other confirmation dialogs (see
    tests/unit/test_views/test_main_window_export_with_previous.py's
    ``QMessageBox`` patching for the export-overwrite confirmation)."""

    def test_delete_from_disk_choice_returns_true(self, view):
        with patch.object(QMessageBox, "exec", return_value=0), patch.object(
            QMessageBox,
            "clickedButton",
            lambda self: next(
                b for b in self.buttons() if b.text() == "Delete from Disk"
            ),
        ):
            result = view._prompt_remove_confirmation("this photo")

        assert result is True

    def test_remove_from_library_choice_returns_false(self, view):
        with patch.object(QMessageBox, "exec", return_value=0), patch.object(
            QMessageBox,
            "clickedButton",
            lambda self: next(
                b for b in self.buttons() if b.text() == "Remove from Library"
            ),
        ):
            result = view._prompt_remove_confirmation("this photo")

        assert result is False

    def test_cancel_choice_returns_none(self, view):
        with patch.object(QMessageBox, "exec", return_value=0), patch.object(
            QMessageBox,
            "clickedButton",
            lambda self: next(
                b for b in self.buttons() if b.text() == "Cancel"
            ),
        ):
            result = view._prompt_remove_confirmation("this photo")

        assert result is None


class TestContextMenuRemoveWiring:
    """Drives ``_show_context_menu``/``_show_batch_context_menu`` with
    ``QMenu.exec`` mocked to immediately "click" the Remove action, and
    ``_prompt_remove_confirmation`` mocked to each of its three possible
    return values, asserting the right signal fires (or doesn't)."""

    def test_single_item_delete_from_disk_emits_remove_requested(self, view, qtbot):
        view.set_entries([_entry("/photos/a.jpg")])
        item = view._item_by_path["/photos/a.jpg"]

        with patch.object(
            view, "_prompt_remove_confirmation", return_value=True
        ), patch(
            "src.views.widgets.filmstrip_view.QMenu.exec",
            lambda self, *a, **k: next(
                a_ for a_ in self.actions() if a_.text() == "Remove Photo..."
            ),
        ):
            with qtbot.waitSignal(view.remove_requested, timeout=1000) as blocker:
                view._show_context_menu(view._list.visualItemRect(item).center())

        assert blocker.args == ["/photos/a.jpg", True]

    def test_single_item_remove_from_library_emits_remove_requested(
        self, view, qtbot
    ):
        view.set_entries([_entry("/photos/a.jpg")])
        item = view._item_by_path["/photos/a.jpg"]

        with patch.object(
            view, "_prompt_remove_confirmation", return_value=False
        ), patch(
            "src.views.widgets.filmstrip_view.QMenu.exec",
            lambda self, *a, **k: next(
                a_ for a_ in self.actions() if a_.text() == "Remove Photo..."
            ),
        ):
            with qtbot.waitSignal(view.remove_requested, timeout=1000) as blocker:
                view._show_context_menu(view._list.visualItemRect(item).center())

        assert blocker.args == ["/photos/a.jpg", False]

    def test_single_item_cancel_emits_nothing(self, view, qtbot):
        view.set_entries([_entry("/photos/a.jpg")])
        item = view._item_by_path["/photos/a.jpg"]
        received = []
        view.remove_requested.connect(lambda *args: received.append(args))

        with patch.object(
            view, "_prompt_remove_confirmation", return_value=None
        ), patch(
            "src.views.widgets.filmstrip_view.QMenu.exec",
            lambda self, *a, **k: next(
                a_ for a_ in self.actions() if a_.text() == "Remove Photo..."
            ),
        ):
            view._show_context_menu(view._list.visualItemRect(item).center())

        assert received == []

    def test_batch_delete_from_disk_emits_remove_batch_requested(self, view, qtbot):
        view.set_entries([_entry("/photos/a.jpg"), _entry("/photos/b.jpg")])
        item_a = view._item_by_path["/photos/a.jpg"]
        item_b = view._item_by_path["/photos/b.jpg"]
        item_a.setSelected(True)
        item_b.setSelected(True)

        with patch.object(
            view, "_prompt_remove_confirmation", return_value=True
        ), patch(
            "src.views.widgets.filmstrip_view.QMenu.exec",
            lambda self, *a, **k: next(
                a_ for a_ in self.actions() if a_.text().startswith("Remove 2 Photos")
            ),
        ):
            with qtbot.waitSignal(
                view.remove_batch_requested, timeout=1000
            ) as blocker:
                view._show_batch_context_menu(
                    view._list.visualItemRect(item_a).center(), [item_a, item_b]
                )

        paths, delete_from_disk = blocker.args
        assert set(paths) == {"/photos/a.jpg", "/photos/b.jpg"}
        assert delete_from_disk is True
