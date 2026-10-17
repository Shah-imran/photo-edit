# Multi-select + batch metadata actions (filmstrip)

Related roadmap: Phase A, "Library DAM and workspace chrome" (PDF
sections 8-9, 24) in `docs/planning/PRODUCT_ROADMAP.md`. The Ratings,
pick/reject flags, Keywords, and Collections slices
(`docs/planning/implementation-notes/2026-10-13-ratings.md`,
`2026-10-13-pick-reject-flags.md`, `2026-10-13-keywords.md`,
`2026-10-13-collections.md`) each explicitly deferred bulk/multi-select
as a non-goal, citing the same confirmed-by-grep fact: "neither the
filmstrip's `QListWidget` nor the library grid supports selecting more
than one item at a time." This slice closes that gap for the
filmstrip's per-entry metadata actions.

## 1. Problem, goal, and non-goals

**Problem.** Applying Favorite/Rating/Flag/Keywords/Collection
membership to a batch of images required repeating the same context-
menu action once per image, one at a time -- there was no selection
mechanism to act on more than one image per action at all.

**Goal.** Ctrl/Shift-click multi-select in the filmstrip, and a
right-click context menu that, when more than one item is selected,
batch-applies Favorite/Rating/Flag/Keywords/Collection-membership to
the whole selection in one action.

**Non-goals (deliberate v1 scope boundary):**

- **No multi-select in the main image viewer itself.** The viewer only
  ever shows one current image -- that invariant is explicitly
  preserved by this slice (see Design below): a single click still
  opens exactly one image in the editor, unchanged. Letting the main
  viewer itself show/edit more than one image at once is an entirely
  separate, much larger undertaking, out of scope here.
- **No batch export.** Lightroom's own "batch export with naming
  patterns" is a distinct, already-tracked future roadmap item, not
  this slice's job. This slice is specifically a *metadata* batch-
  actions feature.
- **No drag-to-multi-select rectangle marquee** beyond whatever
  `QAbstractItemView.SelectionMode.ExtendedSelection` gives for free.
  Qt's own Ctrl+click toggle, Shift+click range-select, and Ctrl+A
  select-all all come free from this one selection-mode setting --
  none of them are hand-rolled, and no additional marquee/rubber-band
  selection UI was built beyond what Qt's icon-mode view already does
  under `ExtendedSelection`.
- **No "select all"/keyboard-shortcut polish** beyond what Qt's
  standard `ExtendedSelection` mode already provides.
- **No multi-select in `LibraryView`'s thumbnail grid.** The task
  brief scoped this specifically to the filmstrip (where the existing
  per-entry context menu already lives); `LibraryView`'s
  `ResponsiveLibraryGrid` is unchanged and still single-selection.
- **No batch "New Collection..."** -- creating a brand-new collection
  and adding the whole selection to it in one action was left out; the
  batch "Add to Collection" submenu only lists already-existing
  collections. A user who wants a new collection for a batch can
  create it via the sidebar's existing "+ New Collection" row first
  (unaffected by this slice), then batch-add to it.
- **No batch rename/delete of collections**, matching Collections'
  own non-goals -- untouched by this slice.

## 2. Design

### Selection mode: `QAbstractItemView.SelectionMode.ExtendedSelection`

`FilmstripView._list` (a `QListWidget`) gained one line:

```python
self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
```

This is the only change to how the list selects items. Qt's own
`ExtendedSelection` mode gives Ctrl+click toggle, Shift+click
range-select, and Ctrl+A select-all for free -- none of that is
hand-rolled here, matching the brief's own instruction not to
reimplement what the Qt selection mode already provides.

### The single "open in editor" invariant is completely unchanged

