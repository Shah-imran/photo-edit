# Collections (minimal v1 flat album list, JSON via LibraryCatalogService)

Related roadmap: Phase A, "Library DAM and workspace chrome" (PDF
sections 8-9, 24; parts of 1-2) in `docs/planning/PRODUCT_ROADMAP.md`
-- the bullet "Sort/filter; optional simple **collections** or folders
(subset of Albums/Album folders)." This is the last unbuilt piece of
Phase A's bullet list; Ratings, pick/reject flags, keywords, the
search box, and the filmstrip/next-previous-photo pieces of that phase
were already **Done** (see the four `2026-10-13-*.md` notes preceding
this one). This note closes the remaining "collections" gap.

## 1. Problem, goal, and non-goals

**Problem.** There was no way to group a subset of images in one
library under a user-chosen name, independent of favorite/rating/flag/
keyword state. The PDF's Edit menu lists a full Albums feature
(create folder/album, delete, rename, leave, abuse report, target
album, add photo, share) -- building that whole surface is explicitly
out of scope for Phase A, which only asks for "optional simple
collections or folders (subset of Albums/Album folders)."

**Goal.** A single flat list of named collections per library:
create, rename, delete a collection; add/remove an image to/from a
collection; a sidebar row per collection (name + image count) next to
the three existing smart collections (All Photos/Favorites/Recently
Added); a filmstrip filter mode that shows only a collection's
members; and a right-click "Add to Collection" context-menu action.

**Non-goals (deliberate v1 scope boundary, not an oversight):**

- **No nesting / album folders.** Collections are a single flat list
  per library -- no "folder containing albums" hierarchy the PDF's
  Album-folder concept implies. A `CollectionRecord` has no `parent_id`
  and no collection can contain another.
- **No drag-and-drop.** Adding an image to a collection is done only
  through the right-click "Add to Collection" context-menu action (see
  Design below) -- no drag a thumbnail onto a sidebar row.
- **No multi-select batch-add.** Checked directly before writing this
  note, the same way the keywords slice checked it: grepping
  `SelectionMode`/`ExtendedSelection`/`MultiSelection` across `src/`
  still returns no results. Neither the filmstrip's `QListWidget` nor
  the library grid supports selecting more than one item at a time, so
  there is no multi-select UI to batch-add from in the first place --
  this isn't a feature being deferred so much as one with no selection
  mechanism to build on, exactly as the keywords slice's own non-goals
  section already documented for keyword editing.
- **No smart/rule-based collections.** A collection's membership is
  exactly the set of entries whose `collection_ids` contains its id --
  set directly by the user through add/remove, never computed from a
  rule (e.g. "all 5-star landscapes"). The three existing smart
  collections (All/Favorites/Recent) are untouched and remain
  rule-based exactly as before; this slice does not generalize that
  mechanism or let a user define their own rule-based collection.
- **No collection reordering.** Collections render in catalog/creation
  order (the order `LibraryRecord.collections` holds them in); there is
  no drag-to-reorder or explicit `order`/`position` field.
- **No cross-library collections.** `CollectionRecord` is scoped
  entirely inside one `LibraryRecord` (see Design below) -- a
  collection's id is only ever looked up within the library that owns
  it. An image that exists in two different libraries (the catalog
  already supports this -- see `test_same_file_can_exist_in_multiple_
  libraries`) has entirely independent `collection_ids` in each.
