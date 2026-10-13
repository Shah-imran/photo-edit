"""Tests for the polished workspace shell widgets."""

import numpy as np

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage
from PyQt6.QtTest import QTest

from src.views.theme import APP_STYLESHEET, apply_theme
from src.views.widgets.filmstrip_view import FilmstripView
from src.views.widgets.image_toolbar import ImageToolBar
from src.views.widgets.histogram_widget import HistogramWidget
from src.views.widgets.workspace_header import WorkspaceHeader


def _entry(path: str, *, status: str = "available") -> dict:
    return {
        "path": path,
        "status": status,
        "text": path.rsplit("/", 1)[-1],
        "tooltip": path,
        "placeholder": "loading",
    }


def test_apply_theme_installs_shared_stylesheet(qapp):
    apply_theme(qapp)
    assert qapp.styleSheet() == APP_STYLESHEET


def test_image_toolbar_emits_intents_and_tracks_zoom(qapp, qtbot):
    toolbar = ImageToolBar()
    qtbot.addWidget(toolbar)

    with qtbot.waitSignal(toolbar.fit_requested):
        QTest.mouseClick(toolbar._fit_button, Qt.MouseButton.LeftButton)
    with qtbot.waitSignal(toolbar.actual_size_requested):
        QTest.mouseClick(toolbar._actual_size_button, Qt.MouseButton.LeftButton)
    with qtbot.waitSignal(toolbar.zoom_in_requested):
        QTest.mouseClick(toolbar._zoom_in_button, Qt.MouseButton.LeftButton)
    with qtbot.waitSignal(toolbar.zoom_out_requested):
        QTest.mouseClick(toolbar._zoom_out_button, Qt.MouseButton.LeftButton)

    toolbar.set_zoom_factor(0.421)
    assert toolbar._zoom_label.text() == "42%"