This was the single most important thing to get right, and the
existing signal chain was traced end to end *before* making any
change: `self._list.currentItemChanged` is still connected to the
same, byte-for-byte-unchanged `_on_current_item_changed()` slot, which
still emits `image_selected(path)` for whichever item is now
`current` -- exactly the same as before `ExtendedSelection` was
enabled. `QListWidget.setCurrentRow`/a plain click still make exactly
one item `current` and fire `currentItemChanged` exactly once, the
same way they did under the Qt default `SingleSelection` mode.
Enabling `ExtendedSelection` only changes which items are *highlighted*
(`selectedItems()`) -- it does not change which single item is
*current*, and `_on_current_item_changed()` only ever reads
`current`/`previous`, never `selectedItems()`. `image_selected` flows
into `MainWindow._on_library_image_selected()` exactly as before (that
method's own source is unchanged), which still calls
`self._image_controller.load_image_async(file_path, ...)` for exactly
one path. Multi-select is strictly additive on top of this flow, never
a replacement for it -- pinned directly by
`test_filmstrip_single_click_still_opens_exactly_one_image_unregressed`,
the critical regression-prevention test the task brief asked for.

### Context menu: a new multi-item branch, the single-item branch left byte-for-byte unchanged

`_show_context_menu()` gained exactly one new branch at its top:

```python
selected_items = [it for it in self._list.selectedItems() if it is not None]
if len(selected_items) > 1 and item in selected_items:
    self._show_batch_context_menu(position, selected_items)
    return
```

Everything below that -- the entire pre-existing single-item
Favorite/Rating/Flag/Keywords/Collection menu-building and
signal-emitting code -- is **completely untouched**, not just
behaviorally equivalent but literally the same lines, still reachable
whenever the right-clicked item isn't part of a >1-item selection
(including every pre-existing test in this suite, none of which ever
calls `setSelected(True)`, so `selectedItems()` is empty for all of
them and they fall straight into this unchanged branch). This was a
deliberate implementation choice over unifying the two branches into
one parameterized code path: a literal "don't touch the existing
code" branch split is the lowest-risk way to guarantee the single-item
behavior these ~15 existing context-menu tests already pin cannot
regress, at the cost of a small amount of near-duplicate menu-building
code between `_show_context_menu()` and the new
`_show_batch_context_menu()`.

**Right-clicking an item outside the current selection falls back to
the single-item branch, not a batch of whatever else happens to be
selected.** If the user has two images selected and right-clicks a
*third*, unselected image, `item in selected_items` is `False`, so the
single-item branch runs against that third image only -- the same
"your call" UX decision most file managers make (right-click an
unselected item acts on that item, not your old selection). Pinned by
`test_filmstrip_right_click_outside_selection_falls_back_to_single_item_menu`.

### `_show_batch_context_menu(position, items)`

Builds a second `QMenu` with the batch-shaped equivalents of the five
existing actions, all labelled with the selection count for clarity
(e.g. `"Set Rating (3)"`, `"Add Keywords to 3 Photos..."`):

- **Favorite -- tri-state label, same UX most file managers use for a
  mixed-state batch toggle.** If *any* selected item isn't already a
  favorite, the action reads `"Add to Favorites (N)"` and clicking it
  favorites **all** of them; only when *every* selected item is
  already a favorite does it flip to `"Remove from Favorites (N)"`
  and unfavorite all of them. Implemented as a plain
  `all(bool(it.data(UserRole + 2)) for it in items)` check. Pinned by
  two tests covering both branches:
  `test_filmstrip_batch_favorite_shows_add_label_for_mixed_selection_and_targets_all`
  and
  `test_filmstrip_batch_favorite_shows_remove_label_when_all_already_favorited`.
- **Rating/Flag -- SET every selected item to the SAME chosen value**,
  not a merge/offset of each item's existing value -- identical to
  what applying the single-item action once per image, one at a time,
  would do. The batch "Set Rating" submenu offers the same six options
  (`No Rating`/1-5 stars) as the single-item version; the three flat
  Pick/Reject/Remove-Flag actions are always shown in the batch menu
  (unlike the single-item menu's "Remove Flag" is only shown when the
  one item is already flagged) -- for a mixed selection there's no
  single "is this flagged" answer to gate on, and "Remove Flag" on an
  already-unflagged item is a harmless no-op at the catalog-service
  layer regardless.
- **"Add Keywords to N Photos..." -- deliberately ADD-ONLY, not a
  destructive full replace.** This is the one deliberate, specific
  semantic choice the task brief asked to be called out clearly: a
  batch replace of keywords across many images, without the user
  having seen each individual image's current keyword list first, is
  a correctness trap (silently wiping out keywords the user never
  looked at). So the batch dialog is a *blank* `QInputDialog.getText`
  prompt ("Comma-separated keywords to add to N photos:") -- no
  pre-fill, since there is no single "current keywords" to pre-fill
  with across a mixed selection -- and the parsed, comma-split list is
  emitted as the keywords to **append**, not the new full list. The
  actual merge (`entry.keywords + new_keywords`, then normalized/
  deduped exactly as a single-image edit already is) happens
  controller-side, in the new `LibraryController.add_entries_keywords()`
  (see below), so each image's own pre-existing, distinct keywords are
  preserved. **The single-image "Edit Keywords..." action is completely
  unmodified and remains a full replace** -- the user can see that one
  image's current keywords while editing them, so a full replace there
  is not the same correctness trap a many-image batch replace would
  be.
- **"Add to Collection (N)"** -- a non-checkable submenu (unlike the
  single-item version's checkable, per-collection toggle, which makes
  no sense across a mixed-membership selection) listing every existing
  collection; selecting one adds **every** selected image to that
  collection. No batch "New Collection..." entry (see Non-goals).

Each menu action, once selected, emits one of five new **batch**
signals -- never the five existing single-item signals -- carrying the
full list of selected paths:

```python
favorite_batch_toggled = pyqtSignal(list, bool)
rating_batch_changed = pyqtSignal(list, int)
flag_batch_changed = pyqtSignal(list, str)
keywords_batch_added = pyqtSignal(list, list)       # (paths, keywords_to_add)
collection_batch_added = pyqtSignal(list, str)       # (paths, collection_id)
```

### Controller: dedicated batch methods, not a view-side loop over the single-entry controller methods

The task brief's own guidance was to check whether looping the
existing single-entry controller methods (`set_entry_favorite`, etc.)
once per selected path is good enough, or whether it causes a real
performance/signal-storm problem worth adding dedicated batch methods
for. Reading what each single-entry controller method does after its
catalog-service call settled this: every one of them
(`set_entry_favorite`, `set_entry_rating`, `set_entry_flag`,
`set_entry_keywords`, `add_entry_to_collection`) ends with
`self._emit_libraries()` and `self._rebuild_entries_for_current_library()`
(or `self._emit_collections()` for the collection ones).
`_rebuild_entries_for_current_library()` is not cheap: it calls
`cancel_thumbnail_batch()`, re-lists every entry in the current
library, rebuilds every entry's full payload dict, re-emits
`entries_rebuilt` (which both `LibraryView` and `FilmstripView` consume
by clearing and rebuilding their entire item list from scratch), kicks
off an async orphaned-cache-cleanup pass, and starts a brand new
background `_ThumbnailBatchWorker` thread for any entry needing a
thumbnail. Looping a single-entry controller method once per selected
path in a 50-image batch would re-run **all of that 50 times** --
cancelling and restarting the thumbnail worker thread 50 times,
re-rendering the whole filmstrip/library grid 50 times, and writing
the catalog file to disk 50 times -- a real, visibly janky cost for a
single user action, not a hypothetical one.

So five new `LibraryController` methods were added
(`set_entries_favorite`, `set_entries_rating`, `set_entries_flag`,
`add_entries_keywords`, `add_entries_to_collection`), each looping the
**catalog-service** call per path (the catalog-service layer itself
needed no batch-shaped methods -- looping its existing per-entry
setters is correctness-preserving and each individual catalog call is
cheap; it's the *controller's* post-call refresh/thumbnail-restart
work that's expensive, not the catalog write itself) and calling
`_emit_libraries()`/`_emit_collections()` plus
`_rebuild_entries_for_current_library()` **exactly once**, after the
loop, instead of once per path:

```python
def set_entries_favorite(self, file_paths: list[str], favorite: bool) -> None:
    if not self._current_library_id or not file_paths:
        return
    for file_path in file_paths:
        if not file_path:
            continue
        self._catalog_service.set_entry_favorite(
            self._current_library_id, file_path, favorite
        )
    self._emit_libraries()
    self._rebuild_entries_for_current_library()
```

`set_entries_rating`/`set_entries_flag` are structurally identical.
`add_entries_to_collection` mirrors this but calls
`self._catalog_service.add_entry_to_collection(...)` per path and ends
with `self._emit_collections()` instead of `self._emit_libraries()`
(matching `add_entry_to_collection`'s own single-entry shape).

`add_entries_keywords` additionally has to compute the per-path merge
itself (the catalog service's `set_entry_keywords` is still a plain
*set*, not an append -- it has no idea this call is part of a batch
"add" operation):

```python
def add_entries_keywords(self, file_paths: list[str], keywords: list[str]) -> None:
    if not self._current_library_id or not file_paths or not keywords:
        return
    for file_path in file_paths:
        if not file_path:
            continue
        try:
            entry = self._catalog_service.get_entry(self._current_library_id, file_path)
        except KeyError:
            continue
        merged = [*entry.keywords, *keywords]
        self._catalog_service.set_entry_keywords(
            self._current_library_id, file_path, merged
        )
    self._emit_libraries()
    self._rebuild_entries_for_current_library()
```

Each path's own existing `entry.keywords` is read first and the new
keywords are appended to *that specific path's* list (not a single
shared list computed once outside the loop), so two images with
different pre-existing keywords each keep their own distinct set, plus
the newly-added ones. The final normalize/case-insensitive-dedupe
(already in `LibraryCatalogService.set_entry_keywords`/
`_normalize_keywords`, unchanged by this slice) then collapses any
case-variant duplicate between "existing" and "newly added" the same
way a single-image edit already would.

**This was the "your call" decision this slice had to make**, per the
task brief's own invitation: dedicated controller-level batch methods
that loop the catalog-service call internally, rather than (a) the
simplest option of looping the single-entry *controller* methods from
the view/signal-handling layer (rejected -- see the thumbnail-worker/
re-render cost above), or (b) adding true batch-shaped methods to
`LibraryCatalogService` itself (not needed -- the catalog-service calls
themselves aren't the expensive part, and looping them from the
controller is just as cheap while keeping the catalog service's
existing per-entry-only method surface unchanged).

### `MainWindow` wiring

Five new connect calls, immediately after the five existing single-item
ones, routing the new batch signals to the new batch controller
methods -- none of the five existing connects were touched:

```python
self._filmstrip_view.favorite_batch_toggled.connect(self._library_controller.set_entries_favorite)
self._filmstrip_view.rating_batch_changed.connect(self._library_controller.set_entries_rating)
self._filmstrip_view.flag_batch_changed.connect(self._library_controller.set_entries_flag)
self._filmstrip_view.keywords_batch_added.connect(self._library_controller.add_entries_keywords)
self._filmstrip_view.collection_batch_added.connect(self._library_controller.add_entries_to_collection)
```

## 3. Contracts

- `FilmstripView._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)`
  -- the only change to the list's selection behavior. `currentItemChanged`
  -> `_on_current_item_changed()` -> `image_selected` is unchanged.
- `FilmstripView` gained five new signals: `favorite_batch_toggled =
  pyqtSignal(list, bool)`, `rating_batch_changed = pyqtSignal(list, int)`,
  `flag_batch_changed = pyqtSignal(list, str)`, `keywords_batch_added =
  pyqtSignal(list, list)` (paths, keywords to ADD), `collection_batch_added
  = pyqtSignal(list, str)` (paths, collection_id). All five are only ever
  emitted by the new `_show_batch_context_menu()`; the five pre-existing
  single-item signals (`favorite_toggled`, `rating_changed`,
  `flag_changed`, `keywords_changed`, `collection_membership_toggled`)
  are completely unmodified and are never emitted from the batch branch.
- `_show_context_menu(position)` gained one new branch at its top
  (`len(selected_items) > 1 and item in selected_items`) that delegates
  to the new `_show_batch_context_menu(position, items)`; every line
  below that branch is byte-for-byte unchanged from before this slice.
- `LibraryController` gained five new methods: `set_entries_favorite(
  file_paths: list[str], favorite: bool)`, `set_entries_rating(
  file_paths: list[str], rating: int)`, `set_entries_flag(file_paths:
  list[str], flag: str)`, `add_entries_keywords(file_paths: list[str],
  keywords: list[str])` (additive -- merges into each path's existing
  keywords), `add_entries_to_collection(file_paths: list[str],
  collection_id: str)`. Each guards on `_current_library_id`/non-empty
  input, loops the matching `LibraryCatalogService` single-entry call
  per path, then calls the refresh signal(s)
  (`_emit_libraries()`/`_emit_collections()` plus
  `_rebuild_entries_for_current_library()`) exactly **once**, not once
  per path.
- `main_window.py` gained five new connect calls routing the five new
  `FilmstripView` batch signals to the five new `LibraryController`
  batch methods. The five pre-existing single-item connects are
  unmodified.
- No existing method's signature or behavior changed, and no existing
  signal's emission site changed. `LibraryCatalogService` gained no new
  methods at all -- every batch method loops its existing single-entry
  methods (`set_entry_favorite`, `set_entry_rating`, `set_entry_flag`,
  `set_entry_keywords`, `add_entry_to_collection`, `get_entry`)
  unchanged.
- `LibraryView`/`ResponsiveLibraryGrid` are completely untouched --
  this slice is scoped to the filmstrip only (see Non-goals).

## 4. Nuances and failure modes

**A single click after a multi-select still only opens one image.**
Clicking a single item (no modifier) always makes exactly that one item
`current` and clears the rest of the selection (standard Qt
`ExtendedSelection` click behavior, not something this slice added),
which fires `currentItemChanged` for that one item and nothing else --
`image_selected` is emitted for exactly one path, same as before this
slice existed. Pinned directly by
`test_filmstrip_single_click_still_opens_exactly_one_image_unregressed`.

**Right-clicking inside vs. outside the current selection.** A
right-click on an item that IS part of a >1-item selection batch-
applies to the whole selection; a right-click on an item that is NOT
part of the current selection (even if something else is selected)
acts on that one right-clicked item only, leaving the rest of the
selection's items alone for that action (though Qt's own
`customContextMenuRequested` does not itself change the selection, so
the old selection visually remains highlighted afterward -- this
slice does not attempt to "select the right-clicked item" as a side
effect of opening the context menu, matching the existing right-click
behavior this codebase already had before multi-select existed).
Pinned by
`test_filmstrip_right_click_outside_selection_falls_back_to_single_item_menu`.

**Every pre-existing single-item context-menu test still exercises the
unmodified single-item branch**, because none of them ever calls
`QListWidgetItem.setSelected(True)` -- `self._list.selectedItems()` is
empty for all of them, so `len(selected_items) > 1` is always `False`
and they fall straight through to the pre-existing code, unmodified.
This was confirmed by running the full pre-existing context-menu test
suite unchanged alongside this slice's new tests (see Test plan).

**Batch keyword-add with an empty/whitespace-only input.** Mirrors the
single-item "Edit Keywords..." dialog's own "nothing emitted on
cancel" behavior, plus one more guard: if the comma-split result is
empty after stripping (e.g. the user enters only whitespace or
commas), `keywords_batch_added` is not emitted at all -- there is
nothing useful to add, and emitting an empty-list "add" would be a
pure no-op through `LibraryController.add_entries_keywords`'s own
`if not keywords: return` guard anyway (the view-side check just
avoids a wasted round-trip).

**Favorite/Rating/Flag/Keywords/Collections single-item regression.**
Every pre-existing test for those five features across the catalog-
service, controller, and filmstrip-view layers was left completely
unmodified and still passes, confirming this slice's additions did not
alter any of them (see Test plan / Verification).

**`LibraryView`'s thumbnail grid has no multi-select.** Only the
filmstrip gained `ExtendedSelection` and batch context-menu actions in
this slice -- `ResponsiveLibraryGrid` (the sidebar's per-library
thumbnail grid) is unchanged, matching the task brief's explicit scope
(the filmstrip/library context-menu gap, not a general app-wide
multi-select rework).

## 5. Test plan

- `tests/unit/test_views/test_workspace_widgets.py`:
  `test_filmstrip_list_uses_extended_selection_mode` (selection mode is
  actually `ExtendedSelection`),
  `test_filmstrip_single_click_still_opens_exactly_one_image_unregressed`
  (the critical regression-prevention test: a plain click on one item,
  twice in a row, each emits `image_selected` for exactly that one
  path, nothing else),
  `test_filmstrip_batch_context_menu_only_triggers_when_right_clicked_item_is_selected`
  (a >1-item selection's right-click menu carries the batch-shaped
  `"(2)"`-suffixed action text, distinguishing it from the single-item
  menu),
  `test_filmstrip_batch_rating_sets_all_selected_to_same_value`,
  `test_filmstrip_batch_flag_sets_all_selected_to_same_value`,
  `test_filmstrip_batch_favorite_shows_add_label_for_mixed_selection_and_targets_all`
  and
  `test_filmstrip_batch_favorite_shows_remove_label_when_all_already_favorited`
  (both tri-state Favorite branches, asserting both the menu label
  shown and the emitted target value),
  `test_filmstrip_batch_add_keywords_is_additive_only` (asserts the
  batch signal carries only the newly-typed keywords, not a merged
  list -- the merge itself is a controller-level concern, tested
  separately below),
  `test_filmstrip_batch_add_to_collection_adds_every_selected_item`,
  and
  `test_filmstrip_right_click_outside_selection_falls_back_to_single_item_menu`.
- `tests/unit/test_controllers/test_library_controller.py`:
  `test_set_entries_favorite_sets_all_to_same_value_and_refreshes_once`
  (also asserts `entries_rebuilt` fires exactly once across the whole
  batch call, the specific perf concern that justified adding dedicated
  batch controller methods in the first place),
  `test_set_entries_rating_sets_all_to_same_value`,
  `test_set_entries_flag_sets_all_to_same_value`,
  `test_add_entries_keywords_is_additive_and_preserves_existing`
  (one path already has `["existing"]`, the batch call adds
  `["sunset"]` to both paths, and the path that already had keywords
  ends up with both, not just the new one),
  `test_add_entries_to_collection_adds_every_path`, and
  `test_set_entries_favorite_no_op_on_empty_paths_or_no_current_library`
  (defensive guard: an empty path list or no current library selected
  yet must not raise or emit a spurious refresh).
- Explicit regression check: every pre-existing Favorite, Rating, Flag,
  Keywords, and Collections test across the catalog-service,
  controller, and filmstrip-view test files was re-run unmodified as
  part of the full suite and still passes (see Verification below).

## 6. Rollout

Purely additive: one new `QListWidget` selection-mode call (no field
added, a one-line behavior change with no persisted state), five new
`FilmstripView` signals, one new context-menu branch (the old branch
left completely unmodified) plus one new private method
(`_show_batch_context_menu`), five new `LibraryController` methods (no
new catalog-service methods, no new persisted fields), and five new
`main_window.py` connect calls. No existing method's signature changed
and no existing signal's emission site changed. A plain revert removes
the feature entirely with nothing left behind in the catalog file --
every batch method writes through the exact same, unmodified
single-entry catalog-service setters a non-batch edit already would,
so there is no new on-disk shape to migrate away from.

## 7. Implementation summary

Added `QAbstractItemView.SelectionMode.ExtendedSelection` to
`FilmstripView._list` (`src/views/widgets/filmstrip_view.py`) -- the
only change to how the list selects items; `currentItemChanged` ->
`_on_current_item_changed()` -> `image_selected` is unchanged, verified
by tracing that chain end to end before writing any new code and by a
dedicated regression test. Added five new `FilmstripView` signals
(`favorite_batch_toggled`, `rating_batch_changed`, `flag_batch_changed`,
`keywords_batch_added`, `collection_batch_added`) and a new
`_show_batch_context_menu()` method, reached via one new branch at the
top of the pre-existing, otherwise byte-for-byte-unchanged
`_show_context_menu()` (taken only when the right-clicked item is part
of a selection of more than one item). The batch menu's Favorite action
is a tri-state "Add to Favorites (N)"/"Remove from Favorites (N)" label
based on whether every selected item is already a favorite; Rating/Flag
set every selected item to the same chosen value; "Add Keywords..." is
deliberately additive-only (new keywords are appended to each image's
own existing, distinct keyword list, never a destructive full replace);
"Add to Collection" adds every selected image to the chosen collection.

Added five new `LibraryController` methods (`set_entries_favorite`,
`set_entries_rating`, `set_entries_flag`, `add_entries_keywords`,
`add_entries_to_collection`, `src/controllers/library_controller.py`),
each looping the matching existing `LibraryCatalogService` single-entry
setter per path but calling the refresh signal(s)
(`_emit_libraries()`/`_emit_collections()` plus
`_rebuild_entries_for_current_library()`) exactly once per batch call
instead of once per path -- the deliberate choice over simply looping
the single-entry *controller* methods, made after reading that
`_rebuild_entries_for_current_library()` cancels and restarts a
background thumbnail-worker thread and fully re-renders both library
views on every call, which would be visibly janky looped once per
selected image in a real batch. `LibraryCatalogService` gained no new
methods. Added five `main_window.py` connect calls routing the new
batch signals to the new batch controller methods, alongside (not
replacing) the five pre-existing single-item connects.

Updated `docs/planning/PRODUCT_ROADMAP.md`: added a new "Multi-select +
batch metadata actions" bullet to Phase A marked **Done** for this v1
scope, updated the Collections bullet's own "no multi-select exists"
non-goal callout to note the gap is now closed, and updated the
Coverage table's PDF row 24 from "no bulk/multi-select across entries"
to **Done for v1 scope** with the three remaining non-goals (viewer-
level multi-select, batch export, marquee selection) called out
explicitly as the deliberate, documented remaining gap.

**Deviation notes / "your call" decisions**, per the task brief's own
invitation:

1. Dedicated controller-level batch methods were added (looping the
   catalog-service calls internally, refreshing once) rather than
   either looping the single-entry *controller* methods from the view
   layer, or adding true batch-shaped methods to the catalog-service
   layer itself -- see Design above for the perf reasoning that drove
   this.
2. The single-item and batch context-menu code paths were kept as two
   separate branches/methods with some near-duplicate menu-building
   code, rather than unified into one parameterized code path, as the
   lowest-risk way to guarantee the ~15 pre-existing single-item
   context-menu tests cannot regress.
3. Favorite's tri-state menu-label wording ("Add to Favorites (N)" /
   "Remove from Favorites (N)") and the decision to always show
   "Remove Flag" in the batch menu (unlike the single-item menu's
   conditional "Remove Flag") were both left to engineering judgment,
   per the task brief's own invitation to do so.
4. No batch "New Collection..." entry was built (see Non-goals) --
   the task brief's own scope list for "Add to Collection" only
   mentioned adding every selected image to "the chosen collection,"
   not creating a new one as part of a batch action.

Verification: new tests -- 10 added to
`tests/unit/test_views/test_workspace_widgets.py`, 6 added to
`tests/unit/test_controllers/test_library_controller.py` (16 new `def
test_...` functions in total, all passing on first run against the new
production code with no fixes needed). Complete suite run via
`QT_QPA_PLATFORM=offscreen python3 -m pytest -q --deselect
tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::
test_geometry_is_restored_on_next_launch` -- see the calling session's
own verification for the exact final pass count; no failures observed,
including no regression in any pre-existing Favorite/Rating/Flag/
Keywords/Collections test.

This completes Phase A's "no bulk/multi-select across entries"
coverage-table gap for its documented minimal v1 scope: multi-select
and batch metadata actions are now **Done**, with viewer-level
multi-select, batch export, and marquee selection called out as the
explicit, deliberate remaining gap.