- **No collection-delete confirmation dialog.** Deleting a collection
  is treated as a low-stakes, easily-undoable-by-recreating action (the
  collection's *name* can trivially be recreated; only membership is
  lost, and re-adding a handful of images back to a recreated
  collection is cheap) -- `LibraryCatalogService.delete_collection()`
  and `LibraryController.delete_collection()` both exist and are fully
  tested, but no UI control calls them in this v1 (see "What shipped in
  the view layer" below). A future slice can wire a delete affordance
  (with or without a confirmation prompt) without touching the service/
  controller layer at all.
- **No rename UI either**, for the same reason: `rename_collection()`
  exists end-to-end (service + controller) and is tested, but no
  sidebar control calls it yet. Only **create** has a UI entry point in
  this v1 (the "+ New Collection" row and the context menu's "New
  Collection..." action) -- matching the task's own description of the
  sidebar extension (one row per collection, a count badge, and a
  trailing "+ New Collection" row) literally, rather than speculatively
  building rename/delete affordances the brief didn't ask for.

This completes Phase A's "collections" bullet for its stated minimal
scope. The Phase A bullet and the Coverage table's rows 1-2 and 24 are
updated below to reflect **Done (v1 scope)** with the above list
called out as a deliberate, documented gap -- matching the tone of
every other deferred-feature call-out already in that table.

## 2. Design

### Persistence: `CollectionRecord`, scoped inside `LibraryRecord`

```python
@dataclass
class CollectionRecord:
    id: str
    name: str
```

`id` is `uuid.uuid4().hex`, the same convention `LibraryRecord.id` and
`LibraryEntry`'s own ids already use (confirmed by reading every
`uuid.uuid4()` call site in `library_catalog_service.py` before picking
this -- there is exactly one existing id-generation convention in this
file, and this reuses it rather than inventing a second one, e.g. an
incrementing int).

`LibraryRecord` gained a new field:

```python
collections: list[CollectionRecord] = field(default_factory=list)
```

alongside its existing `entries: list[LibraryEntry] =
field(default_factory=list)` -- collections are scoped **inside** one
library, never shared or looked up across library boundaries, which is
exactly where the "no cross-library collections" non-goal lives
structurally: a `delete_collection(library_id, collection_id)` call
only ever touches `self.get_library(library_id).collections` and that
same library's `entries`, never any other library's.

Membership is **not** a reverse-lookup/scan of each collection for its
member paths. It's stored directly on `LibraryEntry`:

```python
collection_ids: list[str] = field(default_factory=list)
```

mirroring `keywords: list[str] = field(default_factory=list)`'s own
non-bare-mutable-default precedent (see
docs/planning/implementation-notes/2026-10-13-keywords.md's "mutable-
default-factory bug" section for why `= []` would be a footgun here
too -- the same reasoning applies verbatim to `collection_ids`). This
was the research pass's explicit recommendation over scanning every
collection's membership list for a given path: O(1) "is this entry in
collection X" lookups via `collection_id in entry.collection_ids`,
consistent with how every other per-entry field (`favorite`, `rating`,
`flag`, `keywords`) already lives directly on `LibraryEntry`, and it
keeps `LibraryController._entry_payload()`/`_on_thumbnail_ready()`
simplest -- both payload dicts just add one more
`"collection_ids": entry.collection_ids` line, the same shape as the
existing `"keywords": entry.keywords` line immediately above it.

### `_normalize_collection_ids(value) -> list[str]`

A new module-level helper in `library_catalog_service.py`, used in both
`LibraryEntry.from_dict()` and every service method that mutates
`collection_ids`:

```python
def _normalize_collection_ids(value) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned
```

This deliberately differs from `_normalize_keywords` in exactly one
way: dedup here is a **plain, case-sensitive** exact-string dedup, not
case-insensitive. Keywords are user-facing free text where "Sunset"
and "sunset" are the same real-world tag; `collection_ids` are opaque
uuid tokens where case sensitivity is simply correct (`"AbC" !=
"abc"` as ids) and case-insensitive folding would be actively wrong.
Otherwise it mirrors `_normalize_keywords`'s "coerce, never raise"
style exactly: non-list input -> `[]`; items coerced to `str` and
stripped; empty/duplicate entries dropped; insertion order preserved.

This helper does **not** check that each id actually names a
collection still present in the library -- that's `delete_collection`'s
job (see below), not a load-time concern. A catalog file hand-edited
to contain a `collection_ids` entry for a collection that was deleted
by some other means would simply carry a dangling reference until the
next legitimate `delete_collection()` call cleans it up, or forever if
no such call ever targets that id again -- this is an accepted,
documented edge case (see Nuances), not a guarantee this helper makes.

### `LibraryCatalogService` methods

All six, each defensive/never-raise on bad input, matching every
existing setter's style:

- `list_collections(library_id) -> list[CollectionRecord]` -- `[]` on
  an unknown `library_id` (no `KeyError`, unlike the internal
  `_require_library`-based methods -- this is a read-only, public,
  "give me the list or an empty list" query, the same relaxed contract
  `list_libraries()` already has).
- `create_collection(library_id, name) -> Optional[CollectionRecord]`
  -- `None` on an unknown `library_id` or an empty/whitespace-only
  `name` (there's no sensible auto-generated default name the way
  `next_default_library_name()` exists for libraries, so this rejects
  rather than inventing one). **Duplicate names are explicitly
  allowed** -- no uniqueness check, a deliberate "your call" decision:
  nothing else in this codebase stops two libraries from sharing a
  name either, and enforcing uniqueness would need a user-facing error
  path ("that name is taken") this minimal v1 doesn't build.
- `rename_collection(library_id, collection_id, new_name) ->
  Optional[CollectionRecord]` -- returns the collection unchanged (not
  `None`) on an empty/whitespace-only `new_name`, matching
  `set_entry_keywords`'s "no-op on unchanged/invalid input, still
  return the current state" shape; `None` only on an unknown library or
  collection id.
- `delete_collection(library_id, collection_id) -> bool` -- `True` iff
  a collection was actually removed. **Also strips the deleted id out
  of every entry's `collection_ids`** in the same library, so no
  dangling reference survives:

  ```python
  library.collections = [c for c in library.collections if c.id != collection_id]
  for entry in library.entries:
      if collection_id in entry.collection_ids:
          entry.collection_ids = [cid for cid in entry.collection_ids if cid != collection_id]
  ```

  This is the one piece of this slice with real correctness risk if
  skipped -- pinned directly by
  `test_delete_collection_removes_it_and_strips_dangling_entry_
  references` (see Test plan).
- `add_entry_to_collection(library_id, path, collection_id) ->
  Optional[LibraryEntry]` -- `None` on an unknown library, unknown
  collection id, or unknown path; a no-op (no save, entry returned
  unchanged) if the entry is already a member.
- `remove_entry_from_collection(library_id, path, collection_id) ->
  Optional[LibraryEntry]` -- `None` on an unknown library or path
  (removing a nonexistent/already-unknown collection id from an
  entry's list is harmless and intentionally **not** validated against
  `list_collections` the way `add_entry_to_collection` is, since
  "remove something that isn't there" is inherently a no-op either
  way); a no-op (no save) if the entry wasn't a member.

### `LibraryController`

Six methods mirroring the catalog service 1:1 (`create_collection`,
`rename_collection`, `delete_collection`, `add_entry_to_collection`,
`remove_entry_from_collection`, plus `list_collections` is read via
`self._catalog_service.list_collections(...)` directly where needed --
no controller wrapper was needed since nothing reads it outside
`_emit_collections()`), guarding on `self._current_library_id`/
required args, delegating to the catalog service, then refreshing
views -- mirroring `set_entry_favorite`/`set_entry_keywords`'s own
guard-delegate-refresh shape exactly.

Two more controller-only methods exist purely to make the context
menu's UX work in one call instead of two round-trips:

- `set_entry_collection_membership(file_path, collection_id,
  is_member)` -- the single slot the context menu's checkable "Add to
  Collection" submenu action connects to; `is_member=True` calls
  `add_entry_to_collection`, `False` calls `remove_entry_from_collection`.
  This exists because a checkable `QAction`'s natural signal carries
  only "this was clicked," and the view already knows the *target*
  membership state (the inverse of what was checked before the click)
  -- translating that into which of two catalog-service calls to make
  is business logic that belongs in the controller, not the view.
- `create_collection_with_entry(file_path, name)` -- backs the context
  menu's "New Collection..." action. The problem it solves: when a
  brand-new collection doesn't exist yet, there's no id for the view to
  pass back in a follow-up `add_entry_to_collection` call. Rather than
  have `create_collection`'s signal somehow carry a path through back
  to the view and have the view issue a second call, the controller
  does both steps (`create_collection` then
  `add_entry_to_collection` against the id it just got back) in one
  call, emitting exactly the refresh signals a normal create + add
  sequence would.

### New signal: `collections_changed`, separate from `libraries_changed`

`_emit_libraries()`'s existing per-library aggregate counts
(`count`, `favorite_count`) are a **fixed** set of counters -- every
library always has exactly those two numbers. Collections are a
**dynamic, user-created list** with no fixed size, so bolting a
variable-length list onto `libraries_changed`'s payload would change
that signal's shape in a way nothing downstream expects. Instead, a new
signal:

```python
collections_changed = pyqtSignal(object)  # list[dict] -- {"id", "name", "count"}
```

is emitted by a new `_emit_collections()` helper, structurally mirroring
`_emit_libraries()`: builds a list of dicts (`id`, `name`, and a
per-collection image `count` computed as
`sum(1 for entry in library.entries if collection.id in
entry.collection_ids)`) for the *current* library's collections only
(matching "no cross-library collections" -- there is no library
selector in this payload the way `libraries_changed`'s `current_
library_id` argument lets a consumer tell libraries apart; collections
are only ever shown for whichever library is currently active).
`_emit_collections()` is called everywhere `_emit_libraries()` already
is (`initialize()`, `select_library()`, `create_library()`,
`remove_library()`) plus after every collection CRUD/membership
mutation, so the sidebar and filmstrip's cached collection list never
go stale.

### View wiring: `collection_selected` reused as-is, `main_window.py`'s filter wiring needed **zero** changes

Before writing any view code, the existing wiring was re-read
end-to-end to confirm the task brief's own assumption:
`LibraryView.collection_selected = pyqtSignal(str)` is already emitted
by the three existing smart-collection `QToolButton` rows (`"all"`/
`"favorites"`/`"recent"`), and `main_window.py` connects it directly:

```python
self._library_view.collection_selected.connect(self._filmstrip_view.set_filter)
```

So the new per-collection sidebar rows built for this slice (in
`LibraryView.set_collections()`) emit that **exact same signal**, with
`f"collection:{collection_id}"` as the payload, instead of inventing a
second signal:

```python
button.clicked.connect(
    lambda _checked=False, cid=collection_id: self.collection_selected.emit(
        f"collection:{cid}"
    )
)
```

`FilmstripView.set_filter()` was extended with one more branch
recognizing the `"collection:<id>"` shape and `_render_entries()` with
one more filter branch matching it against `entry.get("collection_ids",
[])`, mirroring the existing `favorites` branch's shape exactly:

```python
elif self._filter_mode.startswith("collection:"):
    collection_id = self._filter_mode[len("collection:"):]
    entries = [e for e in entries if collection_id in (e.get("collection_ids") or [])]
```

Because the string already carries everything `set_filter` needs and
flows through the identical signal/slot path the three smart
collections use, **`main_window.py` needed no changes at all** for
filter wiring -- confirmed by re-reading that connect call before and
after this slice; it is byte-for-byte unchanged. `main_window.py` *did*
need new lines for: `collections_changed` -> `LibraryView.set_collections`
and -> `FilmstripView.set_collections` (two new connects, since both
views need the list -- the sidebar to render rows, the filmstrip to
populate the context menu's submenu); `LibraryView.
create_collection_requested` -> `LibraryController.create_collection`;
`FilmstripView.collection_membership_toggled` ->
`LibraryController.set_entry_collection_membership`; and
`FilmstripView.new_collection_for_entry_requested` ->
`LibraryController.create_collection_with_entry`. None of these touch
or replace any existing connection.

### What shipped in the view layer

**`LibraryView`** (sidebar): extended the existing block (the three
hardcoded `QToolButton` rows) with a new `set_collections(collections)`
method that clears and rebuilds one row per user collection into a
dedicated `self._collections_layout` container sitting directly below
the three fixed rows, each row a `QToolButton` (name + folder icon) +
a `QLabel` count badge, styled identically to the fixed rows' own
`QToolButton`/count-label pair. A trailing `"+ New Collection"`
`QToolButton` below the dynamic container opens
`QInputDialog.getText(self, "New Collection", "Collection name:")` and
emits the new `create_collection_requested(str)` signal with the
trimmed name on accept with non-blank text; nothing is emitted on
cancel or a blank name.

**`FilmstripView`** (context menu + filter): the existing
`_show_context_menu()` (already home to Favorite/Rating/Flag/Keywords
actions -- see docs/planning/implementation-notes/2026-10-13-
keywords.md) gained one more submenu, `"Add to Collection"`, with one
checkable `QAction` per collection the view's new `set_collections()`
cache holds (checked iff the item's `UserRole + 6` data -- the new
per-item storage slot for `collection_ids`, the next unused offset
after keywords' `UserRole + 5` -- contains that collection's id), plus
a trailing `"New Collection..."` action. Selecting an existing
collection's (un)checked action emits
`collection_membership_toggled(path, collection_id, target_state)`
where `target_state` is the inverse of whatever was checked before the
click; selecting "New Collection..." opens the same
`QInputDialog.getText` pattern the sidebar's own "+ New Collection" and
Keywords' own "Edit Keywords..." already use, emitting
`new_collection_for_entry_requested(path, name)` on accept with
non-blank text.

**Existing context-menu precedent was found and reused, not built
from scratch.** `FilmstripView._show_context_menu()` already existed
(Favorite toggle, a "Set Rating" submenu, flat Pick/Reject/Remove-Flag
actions, and an "Edit Keywords..." item, all built across the Ratings/
Flags/Keywords slices) -- this slice's "Add to Collection" submenu was
added in place, in the same `QMenu`, using the exact same
`menu.addMenu(...)`/`action.setCheckable(True)`/`selected = menu.exec(...)`
pattern the existing "Set Rating" submenu already demonstrated for a
collapsible list of options. No new menu-building idiom was invented.

## 3. Contracts

- `CollectionRecord(id: str, name: str)` -- new dataclass in
  `library_catalog_service.py`, `to_dict()`/`from_dict()` round-trip.
  `id` via `uuid.uuid4().hex`.
- `LibraryRecord.collections: list[CollectionRecord] =
  field(default_factory=list)` -- new field, threaded through
  `to_dict()`/`from_dict()`.
- `LibraryEntry.collection_ids: list[str] = field(default_factory=list)`
  -- new field, threaded through `to_dict()`/`from_dict()` via a new
  `_normalize_collection_ids()` helper. Not a bare `= []` default (same
  mutable-default-factory reasoning as `keywords`).
- `LibraryCatalogService`: `list_collections(library_id) ->
  list[CollectionRecord]`; `create_collection(library_id, name) ->
  Optional[CollectionRecord]`; `rename_collection(library_id,
  collection_id, new_name) -> Optional[CollectionRecord]`;
  `delete_collection(library_id, collection_id) -> bool` (strips
  dangling `collection_ids` references); `add_entry_to_collection(
  library_id, path, collection_id) -> Optional[LibraryEntry]`;
  `remove_entry_from_collection(library_id, path, collection_id) ->
  Optional[LibraryEntry]`. All defensive/never-raise.
- `LibraryController`: `create_collection(name)`, `rename_collection(
  collection_id, name)`, `delete_collection(collection_id)`,
  `add_entry_to_collection(file_path, collection_id)`,
  `remove_entry_from_collection(file_path, collection_id)`,
  `set_entry_collection_membership(file_path, collection_id,
  is_member)`, `create_collection_with_entry(file_path, name)`. Each
  guards on `_current_library_id`/required args and delegates to the
  catalog service, then re-emits `collections_changed` and (for
  membership-affecting calls) re-triggers `_rebuild_entries_for_
  current_library()`.
- `LibraryController.collections_changed = pyqtSignal(object)` -- new
  signal, `list[dict]` of `{"id", "name", "count"}` for the current
  library's collections.
- `LibraryController._entry_payload()`/`_on_thumbnail_ready()` per-entry
  payload dicts both now include `"collection_ids": entry.collection_ids`.
- `LibraryView.set_collections(collections: list[dict]) -> None` --
  rebuilds sidebar rows; `create_collection_requested = pyqtSignal(str)`
  -- new signal, emitted by the "+ New Collection" row.
- `FilmstripView.set_collections(collections: list[dict]) -> None` --
  caches the list for the context menu; `collection_membership_toggled
  = pyqtSignal(str, str, bool)` (path, collection_id, target member
  state) and `new_collection_for_entry_requested = pyqtSignal(str, str)`
  (path, new collection name) -- two new signals from the context
  menu's "Add to Collection" submenu.
- `FilmstripView.set_filter(mode: str)` now also accepts
  `f"collection:{collection_id}"`, filtering by
  `collection_id in entry.get("collection_ids", [])`. `FilmstripView`
  stores an item's `collection_ids` at `Qt.ItemDataRole.UserRole + 6`
  (the next unused offset after keywords' `UserRole + 5`).
- `main_window.py`'s existing `collection_selected -> set_filter`
  connection is **unchanged** -- no new signal was needed for filter
  routing (see Design above). New connects: `collections_changed` ->
  both views' `set_collections`; `create_collection_requested` ->
  `LibraryController.create_collection`; `collection_membership_toggled`
  -> `LibraryController.set_entry_collection_membership`; `new_
  collection_for_entry_requested` -> `LibraryController.
  create_collection_with_entry`.
- No existing method's signature or behavior changed. Favorite's,
  Rating's, Flag's, and Keywords' item text, tooltip prefixes,
  `UserRole` offsets, context-menu actions, and signals are all
  unmodified.

## 4. Nuances and failure modes

**Old catalog files predating this slice.** A catalog JSON file
written before this slice has no `"collections"` key on any library
and no `"collection_ids"` key on any entry. `LibraryRecord.from_dict()`'s
`payload.get("collections", [])` and `LibraryEntry.from_dict()`'s
`payload.get("collection_ids", [])` both already default to `[]`
before their respective normalizers even run, so loading an old
catalog produces libraries with no collections and entries with
`collection_ids == []`, with no migration step and no error. Pinned by
`test_collections_missing_from_old_catalog_payload_defaults_to_empty`.

**Deleting a collection strips membership everywhere in that library,
immediately.** There is no "orphaned collection id" state reachable
through normal use -- `delete_collection()` always walks every entry in
the same library and removes the id from `collection_ids` in the same
save. The only way a dangling `collection_ids` entry could exist is a
hand-edited catalog file (see `_normalize_collection_ids`'s own
docstring) -- that's accepted as inert leftover data, not a crash risk,
since nothing anywhere does an unguarded lookup of a collection by id
without handling "not found."

**Duplicate collection names are allowed and can be confusing.**
Creating two collections both named "Travel" is permitted (see
Design); the sidebar will show two rows that read identically, counts
aside, distinguished only by which images are actually in each. This
is a deliberate v1 simplicity choice, not a bug -- the task brief
explicitly left this as a judgment call, and enforcing uniqueness
would need a user-facing rejection path this minimal slice doesn't
build.

**The `"collection:<id>"` filter string referencing an id that no
longer exists.** If a collection is deleted while the filmstrip is
still filtered to it, `set_filter()`'s new branch doesn't special-case
"this id doesn't exist" -- it just filters by
`collection_id in entry.get("collection_ids", [])`, which is trivially
`[]` for every entry once `delete_collection()` has stripped that id
out of all of them, so the filmstrip correctly (if not especially
gracefully) shows zero results rather than erroring. The filter mode
itself isn't automatically reset to `"all"` on delete -- there's no UI
to delete a collection in this v1 in the first place (see Non-goals),
so this situation isn't reachable through the shipped UI, only through
direct `LibraryController.delete_collection()` calls (e.g. tests, or a
future slice that does add a delete control).

**Favorite/Rating/Flag/Keywords regression.** Every pre-existing test
for those four features across the catalog-service, controller, and
view layers was left completely unmodified and still passes,
confirming this slice's additions didn't silently alter any of them.

**No multi-select to batch-add across.** Confirmed by grepping `src/`
for `SelectionMode`/`ExtendedSelection`/`MultiSelection` before writing
this note, exactly as the keywords slice's own note already documented
-- still no match anywhere. A future multi-select slice would need to
design batch semantics for all five per-entry metadata concerns
(favorite/rating/flag/keywords/collection membership) together, not
collections alone.

## 5. Test plan

- `tests/unit/test_services/test_library_catalog_service.py`: full CRUD
  coverage (`test_create_collection_returns_record_and_appears_in_list`,
  `test_create_collection_rejects_empty_or_whitespace_name`,
  `test_create_collection_unknown_library_returns_none`,
  `test_create_collection_allows_duplicate_names`,
  `test_rename_collection_updates_name`,
  `test_rename_collection_unknown_id_is_a_no_op`,
  `test_rename_collection_rejects_empty_name`,
  `test_list_collections_unknown_library_returns_empty_list`,
  `test_add_entry_to_collection_sets_membership`,
  `test_add_entry_to_collection_is_a_no_op_when_already_a_member`,
  `test_add_entry_to_collection_unknown_collection_or_path_returns_none`,
  `test_remove_entry_from_collection_clears_membership`,
  `test_remove_entry_from_collection_is_a_no_op_when_not_a_member`,
  `test_delete_collection_unknown_id_returns_false`,
  `test_delete_collection_unknown_library_returns_false`,
  `test_collections_and_membership_survive_reload`,
  `test_collections_missing_from_old_catalog_payload_defaults_to_empty`,
  `test_normalize_collection_ids_rejects_non_list_input`,
  `test_normalize_collection_ids_dedupes_and_drops_empty`), plus the
  crux regression test,
  **`test_delete_collection_removes_it_and_strips_dangling_entry_
  references`**, which creates a collection, adds an entry to it,
  deletes the collection, and asserts both that the collection is gone
  from `list_collections()` **and** that the same entry's
  `collection_ids` no longer contains that id -- passed on the first
  run, confirming the strip-dangling-references logic in
  `delete_collection()` works as designed.
- `tests/unit/test_controllers/test_library_controller.py`:
  `test_create_collection_delegates_and_emits_collections_changed`,
  `test_add_entry_to_collection_updates_count_and_entry_payload`,
  `test_remove_entry_from_collection_clears_entry_payload`,
  `test_set_entry_collection_membership_toggles_both_ways`,
  `test_create_collection_with_entry_creates_and_adds_in_one_call`,
  `test_delete_collection_strips_dangling_references_and_refreshes_
  entries` (controller-level counterpart to the service-level crux
  test above, asserting the re-emitted `entries_rebuilt` payload
  reflects the stripped membership), and
  **`test_entry_payload_and_thumbnail_ready_payload_have_identical_
  keys`** -- the regression guard the task brief asked for: it imports
  one image (triggering both `_entry_payload()`'s initial payload via
  `entries_rebuilt` and `_on_thumbnail_ready()`'s follow-up payload via
  `entry_thumbnail_updated`) and asserts the two payload dicts' key
  sets are exactly equal, so a future edit that adds/renames a key in
  one of the two payload-construction call sites but not the other
  fails this test immediately rather than silently drifting.
- `tests/unit/test_views/test_library_view.py`:
  `test_set_collections_renders_rows_with_counts`,
  `test_set_collections_clears_previous_rows_on_rebuild`,
  `test_clicking_collection_row_emits_collection_selected_with_prefix`
  (asserts the emitted string is exactly `"collection:<id>"`),
  `test_new_collection_button_prompts_and_emits_requested_name`,
  `test_new_collection_button_cancel_emits_nothing`,
  `test_new_collection_button_rejects_blank_name`.
- `tests/unit/test_views/test_workspace_widgets.py`:
  `test_filmstrip_set_filter_collection_mode_filters_by_collection_id`,
  `test_filmstrip_set_filter_unknown_mode_falls_back_to_all`,
  `test_filmstrip_context_menu_add_to_collection_toggles_membership_on`
  (asserts the action starts unchecked and the emitted bool is `True`),
  `test_filmstrip_context_menu_add_to_collection_toggles_membership_off`
  (asserts the action starts checked and the emitted bool is `False`),
  `test_filmstrip_context_menu_new_collection_prompts_and_emits`,
  `test_filmstrip_context_menu_new_collection_cancel_emits_nothing`.
- Explicit regression check: every pre-existing Favorite, Rating,
  Flag, and Keywords test across all four files above was re-run
  unmodified as part of the full suite and still passes (see
  Verification below).

## 6. Rollout

Purely additive: one new dataclass (`CollectionRecord`), two new
dataclass fields (`LibraryRecord.collections`,
`LibraryEntry.collection_ids`, both default-empty via
`field(default_factory=list)`, so every existing in-memory/freshly-
loaded library/entry is unaffected), six new catalog-service methods,
seven new controller methods plus one new controller signal
(`collections_changed`), two new dict keys added to the two existing
per-entry payload dict literals, two new `FilmstripView` signals plus
one new `UserRole` offset plus a context menu extended with one more
submenu (not replaced), one new `LibraryView` signal plus a new
`set_collections()` method and sidebar rows, and five new
`main_window.py` connect calls. No existing method's signature changed
and `main_window.py`'s pre-existing `collection_selected -> set_filter`
connection is untouched. A plain revert removes the feature entirely;
any `"collections"`/`"collection_ids"` keys already written to a
catalog file by this feature become inert, unread leftover JSON if the
feature is removed later -- the same revert-safety story Keywords,
Flags, Ratings, and "Import presets" documented before it.

## 7. Implementation summary

Added `CollectionRecord` and `LibraryRecord.collections: list[
CollectionRecord] = field(default_factory=list)`, plus
`LibraryEntry.collection_ids: list[str] = field(default_factory=list)`
and a new `_normalize_collection_ids()` module-level helper (all in
`src/services/library_catalog_service.py`), threaded through
`to_dict()`/`from_dict()` on both `CollectionRecord` and the existing
`LibraryRecord`/`LibraryEntry`. Added six `LibraryCatalogService`
methods (`list_collections`, `create_collection`, `rename_collection`,
`delete_collection`, `add_entry_to_collection`,
`remove_entry_from_collection`), each defensive/never-raise, with
`delete_collection` additionally stripping the deleted id out of every
entry's `collection_ids` in the same library.

Added a `collections_changed = pyqtSignal(object)` signal and a new
`_emit_collections()` helper (structurally mirroring `_emit_libraries()`)
to `LibraryController` (`src/controllers/library_controller.py`),
called everywhere `_emit_libraries()` already is plus after every
collection mutation; added seven controller methods
(`create_collection`, `rename_collection`, `delete_collection`,
`add_entry_to_collection`, `remove_entry_from_collection`,
`set_entry_collection_membership`, `create_collection_with_entry`)
mirroring the existing `set_entry_*` setters' guard-delegate-refresh
shape; added `"collection_ids": entry.collection_ids` to both
`_entry_payload()`'s and `_on_thumbnail_ready()`'s payload dicts.

Added `LibraryView.set_collections()` (`src/views/library_view.py`),
rebuilding one sidebar row per collection (name, folder icon, count
label) below the three existing smart-collection rows, plus a trailing
`"+ New Collection"` `QToolButton` backed by `QInputDialog.getText()`
emitting the new `create_collection_requested = pyqtSignal(str)`
signal. Each collection row's click reuses the existing
`collection_selected` signal, emitting `f"collection:{id}"`.

Extended `FilmstripView` (`src/views/widgets/filmstrip_view.py`):
`set_filter()`/`_render_entries()` gained a `"collection:<id>"` mode/
filter branch mirroring the existing `favorites` branch;
`_apply_entry_payload()` now also stores `collection_ids` at
`UserRole + 6`; `_show_context_menu()` gained an "Add to Collection"
submenu (one checkable action per collection plus "New Collection...")
reusing the existing `QMenu`/submenu pattern the "Set Rating" submenu
already established, emitting two new signals
(`collection_membership_toggled`, `new_collection_for_entry_requested`);
added a `set_collections()` cache method.

Added five `main_window.py` connect calls (two for
`collections_changed` fan-out to both views, and one each for
`create_collection_requested`, `collection_membership_toggled`, and
`new_collection_for_entry_requested`); the existing `collection_selected
-> FilmstripView.set_filter` connection needed **zero** changes.
Updated `docs/planning/PRODUCT_ROADMAP.md`'s Phase A bullet and the
Coverage table's rows 2 and 24 to mark the minimal-v1 collections
bullet **Done**, with every explicit non-goal called out as a
deliberate, documented gap.

**Deviation notes / "your call" decisions**, per the task brief's own
invitation:

1. `CollectionRecord.id` uses `uuid.uuid4().hex`, matching the one
   existing id-generation convention already used everywhere else in
   this file (`LibraryRecord.id`), rather than an incrementing int.
2. Duplicate collection names are allowed (no uniqueness check) -- see
   Design and Nuances above.
3. No rename or delete UI control was built, even though both methods
   exist end-to-end and are tested -- the sidebar extension described
   in the task brief's own section 3 only calls for create (rows +
   "+ New Collection"), and no delete-confirmation dialog was built at
   all (the brief explicitly said to "err toward NOT building" one).
4. An existing context-menu pattern (`FilmstripView._show_context_
   menu()`, already extended three times across the Ratings/Flags/
   Keywords slices) was found and reused -- no new menu idiom was
   introduced; "Add to Collection" uses the same `menu.addMenu(...)` +
   checkable-`QAction` style the existing "Set Rating" submenu already
   demonstrated.

Verification: new tests -- 18 added to
`tests/unit/test_services/test_library_catalog_service.py`, 7 added to
`tests/unit/test_controllers/test_library_controller.py`, 6 added to
`tests/unit/test_views/test_library_view.py`, 6 added to
`tests/unit/test_views/test_workspace_widgets.py` (37 new `def
test_...` functions in total, all passing on first run against the new
production code with no fixes needed). Complete suite run via
`QT_QPA_PLATFORM=offscreen python3 -m pytest -q --deselect
tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::
test_geometry_is_restored_on_next_launch` -- the first attempt hit the
known pre-existing, unrelated native-crash-at-interpreter-teardown
flake in `ProcessingWorker.stop` during a performance test's
`closeEvent` teardown (documented in the task brief as a known,
unrelated flake, not something introduced by this slice); a rerun
completed cleanly with **1420 passed, 1 skipped, 1 deselected in
181.77s**. The deselected test is the same pre-existing
offscreen-rendering geometry-restoration flake noted in prior
implementation notes; the 1 skipped test is pre-existing and unrelated.
No failures observed in the successful run, including no regression
in any pre-existing Favorite/Rating/Flag/Keywords test.

This completes Phase A's "Sort/filter; optional simple collections or
folders" bullet for its documented minimal v1 scope.
