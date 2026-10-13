"""Horizontal thumbnail strip synchronized with the active library."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.views.icons import line_icon


def _clamp_rating(value) -> int:
    """Coerce an incoming rating (e.g. from an entry payload) to 0..5."""
    try:
        rating = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(5, rating))


def _normalize_flag(value) -> str:
    """Coerce an incoming pick/reject flag (e.g. from an entry payload) to
    "none"/"pick"/"reject". Mirrors ``_clamp_rating``'s local-copy style in
    this file (and the equivalent helper in ``library_catalog_service.py``)
    -- never raises on missing/garbage data."""
    if value in ("pick", "reject"):
        return value
    return "none"


def _normalize_keywords_for_display(value) -> list[str]:
    """Coerce an incoming keyword list (e.g. from an entry payload) to a
    plain ``list[str]`` for display purposes. Final normalization/dedup
    happens on the catalog-service side (see
    ``library_catalog_service._normalize_keywords``); this local helper
    just needs to be defensive enough to build a tooltip/pre-filled dialog
    without raising on missing/malformed data."""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


class FilmstripView(QWidget):
    """A compact view of the active library's images."""

    image_selected = pyqtSignal(str)
    favorite_toggled = pyqtSignal(str, bool)
    rating_changed = pyqtSignal(str, int)
    flag_changed = pyqtSignal(str, str)
    keywords_changed = pyqtSignal(str, list)
    collection_membership_toggled = pyqtSignal(str, str, bool)
    new_collection_for_entry_requested = pyqtSignal(str, str)
    # Batch (multi-select) counterparts of the five signals above -- only
    # ever emitted from the context menu's MULTI-selection branch (see
    # ``_show_batch_context_menu``), never from the single-item branch,
    # which keeps emitting the plain signals above completely unchanged.
    # See docs/planning/implementation-notes/2026-10-13-multi-select-
    # batch-actions.md for why these are separate signals/controller
    # methods rather than the view looping the single-item signals.
    favorite_batch_toggled = pyqtSignal(list, bool)
    rating_batch_changed = pyqtSignal(list, int)
    flag_batch_changed = pyqtSignal(list, str)
    keywords_batch_added = pyqtSignal(list, list)
    collection_batch_added = pyqtSignal(list, str)
    THUMBNAIL_SIZE = QSize(88, 62)
    CELL_SIZE = QSize(104, 78)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("filmstripView")
        self.setMinimumHeight(112)
        self.setMaximumHeight(132)
        self._item_by_path: dict[str, QListWidgetItem] = {}
        self._suppress_selection = False
        self._entries: list[dict] = []
        self._filter_mode = "all"
        self._sort_mode = "added"
        self._search_text = ""
        self._collections: list[dict] = []

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
        self._search_edit = QLineEdit()
        self._search_edit.setObjectName("filmstripSearchEdit")
        self._search_edit.setPlaceholderText("Search photos...")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setFixedWidth(160)
        self._search_edit.setStyleSheet(
            "QLineEdit#filmstripSearchEdit {"
            " background: #2a2a2a; color: #e7e9ec; border: 1px solid #3a3a3a;"
            " border-radius: 4px; padding: 2px 6px; }"
        )
        self._search_edit.textChanged.connect(self.set_search_text)
        header.addWidget(self._search_edit)
        self._filter_button = QToolButton()
        self._filter_button.setText("Filter")
        self._filter_button.setIcon(line_icon("filter", "#c1cad4", 16))
        self._filter_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._filter_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        filter_menu = QMenu(self._filter_button)
        for label, mode in (("All Photos", "all"), ("Favorites", "favorites"), ("Recently Added", "recent")):
            action = QAction(label, filter_menu)
            action.triggered.connect(lambda _checked=False, value=mode: self.set_filter(value))
            filter_menu.addAction(action)
        self._filter_button.setMenu(filter_menu)
        header.addWidget(self._filter_button)

        self._sort_button = QToolButton()
        self._sort_button.setText("Sort: Date Added")
        self._sort_button.setIcon(line_icon("sort", "#c1cad4", 16))
        self._sort_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._sort_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        sort_menu = QMenu(self._sort_button)
        for label, mode in (("Date Added", "added"), ("File Name", "name")):
            action = QAction(label, sort_menu)
            action.triggered.connect(lambda _checked=False, value=mode: self.set_sort(value))
            sort_menu.addAction(action)
        self._sort_button.setMenu(sort_menu)
        self._sort_label = self._sort_button
        header.addWidget(self._sort_button)
        layout.addLayout(header)

        self._list = QListWidget()
        self._list.setObjectName("filmstripList")
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setFlow(QListWidget.Flow.LeftToRight)
        self._list.setWrapping(False)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Static)
        # Ctrl/Shift-click multi-select (see docs/planning/implementation-
        # notes/2026-10-13-multi-select-batch-actions.md). This is ADDITIVE
        # to, not a replacement for, the single "open in editor" flow below:
        # ``currentItemChanged`` still fires with whichever item was most
        # recently clicked/made current, exactly as it did under the
        # previous default ``SingleSelection`` mode, so a single click
        # still opens exactly one image in the editor unchanged. Qt's
        # ExtendedSelection mode gives Ctrl+click toggle, Shift+click
        # range-select, and Ctrl+A select-all for free -- none of that is
        # hand-rolled here.
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
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
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        self._list.currentItemChanged.connect(self._on_current_item_changed)
        layout.addWidget(self._list)

    def set_collections(self, collections: list[dict]) -> None:
        """Cache the current library's flat collection list for the
        context menu's "Add to Collection" submenu. Does not itself
        trigger a re-render -- it's only read when the context menu is
        opened."""
        self._collections = [dict(collection) for collection in collections]

    def set_context(self, source_name: str) -> None:
        """Update the active library name shown above the thumbnails."""
        self._source_label.setText(source_name or "Library")

    def set_entries(self, entries: list[dict]) -> None:
        self._entries = [dict(entry) for entry in entries]
        self._render_entries()

    def set_filter(self, mode: str) -> None:
        """Filter the strip using the smart-collection controls, or a
        user-created collection given as ``"collection:<id>"``.

        The three smart collections ("all"/"favorites"/"recent") and the
        dynamic per-collection mode share this one setter/signal rather
        than inventing a second signal for collections -- see
        docs/planning/implementation-notes/2026-10-13-collections.md.
        """
        if mode.startswith("collection:") and len(mode) > len("collection:"):
            self._filter_mode = mode
            self._filter_button.setText("Collection")
            self._render_entries()
            return
        if mode not in {"all", "favorites", "recent"}:
            mode = "all"
        self._filter_mode = mode
        self._filter_button.setText(
            {"all": "Filter", "favorites": "Favorites", "recent": "Recent"}[mode]
        )
        self._render_entries()

    def set_sort(self, mode: str) -> None:
        """Sort the strip by import order or file name."""
        self._sort_mode = "name" if mode == "name" else "added"
        self._sort_button.setText(
            "Sort: File Name" if self._sort_mode == "name" else "Sort: Date Added"
        )
        self._render_entries()

    def set_search_text(self, text: str) -> None:
        """Filter the strip by a case-insensitive filename substring.

        Normalizes via ``strip().lower()`` so leading/trailing whitespace
        typed mid-edit doesn't change matching (" sunset" behaves the same
        as "sunset"). Skips re-rendering when the normalized value is
        unchanged from the current ``_search_text``, mirroring the
        no-op-if-unchanged style used by the recent Favorite/Rating/Flag
        setters -- this guards against redundant renders when, e.g., a
        caller sets the same text twice, even though ``QLineEdit.textChanged``
        itself already only fires on an actual change to the widget's text.
        """
        normalized = text.strip().lower()
        if normalized == self._search_text:
            return
        self._search_text = normalized
        self._render_entries()

    def _render_entries(self) -> None:
        current_path = self.current_path()
        entries = list(self._entries)
        if self._filter_mode == "favorites":
            entries = [entry for entry in entries if entry.get("favorite", False)]
        elif self._filter_mode == "recent":
            entries.sort(key=lambda entry: str(entry.get("added_at", "")), reverse=True)
        elif self._filter_mode.startswith("collection:"):
            collection_id = self._filter_mode[len("collection:") :]
            entries = [
                entry
                for entry in entries
                if collection_id in (entry.get("collection_ids") or [])
            ]
        if self._search_text:
            entries = [
                entry
                for entry in entries
                if self._search_text in str(entry.get("filename") or entry.get("path", "")).lower()
            ]
        if self._sort_mode == "name":
            entries.sort(key=lambda entry: str(entry.get("filename") or entry.get("path", "")).casefold())
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
        for index, entry in enumerate(self._entries):
            if str(entry.get("path")) == path:
                merged = dict(entry)
                merged.update(payload)
                self._entries[index] = merged
                break
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

    def select_next(self) -> bool:
        """Move the current selection to the next photo in the CURRENTLY
        DISPLAYED (already filtered/sorted/searched) order.

        ``self._list`` is always populated in final, already-filtered-and
        -sorted order by ``_render_entries()``, so "next row in the list"
        is exactly "next photo in filmstrip order" -- no extra lookup into
        ``self._entries`` is needed. ``QListWidget.setCurrentRow`` fires the
        same ``currentItemChanged`` signal a click does, so
        ``image_selected`` is emitted naturally by ``_on_current_item_changed``.

        Returns True if the selection moved, False if the list is empty or
        the current row is already the last one (no wraparound, matching
        Lightroom's own non-wrapping next/previous behavior).
        """
        count = self._list.count()
        if count == 0:
            return False
        row = self._list.currentRow()
        if row >= count - 1:
            return False
        self._list.setCurrentRow(row + 1 if row >= 0 else 0)
        return True

    def select_previous(self) -> bool:
        """Mirror of ``select_next`` -- moves to the previous row, clamped
        at 0 (no wraparound). Returns False on an empty list or when
        already at the first row."""
        count = self._list.count()
        if count == 0:
            return False
        row = self._list.currentRow()
        if row <= 0:
            return False
        self._list.setCurrentRow(row - 1)
        return True

    def _apply_entry_payload(self, item: QListWidgetItem, payload: dict) -> None:
        thumbnail = payload.get("thumbnail")
        if thumbnail is not None:
            pixmap = QPixmap.fromImage(thumbnail)
        else:
            missing = payload.get("placeholder") == "missing"
            pixmap = self._placeholder_pixmap(missing)
        item.setIcon(QIcon(pixmap))
        favorite = bool(payload.get("favorite", False))
        rating = _clamp_rating(payload.get("rating", 0))
        flag = _normalize_flag(payload.get("flag", "none"))
        keywords = _normalize_keywords_for_display(payload.get("keywords", []))
        collection_ids = _normalize_keywords_for_display(payload.get("collection_ids", []))
        # Rating/flag/keywords are surfaced via the tooltip only -- the item
        # TEXT stays reserved for the existing favorite "★" marker and must
        # not be repurposed or overwritten here. See
        # docs/planning/implementation-notes/2026-10-13-ratings.md,
        # docs/planning/implementation-notes/2026-10-13-pick-reject-flags.md,
        # and docs/planning/implementation-notes/2026-10-13-keywords.md.
        item.setText("★" if favorite else "")
        tooltip = str(payload.get("tooltip") or Path(str(payload["path"])).name)
        prefix = ("Favorite\n" if favorite else "")
        if rating > 0:
            prefix += f"Rating: {'★' * rating}{'☆' * (5 - rating)}\n"
        if flag == "pick":
            prefix += "Pick\n"
        elif flag == "reject":
            prefix += "Rejected\n"
        if keywords:
            prefix += f"Keywords: {', '.join(keywords)}\n"
        item.setToolTip(prefix + tooltip)
        item.setData(Qt.ItemDataRole.UserRole + 1, payload.get("status"))
        item.setData(Qt.ItemDataRole.UserRole + 2, favorite)
        item.setData(Qt.ItemDataRole.UserRole + 3, rating)
        item.setData(Qt.ItemDataRole.UserRole + 4, flag)
        item.setData(Qt.ItemDataRole.UserRole + 5, keywords)
        item.setData(Qt.ItemDataRole.UserRole + 6, collection_ids)

    def _show_context_menu(self, position) -> None:
        item = self._list.itemAt(position)
        if item is None:
            return
        # Multi-select batch branch: only taken when the right-clicked item
        # is itself part of a selection of MORE than one item -- right-
        # clicking an item outside the current selection (or with nothing
        # selected at all, e.g. every pre-existing single-item test in this
        # suite, which never calls ``setSelected``) falls straight through
        # to the single-item branch below, completely unchanged. See
        # docs/planning/implementation-notes/2026-10-13-multi-select-
        # batch-actions.md.
        selected_items = [it for it in self._list.selectedItems() if it is not None]
        if len(selected_items) > 1 and item in selected_items:
            self._show_batch_context_menu(position, selected_items)
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        favorite = bool(item.data(Qt.ItemDataRole.UserRole + 2))
        flag = _normalize_flag(item.data(Qt.ItemDataRole.UserRole + 4))
        current_keywords = _normalize_keywords_for_display(
            item.data(Qt.ItemDataRole.UserRole + 5)
        )
        current_collection_ids = set(
            _normalize_keywords_for_display(item.data(Qt.ItemDataRole.UserRole + 6))
        )
        menu = QMenu(self)
        favorite_action = menu.addAction(
            "Remove from Favorites" if favorite else "Add to Favorites"
        )
        rating_menu = menu.addMenu("Set Rating")
        rating_actions: dict = {}
        for label, value in (
            ("No Rating", 0),
            ("★ (1)", 1),
            ("★★ (2)", 2),
            ("★★★ (3)", 3),
            ("★★★★ (4)", 4),
            ("★★★★★ (5)", 5),
        ):
            rating_action = rating_menu.addAction(label)
            rating_actions[rating_action] = value
        # Pick/Reject use three flat actions rather than a "Set Flag"
        # submenu (unlike Rating's six-option submenu): with only three
        # choices, a flat section reads more cleanly in this menu's
        # existing visual structure than a one-level-deeper submenu would.
        # "Remove Flag" is only shown when a flag is currently set, to
        # avoid offering a no-op action.
        pick_action = menu.addAction("Flag as Pick")
        reject_action = menu.addAction("Flag as Reject")
        remove_flag_action = menu.addAction("Remove Flag") if flag != "none" else None
        keywords_action = menu.addAction("Edit Keywords...")
        # "Add to Collection" submenu: one checkable action per existing
        # collection (checked = currently a member) plus a trailing
        # "New Collection..." entry. No existing collection/batch
        # context-menu precedent existed to mirror beyond this file's own
        # Favorite/Rating/Flag/Keywords actions, so this follows their
        # same flat QMenu/QAction style. See
        # docs/planning/implementation-notes/2026-10-13-collections.md.
        collection_menu = menu.addMenu("Add to Collection")
        collection_actions: dict = {}
        for collection in self._collections:
            collection_id = str(collection.get("id", ""))
            if not collection_id:
                continue
            action = collection_menu.addAction(str(collection.get("name", "Collection")))
            action.setCheckable(True)
            action.setChecked(collection_id in current_collection_ids)
            collection_actions[action] = collection_id
        if collection_actions:
            collection_menu.addSeparator()
        new_collection_action = collection_menu.addAction("New Collection...")
        selected = menu.exec(self._list.viewport().mapToGlobal(position))
        if selected is None or not path:
            return
        if selected is favorite_action:
            self.favorite_toggled.emit(str(path), not favorite)
        elif selected in rating_actions:
            self.rating_changed.emit(str(path), rating_actions[selected])
        elif selected is pick_action:
            self.flag_changed.emit(str(path), "pick")
        elif selected is reject_action:
            self.flag_changed.emit(str(path), "reject")
        elif remove_flag_action is not None and selected is remove_flag_action:
            self.flag_changed.emit(str(path), "none")
        elif selected is keywords_action:
            text, ok = QInputDialog.getText(
                self,
                "Edit Keywords",
                "Comma-separated keywords:",
                text=", ".join(current_keywords),
            )
            if not ok:
                return
            new_keywords = [piece.strip() for piece in text.split(",") if piece.strip()]
            self.keywords_changed.emit(str(path), new_keywords)
        elif selected in collection_actions:
            collection_id = collection_actions[selected]
            is_member = collection_id in current_collection_ids
            self.collection_membership_toggled.emit(str(path), collection_id, not is_member)
        elif selected is new_collection_action:
            name, ok = QInputDialog.getText(self, "New Collection", "Collection name:")
            if not ok:
                return
            clean_name = name.strip()
            if not clean_name:
                return
            self.new_collection_for_entry_requested.emit(str(path), clean_name)

    def _show_batch_context_menu(self, position, items: list[QListWidgetItem]) -> None:
        """The multi-selection counterpart of ``_show_context_menu``.

        Favorite/Rating/Flag/Collection apply to every selected item with
        the SAME chosen value (a plain "set" for the scalar fields, not a
        merge/offset); "Add Keywords..." is deliberately ADD-ONLY (each
        image's existing distinct keywords are preserved, new ones are
        appended) rather than a destructive full replace, since a batch
        replace across many images the user can't individually see the
        current keywords of is a correctness trap -- see
        docs/planning/implementation-notes/2026-10-13-multi-select-
        batch-actions.md.
        """
        paths = [str(it.data(Qt.ItemDataRole.UserRole)) for it in items if it.data(Qt.ItemDataRole.UserRole)]
        if not paths:
            return
        count = len(paths)
        favorites = [bool(it.data(Qt.ItemDataRole.UserRole + 2)) for it in items]
        all_favorite = bool(favorites) and all(favorites)
        menu = QMenu(self)
        # Tri-state favorite label: "standard file-manager" behavior for a
        # mixed-state batch toggle -- if ANY selected item isn't already a
        # favorite, offer to favorite ALL of them; only when every selected
        # item is already a favorite does the action flip to removing it
        # from all of them.
        favorite_action = menu.addAction(
            f"Remove from Favorites ({count})"
            if all_favorite
            else f"Add to Favorites ({count})"
        )
        rating_menu = menu.addMenu(f"Set Rating ({count})")
        rating_actions: dict = {}
        for label, value in (
            ("No Rating", 0),
            ("★ (1)", 1),
            ("★★ (2)", 2),
            ("★★★ (3)", 3),
            ("★★★★ (4)", 4),
            ("★★★★★ (5)", 5),
        ):
            rating_action = rating_menu.addAction(label)
            rating_actions[rating_action] = value
        pick_action = menu.addAction(f"Flag as Pick ({count})")
        reject_action = menu.addAction(f"Flag as Reject ({count})")
        remove_flag_action = menu.addAction(f"Remove Flag ({count})")
        keywords_action = menu.addAction(f"Add Keywords to {count} Photos...")
        collection_menu = menu.addMenu(f"Add to Collection ({count})")
        collection_actions: dict = {}
        for collection in self._collections:
            collection_id = str(collection.get("id", ""))
            if not collection_id:
                continue
            action = collection_menu.addAction(str(collection.get("name", "Collection")))
            collection_actions[action] = collection_id
        selected = menu.exec(self._list.viewport().mapToGlobal(position))
        if selected is None:
            return
        if selected is favorite_action:
            self.favorite_batch_toggled.emit(paths, not all_favorite)
        elif selected in rating_actions:
            self.rating_batch_changed.emit(paths, rating_actions[selected])
        elif selected is pick_action:
            self.flag_batch_changed.emit(paths, "pick")
        elif selected is reject_action:
            self.flag_batch_changed.emit(paths, "reject")
        elif selected is remove_flag_action:
            self.flag_batch_changed.emit(paths, "none")
        elif selected is keywords_action:
            text, ok = QInputDialog.getText(
                self,
                "Add Keywords",
                f"Comma-separated keywords to add to {count} photos:",
                text="",
            )
            if not ok:
                return
            new_keywords = [piece.strip() for piece in text.split(",") if piece.strip()]
            if new_keywords:
                self.keywords_batch_added.emit(paths, new_keywords)
        elif selected in collection_actions:
            self.collection_batch_added.emit(paths, collection_actions[selected])

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