def test_filmstrip_populates_selects_and_emits(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_context("Landscapes")
    strip.set_entries([_entry("C:/photos/one.jpg"), _entry("C:/photos/two.jpg")])

    assert strip.count() == 2
    assert strip._source_label.text() == "Landscapes"
    assert strip._count_label.text() == "2 photos"
    strip.set_current_path("C:/photos/one.jpg")
    assert strip.current_path() == "C:/photos/one.jpg"

    with qtbot.waitSignal(strip.image_selected) as blocker:
        strip._list.setCurrentRow(1)
    assert blocker.args == ["C:/photos/two.jpg"]


def test_filmstrip_ignores_missing_selection_and_accepts_late_thumbnail(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/missing.jpg", status="missing")])
    received = []
    strip.image_selected.connect(received.append)

    strip._list.setCurrentRow(0)
    assert received == []

    image = QImage(24, 16, QImage.Format.Format_RGB888)
    image.fill(Qt.GlobalColor.red)
    payload = _entry("C:/photos/missing.jpg")
    payload["thumbnail"] = image
    strip.update_entry_thumbnail(payload["path"], payload)
    item = strip._item_by_path[payload["path"]]
    assert item.icon().isNull() is False


def test_filmstrip_filters_favorites_and_sorts_by_name(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    favorite = _entry("C:/photos/zebra.jpg")
    favorite["favorite"] = True
    strip.set_entries([favorite, _entry("C:/photos/alpha.jpg")])

    strip.set_sort("name")
    assert strip._list.item(0).data(Qt.ItemDataRole.UserRole).endswith("alpha.jpg")
    strip.set_filter("favorites")
    assert strip.count() == 1
    assert strip._list.item(0).data(Qt.ItemDataRole.UserRole).endswith("zebra.jpg")


def test_filmstrip_search_filters_by_filename_substring(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/sunset.jpg"), _entry("C:/photos/alpha.jpg")])

    strip.set_search_text("sun")
    assert strip.count() == 1
    assert strip._list.item(0).data(Qt.ItemDataRole.UserRole).endswith("sunset.jpg")


def test_filmstrip_search_cleared_restores_all_entries(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/sunset.jpg"), _entry("C:/photos/alpha.jpg")])

    strip.set_search_text("sun")
    assert strip.count() == 1
    strip.set_search_text("")
    assert strip.count() == 2


def test_filmstrip_select_next_and_previous_move_through_entries(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries(
        [_entry("C:/photos/one.jpg"), _entry("C:/photos/two.jpg"), _entry("C:/photos/three.jpg")]
    )
    strip.set_current_path("C:/photos/one.jpg")

    with qtbot.waitSignal(strip.image_selected) as blocker:
        assert strip.select_next() is True
    assert blocker.args == ["C:/photos/two.jpg"]
    assert strip.current_path() == "C:/photos/two.jpg"

    with qtbot.waitSignal(strip.image_selected) as blocker:
        assert strip.select_next() is True
    assert blocker.args == ["C:/photos/three.jpg"]
    assert strip.current_path() == "C:/photos/three.jpg"

    with qtbot.waitSignal(strip.image_selected) as blocker:
        assert strip.select_previous() is True
    assert blocker.args == ["C:/photos/two.jpg"]
    assert strip.current_path() == "C:/photos/two.jpg"


def test_filmstrip_select_next_at_last_entry_does_not_move_or_wrap(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/one.jpg"), _entry("C:/photos/two.jpg")])
    strip.set_current_path("C:/photos/two.jpg")

    assert strip.select_next() is False
    assert strip.current_path() == "C:/photos/two.jpg"


def test_filmstrip_select_previous_at_first_entry_does_not_move_or_wrap(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/one.jpg"), _entry("C:/photos/two.jpg")])
    strip.set_current_path("C:/photos/one.jpg")

    assert strip.select_previous() is False
    assert strip.current_path() == "C:/photos/one.jpg"


def test_filmstrip_select_next_and_previous_on_empty_filmstrip_return_false(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)

    assert strip.select_next() is False
    assert strip.select_previous() is False


def test_filmstrip_select_next_and_previous_respect_filtered_sorted_order(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    favorite_match = _entry("C:/photos/sunset.jpg")
    favorite_match["favorite"] = True
    favorite_no_match = _entry("C:/photos/mountain.jpg")
    favorite_no_match["favorite"] = True
    plain_match = _entry("C:/photos/sunrise.jpg")
    # Unfiltered/unsorted order is sunset, mountain, sunrise; the active
    # filter+sort+search below should leave only sunrise and sunset, sorted
    # by name -- select_next/previous must walk THAT order, not the
    # original self._entries order.
    strip.set_entries([favorite_match, favorite_no_match, plain_match])
    strip.set_filter("favorites")
    strip.set_search_text("sun")
    strip.set_sort("name")

    assert [strip._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(strip.count())] == [
        "C:/photos/sunset.jpg"
    ]
    # Only the favorites+"sun"-matching entry (sunset) survives the filter;
    # mountain (favorite but no "sun" match) and sunrise (matches "sun" but
    # not a favorite) are both excluded, so a single-item displayed order is
    # exactly what this filtered/sorted view should be able to navigate.
    strip.set_current_path("C:/photos/sunset.jpg")
    assert strip.select_next() is False
    assert strip.select_previous() is False

    # Rebuild with a filtered+sorted order containing two entries, confirming
    # next/previous actually walks the FILTERED/SORTED order, not the
    # original entries order.
    strip.set_filter("all")
    strip.set_search_text("")
    strip.set_sort("name")
    strip.set_entries(
        [
            _entry("C:/photos/zebra.jpg"),
            _entry("C:/photos/alpha.jpg"),
            _entry("C:/photos/mango.jpg"),
        ]
    )
    # Sorted by name: alpha, mango, zebra -- NOT the original zebra/alpha/mango
    # insertion order.
    assert [strip._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(strip.count())] == [
        "C:/photos/alpha.jpg",
        "C:/photos/mango.jpg",
        "C:/photos/zebra.jpg",
    ]
    strip.set_current_path("C:/photos/alpha.jpg")
    with qtbot.waitSignal(strip.image_selected) as blocker:
        assert strip.select_next() is True
    assert blocker.args == ["C:/photos/mango.jpg"]


def test_filmstrip_search_composes_with_favorites_filter(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    favorite_match = _entry("C:/photos/sunset.jpg")
    favorite_match["favorite"] = True
    favorite_no_match = _entry("C:/photos/mountain.jpg")
    favorite_no_match["favorite"] = True
    plain_match = _entry("C:/photos/sunrise.jpg")
    strip.set_entries([favorite_match, favorite_no_match, plain_match])

    strip.set_filter("favorites")
    strip.set_search_text("sun")

    assert strip.count() == 1
    assert strip._list.item(0).data(Qt.ItemDataRole.UserRole).endswith("sunset.jpg")


def test_filmstrip_search_composes_with_name_sort(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries(
        [
            _entry("C:/photos/sun_zebra.jpg"),
            _entry("C:/photos/sun_alpha.jpg"),
            _entry("C:/photos/other.jpg"),
        ]
    )

    strip.set_sort("name")
    strip.set_search_text("sun")

    assert strip.count() == 2
    assert strip._list.item(0).data(Qt.ItemDataRole.UserRole).endswith("sun_alpha.jpg")
    assert strip._list.item(1).data(Qt.ItemDataRole.UserRole).endswith("sun_zebra.jpg")


def test_filmstrip_search_with_no_matches_is_empty_not_crash(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/alpha.jpg"), _entry("C:/photos/beta.jpg")])

    strip.set_search_text("nonexistent")
    assert strip.count() == 0
    assert strip._count_label.text() == "0 photos"


def test_filmstrip_search_is_case_insensitive(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/sunset.jpg"), _entry("C:/photos/alpha.jpg")])

    strip.set_search_text("SUNSET")
    assert strip.count() == 1
    assert strip._list.item(0).data(Qt.ItemDataRole.UserRole).endswith("sunset.jpg")

    strip.set_search_text("sunset")
    assert strip.count() == 1
    assert strip._list.item(0).data(Qt.ItemDataRole.UserRole).endswith("sunset.jpg")


def test_filmstrip_search_whitespace_is_stripped(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/sunset.jpg"), _entry("C:/photos/alpha.jpg")])

    strip.set_search_text("  sunset  ")
    assert strip.count() == 1
    assert strip._list.item(0).data(Qt.ItemDataRole.UserRole).endswith("sunset.jpg")


def test_filmstrip_favorite_only_tooltip_and_text_are_unchanged(qapp, qtbot):
    """Regression guard: adding ratings must not alter the existing
    favorite-only item text/tooltip behavior in any way."""
    strip = FilmstripView()
    qtbot.addWidget(strip)
    favorite = _entry("C:/photos/zebra.jpg")
    favorite["favorite"] = True
    strip.set_entries([favorite])

    item = strip._item_by_path["C:/photos/zebra.jpg"]
    assert item.text() == "★"
    assert item.toolTip() == "Favorite\nC:/photos/zebra.jpg"
    assert item.data(Qt.ItemDataRole.UserRole + 2) is True


def test_filmstrip_rating_appears_in_tooltip_only_and_leaves_text_alone(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    rated = _entry("C:/photos/zebra.jpg")
    rated["rating"] = 3
    strip.set_entries([rated, _entry("C:/photos/alpha.jpg")])

    rated_item = strip._item_by_path["C:/photos/zebra.jpg"]
    unrated_item = strip._item_by_path["C:/photos/alpha.jpg"]

    # Rating never touches the item TEXT -- that's reserved for favorite.
    assert rated_item.text() == ""
    assert rated_item.toolTip() == "Rating: ★★★☆☆\nC:/photos/zebra.jpg"
    assert rated_item.data(Qt.ItemDataRole.UserRole + 3) == 3

    # A rating of 0 adds nothing to the tooltip.
    assert unrated_item.toolTip() == "C:/photos/alpha.jpg"
    assert unrated_item.data(Qt.ItemDataRole.UserRole + 3) == 0


def test_filmstrip_favorite_and_rating_both_show_in_tooltip_together(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    entry = _entry("C:/photos/zebra.jpg")
    entry["favorite"] = True
    entry["rating"] = 5
    strip.set_entries([entry])

    item = strip._item_by_path["C:/photos/zebra.jpg"]
    assert item.text() == "★"
    assert item.toolTip() == "Favorite\nRating: ★★★★★\nC:/photos/zebra.jpg"


def test_filmstrip_flag_appears_in_tooltip_only_and_leaves_text_alone(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    picked = _entry("C:/photos/zebra.jpg")
    picked["flag"] = "pick"
    rejected = _entry("C:/photos/alpha.jpg")
    rejected["flag"] = "reject"
    unflagged = _entry("C:/photos/beta.jpg")
    strip.set_entries([picked, rejected, unflagged])

    picked_item = strip._item_by_path["C:/photos/zebra.jpg"]
    rejected_item = strip._item_by_path["C:/photos/alpha.jpg"]
    unflagged_item = strip._item_by_path["C:/photos/beta.jpg"]

    # Flag never touches the item TEXT -- that's reserved for favorite.
    assert picked_item.text() == ""
    assert picked_item.toolTip() == "Pick\nC:/photos/zebra.jpg"
    assert picked_item.data(Qt.ItemDataRole.UserRole + 4) == "pick"

    assert rejected_item.toolTip() == "Rejected\nC:/photos/alpha.jpg"
    assert rejected_item.data(Qt.ItemDataRole.UserRole + 4) == "reject"

    # "none" adds nothing to the tooltip.
    assert unflagged_item.toolTip() == "C:/photos/beta.jpg"
    assert unflagged_item.data(Qt.ItemDataRole.UserRole + 4) == "none"


def test_filmstrip_favorite_rating_and_flag_all_show_in_tooltip_together(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    entry = _entry("C:/photos/zebra.jpg")
    entry["favorite"] = True
    entry["rating"] = 5
    entry["flag"] = "pick"
    strip.set_entries([entry])

    item = strip._item_by_path["C:/photos/zebra.jpg"]
    assert item.text() == "★"
    assert item.toolTip() == "Favorite\nRating: ★★★★★\nPick\nC:/photos/zebra.jpg"


def test_filmstrip_context_menu_flag_as_pick_emits_flag_changed(qapp, qtbot):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/one.jpg")])
    item = strip._item_by_path["C:/photos/one.jpg"]

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            if action.text() == "Flag as Pick":
                return action
        return None

    with patch.object(QMenu, "exec", fake_exec):
        with qtbot.waitSignal(strip.flag_changed) as blocker:
            strip._show_context_menu(strip._list.visualItemRect(item).center())

    assert blocker.args == ["C:/photos/one.jpg", "pick"]


def test_filmstrip_context_menu_flag_as_reject_emits_flag_changed(qapp, qtbot):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/one.jpg")])
    item = strip._item_by_path["C:/photos/one.jpg"]

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            if action.text() == "Flag as Reject":
                return action
        return None

    with patch.object(QMenu, "exec", fake_exec):
        with qtbot.waitSignal(strip.flag_changed) as blocker:
            strip._show_context_menu(strip._list.visualItemRect(item).center())

    assert blocker.args == ["C:/photos/one.jpg", "reject"]


def test_filmstrip_context_menu_remove_flag_emits_none(qapp, qtbot):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    entry = _entry("C:/photos/one.jpg")
    entry["flag"] = "pick"
    strip.set_entries([entry])
    item = strip._item_by_path["C:/photos/one.jpg"]

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            if action.text() == "Remove Flag":
                return action
        return None

    with patch.object(QMenu, "exec", fake_exec):
        with qtbot.waitSignal(strip.flag_changed) as blocker:
            strip._show_context_menu(strip._list.visualItemRect(item).center())

    assert blocker.args == ["C:/photos/one.jpg", "none"]


def test_filmstrip_context_menu_remove_flag_absent_when_unflagged(qapp, qtbot):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/one.jpg")])
    item = strip._item_by_path["C:/photos/one.jpg"]

    seen_action_texts = []

    def fake_exec(self, *_args, **_kwargs):
        seen_action_texts.extend(action.text() for action in self.actions())
        return None

    with patch.object(QMenu, "exec", fake_exec):
        strip._show_context_menu(strip._list.visualItemRect(item).center())

    assert "Flag as Pick" in seen_action_texts
    assert "Flag as Reject" in seen_action_texts
    assert "Remove Flag" not in seen_action_texts


def test_filmstrip_keywords_appear_in_tooltip_only_and_leave_text_alone(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    keyworded = _entry("C:/photos/zebra.jpg")
    keyworded["keywords"] = ["sunset", "beach"]
    unkeyworded = _entry("C:/photos/alpha.jpg")
    strip.set_entries([keyworded, unkeyworded])

    keyworded_item = strip._item_by_path["C:/photos/zebra.jpg"]
    unkeyworded_item = strip._item_by_path["C:/photos/alpha.jpg"]

    # Keywords never touch the item TEXT -- that's reserved for favorite.
    assert keyworded_item.text() == ""
    assert keyworded_item.toolTip() == "Keywords: sunset, beach\nC:/photos/zebra.jpg"
    assert keyworded_item.data(Qt.ItemDataRole.UserRole + 5) == ["sunset", "beach"]

    # Empty keywords add nothing to the tooltip.
    assert unkeyworded_item.toolTip() == "C:/photos/alpha.jpg"
    assert unkeyworded_item.data(Qt.ItemDataRole.UserRole + 5) == []


def test_filmstrip_favorite_rating_flag_and_keywords_all_show_in_tooltip_together(
    qapp, qtbot
):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    entry = _entry("C:/photos/zebra.jpg")
    entry["favorite"] = True
    entry["rating"] = 5
    entry["flag"] = "pick"
    entry["keywords"] = ["sunset"]
    strip.set_entries([entry])

    item = strip._item_by_path["C:/photos/zebra.jpg"]
    assert item.text() == "★"
    assert (
        item.toolTip()
        == "Favorite\nRating: ★★★★★\nPick\nKeywords: sunset\nC:/photos/zebra.jpg"
    )


def test_filmstrip_context_menu_edit_keywords_prefills_dialog_and_emits_parsed_list(
    qapp, qtbot
):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QInputDialog, QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    entry = _entry("C:/photos/one.jpg")
    entry["keywords"] = ["sunset", "beach"]
    strip.set_entries([entry])
    item = strip._item_by_path["C:/photos/one.jpg"]

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            if action.text() == "Edit Keywords...":
                return action
        return None

    captured_kwargs = {}

    def fake_get_text(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return "sunset, mountain, , beach ", True

    with patch.object(QMenu, "exec", fake_exec), patch.object(
        QInputDialog, "getText", staticmethod(fake_get_text)
    ):
        with qtbot.waitSignal(strip.keywords_changed) as blocker:
            strip._show_context_menu(strip._list.visualItemRect(item).center())

    assert captured_kwargs.get("text") == "sunset, beach"
    assert blocker.args == ["C:/photos/one.jpg", ["sunset", "mountain", "beach"]]


def test_filmstrip_context_menu_edit_keywords_cancel_emits_nothing(qapp, qtbot):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QInputDialog, QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/one.jpg")])
    item = strip._item_by_path["C:/photos/one.jpg"]

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            if action.text() == "Edit Keywords...":
                return action
        return None

    def fake_get_text(*_args, **_kwargs):
        return "sunset, beach", False

    received = []
    strip.keywords_changed.connect(lambda *args: received.append(args))

    with patch.object(QMenu, "exec", fake_exec), patch.object(
        QInputDialog, "getText", staticmethod(fake_get_text)
    ):
        strip._show_context_menu(strip._list.visualItemRect(item).center())

    assert received == []


def test_filmstrip_context_menu_set_rating_emits_rating_changed(qapp, qtbot):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/one.jpg")])
    item = strip._item_by_path["C:/photos/one.jpg"]

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            submenu = action.menu()
            if submenu is None:
                continue
            for sub_action in submenu.actions():
                if sub_action.text() == "★★★ (3)":
                    return sub_action
        return None

    with patch.object(QMenu, "exec", fake_exec):
        with qtbot.waitSignal(strip.rating_changed) as blocker:
            strip._show_context_menu(strip._list.visualItemRect(item).center())

    assert blocker.args == ["C:/photos/one.jpg", 3]


def test_filmstrip_context_menu_no_rating_emits_zero(qapp, qtbot):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    entry = _entry("C:/photos/one.jpg")
    entry["rating"] = 4
    strip.set_entries([entry])
    item = strip._item_by_path["C:/photos/one.jpg"]

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            submenu = action.menu()
            if submenu is None:
                continue
            for sub_action in submenu.actions():
                if sub_action.text() == "No Rating":
                    return sub_action
        return None

    with patch.object(QMenu, "exec", fake_exec):
        with qtbot.waitSignal(strip.rating_changed) as blocker:
            strip._show_context_menu(strip._list.visualItemRect(item).center())

    assert blocker.args == ["C:/photos/one.jpg", 0]


def test_filmstrip_set_filter_collection_mode_filters_by_collection_id(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    member = _entry("C:/photos/zebra.jpg")
    member["collection_ids"] = ["c1"]
    other = _entry("C:/photos/alpha.jpg")
    other["collection_ids"] = ["c2"]
    unassigned = _entry("C:/photos/mango.jpg")
    strip.set_entries([member, other, unassigned])

    strip.set_filter("collection:c1")

    assert strip.count() == 1
    assert strip._list.item(0).data(Qt.ItemDataRole.UserRole).endswith("zebra.jpg")


def test_filmstrip_set_filter_unknown_mode_falls_back_to_all(qapp, qtbot):
    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/one.jpg"), _entry("C:/photos/two.jpg")])

    strip.set_filter("not-a-real-mode")

    assert strip.count() == 2


def test_filmstrip_context_menu_add_to_collection_toggles_membership_on(qapp, qtbot):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/one.jpg")])
    strip.set_collections([{"id": "c1", "name": "Travel", "count": 0}])
    item = strip._item_by_path["C:/photos/one.jpg"]

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            submenu = action.menu()
            if submenu is None:
                continue
            for sub_action in submenu.actions():
                if sub_action.text() == "Travel":
                    assert sub_action.isChecked() is False
                    return sub_action
        return None

    with patch.object(QMenu, "exec", fake_exec):
        with qtbot.waitSignal(strip.collection_membership_toggled) as blocker:
            strip._show_context_menu(strip._list.visualItemRect(item).center())

    assert blocker.args == ["C:/photos/one.jpg", "c1", True]


def test_filmstrip_context_menu_add_to_collection_toggles_membership_off(qapp, qtbot):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    entry = _entry("C:/photos/one.jpg")
    entry["collection_ids"] = ["c1"]
    strip.set_entries([entry])
    strip.set_collections([{"id": "c1", "name": "Travel", "count": 1}])
    item = strip._item_by_path["C:/photos/one.jpg"]

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            submenu = action.menu()
            if submenu is None:
                continue
            for sub_action in submenu.actions():
                if sub_action.text() == "Travel":
                    assert sub_action.isChecked() is True
                    return sub_action
        return None

    with patch.object(QMenu, "exec", fake_exec):
        with qtbot.waitSignal(strip.collection_membership_toggled) as blocker:
            strip._show_context_menu(strip._list.visualItemRect(item).center())

    assert blocker.args == ["C:/photos/one.jpg", "c1", False]


def test_filmstrip_context_menu_new_collection_prompts_and_emits(qapp, qtbot):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QInputDialog, QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/one.jpg")])
    item = strip._item_by_path["C:/photos/one.jpg"]

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            submenu = action.menu()
            if submenu is None:
                continue
            for sub_action in submenu.actions():
                if sub_action.text() == "New Collection...":
                    return sub_action
        return None

    def fake_get_text(*_args, **_kwargs):
        return "Travel", True

    with patch.object(QMenu, "exec", fake_exec), patch.object(
        QInputDialog, "getText", staticmethod(fake_get_text)
    ):
        with qtbot.waitSignal(strip.new_collection_for_entry_requested) as blocker:
            strip._show_context_menu(strip._list.visualItemRect(item).center())

    assert blocker.args == ["C:/photos/one.jpg", "Travel"]


def test_filmstrip_context_menu_new_collection_cancel_emits_nothing(qapp, qtbot):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QInputDialog, QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/one.jpg")])
    item = strip._item_by_path["C:/photos/one.jpg"]

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            submenu = action.menu()
            if submenu is None:
                continue
            for sub_action in submenu.actions():
                if sub_action.text() == "New Collection...":
                    return sub_action
        return None

    received = []
    strip.new_collection_for_entry_requested.connect(lambda *args: received.append(args))

    with patch.object(QMenu, "exec", fake_exec), patch.object(
        QInputDialog, "getText", staticmethod(lambda *a, **k: ("Travel", False))
    ):
        strip._show_context_menu(strip._list.visualItemRect(item).center())

    assert received == []


def test_filmstrip_list_uses_extended_selection_mode(qapp, qtbot):
    from PyQt6.QtWidgets import QAbstractItemView

    strip = FilmstripView()
    qtbot.addWidget(strip)
    assert (
        strip._list.selectionMode()
        == QAbstractItemView.SelectionMode.ExtendedSelection
    )


def test_filmstrip_single_click_still_opens_exactly_one_image_unregressed(
    qapp, qtbot
):
    """Critical regression guard (see docs/planning/implementation-notes/
    2026-10-13-multi-select-batch-actions.md): multi-select is additive,
    not a replacement for the single "open in editor" flow -- a plain
    click on one item must still emit ``image_selected`` for that one
    path only, exactly as it did before ExtendedSelection was enabled."""
    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/one.jpg"), _entry("C:/photos/two.jpg")])

    with qtbot.waitSignal(strip.image_selected) as blocker:
        strip._list.setCurrentRow(0)
    assert blocker.args == ["C:/photos/one.jpg"]

    received = []
    strip.image_selected.connect(received.append)
    with qtbot.waitSignal(strip.image_selected) as blocker:
        strip._list.setCurrentRow(1)
    assert blocker.args == ["C:/photos/two.jpg"]
    # Exactly one selection, exactly one emission -- no batch fan-out.
    assert received == ["C:/photos/two.jpg"]


def test_filmstrip_batch_context_menu_only_triggers_when_right_clicked_item_is_selected(
    qapp, qtbot
):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/one.jpg"), _entry("C:/photos/two.jpg")])
    one = strip._item_by_path["C:/photos/one.jpg"]
    two = strip._item_by_path["C:/photos/two.jpg"]
    one.setSelected(True)
    two.setSelected(True)

    seen_action_texts = []

    def fake_exec(self, *_args, **_kwargs):
        seen_action_texts.extend(action.text() for action in self.actions())
        return None

    with patch.object(QMenu, "exec", fake_exec):
        strip._show_context_menu(strip._list.visualItemRect(one).center())

    # The batch menu's favorite action carries a "(2)" count -- the
    # single-item menu's action text ("Add to Favorites") never does.
    assert any("(2)" in text for text in seen_action_texts)


def test_filmstrip_batch_rating_sets_all_selected_to_same_value(qapp, qtbot):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/one.jpg"), _entry("C:/photos/two.jpg")])
    one = strip._item_by_path["C:/photos/one.jpg"]
    two = strip._item_by_path["C:/photos/two.jpg"]
    one.setSelected(True)
    two.setSelected(True)

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            submenu = action.menu()
            if submenu is None:
                continue
            for sub_action in submenu.actions():
                if sub_action.text() == "★★★ (3)":
                    return sub_action
        return None

    with patch.object(QMenu, "exec", fake_exec):
        with qtbot.waitSignal(strip.rating_batch_changed) as blocker:
            strip._show_context_menu(strip._list.visualItemRect(one).center())

    paths, rating = blocker.args
    assert set(paths) == {"C:/photos/one.jpg", "C:/photos/two.jpg"}
    assert rating == 3


def test_filmstrip_batch_flag_sets_all_selected_to_same_value(qapp, qtbot):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/one.jpg"), _entry("C:/photos/two.jpg")])
    one = strip._item_by_path["C:/photos/one.jpg"]
    two = strip._item_by_path["C:/photos/two.jpg"]
    one.setSelected(True)
    two.setSelected(True)

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            if action.text().startswith("Flag as Reject"):
                return action
        return None

    with patch.object(QMenu, "exec", fake_exec):
        with qtbot.waitSignal(strip.flag_batch_changed) as blocker:
            strip._show_context_menu(strip._list.visualItemRect(one).center())

    paths, flag = blocker.args
    assert set(paths) == {"C:/photos/one.jpg", "C:/photos/two.jpg"}
    assert flag == "reject"


def test_filmstrip_batch_favorite_shows_add_label_for_mixed_selection_and_targets_all(
    qapp, qtbot
):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    favorited = _entry("C:/photos/one.jpg")
    favorited["favorite"] = True
    strip.set_entries([favorited, _entry("C:/photos/two.jpg")])
    one = strip._item_by_path["C:/photos/one.jpg"]
    two = strip._item_by_path["C:/photos/two.jpg"]
    one.setSelected(True)
    two.setSelected(True)

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            if action.text().startswith("Add to Favorites"):
                return action
        return None

    with patch.object(QMenu, "exec", fake_exec):
        with qtbot.waitSignal(strip.favorite_batch_toggled) as blocker:
            strip._show_context_menu(strip._list.visualItemRect(one).center())

    paths, value = blocker.args
    # Mixed selection (one already favorited, one not) -> "Add to
    # Favorites" is offered, and clicking it favorites the WHOLE selection.
    assert set(paths) == {"C:/photos/one.jpg", "C:/photos/two.jpg"}
    assert value is True


def test_filmstrip_batch_favorite_shows_remove_label_when_all_already_favorited(
    qapp, qtbot
):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    first = _entry("C:/photos/one.jpg")
    first["favorite"] = True
    second = _entry("C:/photos/two.jpg")
    second["favorite"] = True
    strip.set_entries([first, second])
    one = strip._item_by_path["C:/photos/one.jpg"]
    two = strip._item_by_path["C:/photos/two.jpg"]
    one.setSelected(True)
    two.setSelected(True)

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            if action.text().startswith("Remove from Favorites"):
                return action
        return None

    with patch.object(QMenu, "exec", fake_exec):
        with qtbot.waitSignal(strip.favorite_batch_toggled) as blocker:
            strip._show_context_menu(strip._list.visualItemRect(one).center())

    paths, value = blocker.args
    assert set(paths) == {"C:/photos/one.jpg", "C:/photos/two.jpg"}
    assert value is False


def test_filmstrip_batch_add_keywords_is_additive_only(qapp, qtbot):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QInputDialog, QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    first = _entry("C:/photos/one.jpg")
    first["keywords"] = ["existing"]
    strip.set_entries([first, _entry("C:/photos/two.jpg")])
    one = strip._item_by_path["C:/photos/one.jpg"]
    two = strip._item_by_path["C:/photos/two.jpg"]
    one.setSelected(True)
    two.setSelected(True)

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            if action.text().startswith("Add Keywords to"):
                return action
        return None

    def fake_get_text(*_args, **_kwargs):
        return "sunset", True

    with patch.object(QMenu, "exec", fake_exec), patch.object(
        QInputDialog, "getText", staticmethod(fake_get_text)
    ):
        with qtbot.waitSignal(strip.keywords_batch_added) as blocker:
            strip._show_context_menu(strip._list.visualItemRect(one).center())

    paths, keywords = blocker.args
    assert set(paths) == {"C:/photos/one.jpg", "C:/photos/two.jpg"}
    # The batch signal carries only the NEW keywords to add -- the view
    # never reads/merges each item's existing keywords itself; that merge
    # (preserving "existing") happens controller-side (see
    # LibraryController.add_entries_keywords).
    assert keywords == ["sunset"]


def test_filmstrip_batch_add_to_collection_adds_every_selected_item(qapp, qtbot):
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries([_entry("C:/photos/one.jpg"), _entry("C:/photos/two.jpg")])
    strip.set_collections([{"id": "c1", "name": "Travel", "count": 0}])
    one = strip._item_by_path["C:/photos/one.jpg"]
    two = strip._item_by_path["C:/photos/two.jpg"]
    one.setSelected(True)
    two.setSelected(True)

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            submenu = action.menu()
            if submenu is None:
                continue
            for sub_action in submenu.actions():
                if sub_action.text() == "Travel":
                    return sub_action
        return None

    with patch.object(QMenu, "exec", fake_exec):
        with qtbot.waitSignal(strip.collection_batch_added) as blocker:
            strip._show_context_menu(strip._list.visualItemRect(one).center())

    paths, collection_id = blocker.args
    assert set(paths) == {"C:/photos/one.jpg", "C:/photos/two.jpg"}
    assert collection_id == "c1"


def test_filmstrip_right_click_outside_selection_falls_back_to_single_item_menu(
    qapp, qtbot
):
    """Right-clicking an item that is NOT part of the current multi-
    selection must act on that one item only, same as before multi-select
    existed -- not silently batch-apply to whatever else happens to be
    selected."""
    from unittest.mock import patch

    from PyQt6.QtWidgets import QMenu

    strip = FilmstripView()
    qtbot.addWidget(strip)
    strip.set_entries(
        [
            _entry("C:/photos/one.jpg"),
            _entry("C:/photos/two.jpg"),
            _entry("C:/photos/three.jpg"),
        ]
    )
    one = strip._item_by_path["C:/photos/one.jpg"]
    two = strip._item_by_path["C:/photos/two.jpg"]
    three = strip._item_by_path["C:/photos/three.jpg"]
    one.setSelected(True)
    two.setSelected(True)
    # three.jpg is right-clicked but is NOT part of the selection.

    def fake_exec(self, *_args, **_kwargs):
        for action in self.actions():
            if action.text() == "Flag as Pick":
                return action
        return None

    with patch.object(QMenu, "exec", fake_exec):
        with qtbot.waitSignal(strip.flag_changed) as blocker:
            strip._show_context_menu(strip._list.visualItemRect(three).center())

    assert blocker.args == ["C:/photos/three.jpg", "pick"]


def test_workspace_header_emits_primary_actions(qapp, qtbot):
    header = WorkspaceHeader()
    qtbot.addWidget(header)
    with qtbot.waitSignal(header.undo_requested):
        header._undo_button.click()
    with qtbot.waitSignal(header.redo_requested):
        header._redo_button.click()
    with qtbot.waitSignal(header.export_requested):
        header._export_button.click()
    assert header._compare_button.isEnabled() is False
    with qtbot.waitSignal(header.workspace_changed) as changed:
        header._library_tab.click()
    assert changed.args == ["library"]
    assert header._library_tab.isChecked() is True
    assert header._develop_tab.isChecked() is False


def test_histogram_accepts_rgb_image(qapp, qtbot):
    histogram = HistogramWidget()
    qtbot.addWidget(histogram)
    histogram.set_image(np.full((40, 60, 3), 0.5, dtype=np.float32))
    assert len(histogram._channels) == 3
    assert all(channel.sum() > 0 for channel in histogram._channels)

