# Remove Photo / Delete from Disk

Related roadmap: Phase A, Edit-menu and Photo-menu coverage (PDF
sections 2 and 4) in `docs/planning/PRODUCT_ROADMAP.md` -- both rows'
notes listed "Duplicate/Delete/Remove photo" as still missing. This
slice closes the Remove/Delete half of that item. Duplicate (virtual
copies) is explicitly **not** closed here -- see Non-goals.

## 1. Problem, goal, and non-goals

**Problem.** `LibraryCatalogService` only ever offered whole-library
removal (`remove_library`) -- there was no way to take a single photo
out of a library's catalog, and no way to delete the underlying file
from disk at all. Every mutation this session has shipped before this
slice (Favorite, Rating, Flag, Keywords, Edit Date & Time, Collections)
only ever added or removed **metadata**; none of them touched a real
file on the user's disk.

**Goal.** Add a single-entry catalog-removal primitive
(`LibraryCatalogService.remove_entry`), a controller layer
(`LibraryController.remove_entry`/`remove_entries`) that optionally also
deletes the underlying file, and a `FilmstripView` context-menu action
(single + multi-select batch) that shows a Lightroom-style 3-way
confirmation -- "Remove from Library" / "Delete from Disk" / "Cancel" --
before emitting anything, wired through `MainWindow` to the controller.
Removing the image currently open in the editor resets the editor to
its own pre-load "no image" state rather than leaving a dangling
reference to a file that may no longer exist.

**Non-goals (explicit scope boundary for this slice):**

- **No "Duplicate" / virtual copies, in any form.** Confirmed by
  reading the catalog layer end to end before writing any code:
  `LibraryEntry`, `LibraryCatalogService.get_entry`, and its internal
  `_require_entry` are all keyed by `path` (`entry.normalized_path ==
  normalized`, where `normalized = _normalize_path(path)`) -- there is
  no entry-id concept distinct from the file path anywhere in this
  catalog. A true Lightroom-style "virtual copy" needs **two catalog
  entries that share one physical file, each with its own independent
  adjustment history** -- that requires a new, separate catalog
  identity scheme (an opaque entry id, not a path, as the primary key),
  which is a real architectural change to every lookup in
  `LibraryCatalogService`, not a small addition on top of this slice's
  own work. Per the task brief's own explicit instruction, this is a
  **deliberate, documented remaining gap**, not an oversight -- and,
  just as explicitly instructed, no naive stand-in was built either
  (e.g. "Duplicate" that just copies the file on disk under a new name
  and re-imports it): that would silently create a second real file the
  user never asked to create, which is exactly the kind of
  surprising-filesystem-side-effect this slice's own "Delete from Disk"
  wording goes out of its way to avoid for the *deletion* half of this
  feature.
- **No OS trash/recycle-bin integration.** "Delete from Disk" calls
  `Path.unlink()` -- a **permanent** delete, not a move to the OS trash
  can. Recycle-bin-aware deletion is a real, OS-specific integration
  (different APIs/libraries per platform) that nothing in this
  codebase has any precedent for. This is a deliberate, simpler v1
  choice: plain `unlink()` is what the task brief's own wording
  ("permanently delete") describes, and the confirmation dialog's text
  is written to make that permanence unambiguous to the user up front
  rather than relying on a trash-can safety net to exist.
- **No undo for "Delete from Disk."** This app's undo/redo system
  (`HistoryService`) only ever applies to in-memory adjustment state
  (`AdjustmentStateCommand`/`CombinedAdjustmentCommand`) -- it has never
  modeled a filesystem operation and does not start doing so here.
  Once a file is unlinked, it is gone; there is no "undo" command that
  could bring it back. This is called out explicitly in the
  confirmation dialog's own wording (see Design below) specifically so
  the user understands this *before* confirming, not after.
- **No change to `remove_library`'s own existing behavior.** It still
  only removes an entire library and never touches the filesystem --
  `remove_entry` is a new, separate, single-entry primitive alongside
  it, not a replacement or refactor of it.

## 2. Current behavior (before this slice)

`LibraryCatalogService` had `remove_library(library_id)` (deletes an
entire `LibraryRecord`, falling back to a fresh default library if that
was the last one) and `clear_library_entries(library_id)` (empties one
library's entry list in bulk) -- no method existed to remove exactly
one entry while leaving the rest of its library untouched. No code path
anywhere in this codebase ever called `Path.unlink()` (or any other
filesystem-deleting call) on a user's image file; `import_images`/
`_refresh_entry`/`_build_entry` only ever call `Path.stat()` (read-only)
to track a file's existence/mtime/size.

## 3. Design

### `LibraryCatalogService.remove_entry` -- a pure catalog primitive, no filesystem access

```python
def remove_entry(self, library_id: str, path: str) -> bool:
    library = self.get_library(library_id)
    if library is None:
        return False
    normalized = _normalize_path(path)
    remaining = [e for e in library.entries if e.normalized_path != normalized]
    if len(remaining) == len(library.entries):
        return False
    library.entries = remaining
    library.updated_at = _utc_now_iso()
    self._save_catalog()
    return True
```

No-op (`False`) on an unknown library or path, never raises -- mirrors
`add_entry_to_collection`'s defensive style, the most recent precedent
for a method whose one real caller (`LibraryController`) wants a plain
boolean rather than a `KeyError` to catch.

**Where the actual file deletion lives, and why.** This method **never
touches the filesystem** -- it is deliberately kept a pure JSON-catalog
abstraction, the same way `import_images`/`_refresh_entry`/
`_build_entry` only ever *read* a file's `stat()` here, never write to
or delete anything on disk. The task brief asked explicitly to check for
an established precedent for where filesystem-touching responsibility
belongs before picking a layer, and that grep came back empty --
nothing in this service writes to or deletes anything outside its own
catalog JSON file. Rather than adding the first filesystem-deleting code
to the service layer, the actual `Path.unlink()` call lives one layer
up, in `LibraryController._delete_file_from_disk`, called from
`remove_entry`/`remove_entries` **after** the catalog removal has
already succeeded. This keeps `LibraryCatalogService`'s existing
contract (a catalog JSON abstraction, nothing more) intact, and keeps
the one new filesystem-destructive operation this whole session has
ever added in a single, easy-to-find place.

**No separate collection-membership cleanup needed.** Unlike
`delete_collection` (which deletes a `CollectionRecord` that many
entries may still reference by id, and so must loop every entry to
strip the dangling id out of each one's `collection_ids`), an entry's
`collection_ids` live **on the entry itself** -- deleting the entry
already takes every one of its collection memberships with it. This was
confirmed by reading `add_entry_to_collection`/`remove_entry_from_
collection`/`delete_collection` before writing `remove_entry`, exactly as
the task brief asked.

### `LibraryController.remove_entry`/`remove_entries` -- where the disk deletion happens, and how a failure is handled

```python
def remove_entry(self, file_path: str, delete_from_disk: bool = False) -> bool:
    if not self._current_library_id or not file_path:
        return False
    removed = self._catalog_service.remove_entry(self._current_library_id, file_path)
    if not removed:
        return False
    if delete_from_disk:
        self._delete_file_from_disk(file_path)
    self._emit_libraries()
    self._emit_collections()
    self._rebuild_entries_for_current_library()
    return True

def _delete_file_from_disk(self, file_path: str) -> None:
    try:
        Path(file_path).unlink(missing_ok=True)
    except OSError:
        logger.exception("Failed to delete file from disk: %s", file_path)
```

`remove_entries(file_paths, delete_from_disk=False)` is the batch
counterpart, looping the per-path removal (and, when requested, its
disk deletion) but refreshing views only **once** at the end -- the
exact shape `set_entries_rating`/`set_entries_favorite` already
established for every other batch mutation this session.

**Order of operations, and why a disk-deletion failure doesn't undo the
catalog removal.** The catalog entry is removed **first**; disk
deletion (if requested) is attempted only after that has already
succeeded. `Path.unlink(missing_ok=True)` makes an already-gone file a
silent no-op (not an error) -- the common case where the user asks to
delete a file that was already missing from the library's perspective.
Any **other** `OSError` (permission denied, file locked by another
process, a read-only filesystem, etc.) is caught, logged via
`logger.exception` (this file's established logging convention,
`logging.getLogger(__name__)`), and swallowed -- **never raised, never
undoing the catalog removal that already happened.** This was a
deliberate choice: the user's primary request ("take this photo out of
my library") has already been satisfied by the time disk deletion is
even attempted, and a secondary filesystem problem is a real but
*separate* failure that should not (a) crash the app, or (b) silently
leave the photo back in the library as if nothing happened, which
would be a confusing, inconsistent "half-undo" the user never asked
for. The log entry is the mechanism by which this secondary failure is
surfaced to anyone debugging it; there is no additional UI-level
"disk deletion failed" toast or dialog in this v1 (a reasonable,
minimal scope -- the file is logged, not silently lost from view).

**Removing an entry also refreshes collections.** `_emit_collections()`
is called alongside `_emit_libraries()`/`_rebuild_entries_for_current_
library()` -- a removed entry may have belonged to one or more
collections, and `delete_collection` already establishes "removing
something an entry belonged to refreshes the collections list too" as
this controller's own convention.

### The 3-way confirmation dialog lives in `FilmstripView`, not `MainWindow`

**Decision: the confirmation dialog is shown directly inside
`FilmstripView._prompt_remove_confirmation`, before either
`remove_requested`/`remove_batch_requested` signal is ever emitted.**
This mirrors the existing precedent in this exact file: "Edit
Keywords..."/"Edit Date & Time..." already show their own dialogs
(`QInputDialog.getText`/`_prompt_for_captured_at`) directly in the view,
parse/validate the result, and only emit a signal on confirmation --
never on Cancel. `MainWindow`'s own `QMessageBox.question` calls (e.g.
`_on_remove_library_requested`) are a *different* existing pattern (a
plain Yes/No confirmation for a controller-level action the view has no
opinion about), but a 3-way choice tied to one specific context-menu
item's own semantics fits the `FilmstripView`-owns-its-dialogs
convention better, and keeps `MainWindow`'s wiring purely additive
(connect two signals, nothing more) exactly like every other
context-menu action this session has wired.

```python
def _prompt_remove_confirmation(self, subject: str) -> Optional[bool]:
    box = QMessageBox(self)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Remove Photo")
    box.setText(f"Remove {subject} from this library?")
    box.setInformativeText(
        "Remove from Library: removes the photo from this library's "
        "catalog. The file itself will not be deleted and stays "
        "exactly where it is on disk.\n\n"
        "Delete from Disk: removes the photo from this library AND "
        "permanently deletes the file from your computer. This "
        "cannot be undone by this app."
    )
    remove_button = box.addButton("Remove from Library", QMessageBox.ButtonRole.AcceptRole)
    delete_button = box.addButton("Delete from Disk", QMessageBox.ButtonRole.DestructiveRole)
    cancel_button = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(remove_button)
    box.setEscapeButton(cancel_button)
    box.exec()
    clicked = box.clickedButton()
    if clicked is delete_button:
        return True
    if clicked is remove_button:
        return False
    return None
```

**Exact wording chosen, and why.** "Delete from Disk" is the single
most destructive, hardest-to-undo action added to this app in this
entire session -- every prior slice only ever added/removed metadata.
The dialog is written so the difference between the two real choices
cannot be misread from the button labels alone:

- Main text: `"Remove {subject} from this library?"` (`subject` is
  "this photo" for the single-item menu, or `"{count} photos"` for the
  batch one) -- a neutral framing that doesn't presuppose which of the
  two destructive choices the user wants.
- "Remove from Library" description: *"removes the photo from this
  library's catalog. The file itself will not be deleted and stays
  exactly where it is on disk."* -- explicitly states the file survives,
  twice over ("will not be deleted" and "stays exactly where it is").
- "Delete from Disk" description: *"removes the photo from this
  library AND permanently deletes the file from your computer. This
  cannot be undone by this app."* -- explicitly spells out that this is
  the file (not just the library entry), uses "permanently", and adds
  the undo caveat inline rather than leaving it to be inferred.
- A `QMessageBox.Icon.Warning` icon, and "Delete from Disk" registered
  with `QMessageBox.ButtonRole.DestructiveRole` (Qt's own semantic
  marker for a destructive action, which on some platforms renders the
  button distinctly, e.g. in red).
- "Remove from Library" is the **default** button (`setDefaultButton`)
  and "Cancel" is the **escape** button (`setEscapeButton`) -- pressing
  Enter or Escape can never accidentally trigger the irreversible disk
  deletion; only an explicit click on "Delete from Disk" can.

Returns `True` for "Delete from Disk", `False` for "Remove from
Library", or `None` for "Cancel"/closing the dialog (treated
identically) -- the caller (`_show_context_menu`/
`_show_batch_context_menu`) returns immediately on `None` without
emitting anything.

### Context menu: one new flat action each, after a separator

Single-item menu gets `menu.addAction("Remove Photo...")` after a
`menu.addSeparator()` (visually distinct from the metadata actions
above it, matching how destructive actions are usually set apart in
this kind of menu). The multi-select batch menu gets
`f"Remove {count} Photos..."`, following the same `{count}`-suffixed
label convention every other batch action in that menu already uses.

```python
elif selected is remove_action:
    choice = self._prompt_remove_confirmation("this photo")
    if choice is None:
        return
    self.remove_requested.emit(str(path), choice)
```

```python
elif selected is remove_action:
    choice = self._prompt_remove_confirmation(f"{count} photos")
    if choice is None:
        return
    self.remove_batch_requested.emit(paths, choice)
```

### `MainWindow` wiring, and clearing the editor for the currently-open image

`MainWindow` connects the two new signals purely additively, right
after the existing collection-batch wiring:

```python
self._filmstrip_view.remove_requested.connect(self._on_remove_entry_requested)
self._filmstrip_view.remove_batch_requested.connect(self._on_remove_entries_requested)
```

```python
def _on_remove_entry_requested(self, file_path: str, delete_from_disk: bool) -> None:
    self._clear_current_image_if_removed([file_path])
    self._library_controller.remove_entry(file_path, delete_from_disk)

def _on_remove_entries_requested(self, file_paths: list, delete_from_disk: bool) -> None:
    self._clear_current_image_if_removed(file_paths)
    self._library_controller.remove_entries(file_paths, delete_from_disk)
```

**Removing the currently-open image.** `LibraryController` has no
notion of "what image is currently open in the editor" -- that lives in
`ImageController`/`MainWindow`. So this check happens at the
`MainWindow` wiring layer, **before** calling into the library
controller:

```python
def _clear_current_image_if_removed(self, removed_paths: list) -> None:
    current_path = self._image_controller.image_model.file_path
    if not current_path or current_path not in removed_paths:
        return
    self._image_controller.clear_image()
    self._tools_panel.set_enabled(False)
    self._settings_service.set_current_image_path("")
    self._settings_service.sync()
    self._status_bar.showMessage("Photo removed", 2000)
```

Rather than inventing a new empty-state UI, this reuses the **exact**
state the app is already in right after startup with an empty library,
before any `load_image`/`load_image_async` call has ever been made.
Grepping `main_window.py`/`image_controller.py`/`image_view.py` for how
that startup "no image" state already looks found it was never an
explicit "clear" call at all -- it's simply the state every piece of UI
starts in before anything has ever loaded: `ImageModel`'s fields are
all `None` until `set_original_image`/`file_path =` is first assigned,
and `ImageView`'s `_ImageCanvas` paints its own built-in `"No image
loaded"` placeholder text whenever `self._pixmap is None`, which is
exactly its own `__init__` state before `set_pixmap` is ever called.
Two small new methods reproduce that same state explicitly, instead of
leaving it as an implicit "never been touched" invariant that a reset
path would have to fake:

```python
# ImageModel
def clear(self) -> None:
    self.file_path = None
    self.original_image = None
    self.current_image = None
    self._is_modified = False

# ImageView
def clear(self) -> None:
    self._pixmap = None
    self._display_frame = None
    self._image_canvas.clear()  # already existed, private, now exposed via this call

# ImageController
def clear_image(self) -> None:
    self._image_model.clear()
    self._image_view.clear()
    self._history_service.clear_history()
```

`ImageController.clear_image()` also clears undo/redo history -- there
is no image left for it to apply to, mirroring `_apply_loaded_image`'s
own `self._history_service.clear_history()` call on every ordinary
image switch. `MainWindow` additionally disables the tools panel and
clears the persisted "last-opened image" setting (`set_current_image_
path("")`, which removes the stored key entirely -- `get_current_image_
path()` then correctly returns `None`, not an empty string), so a
restart doesn't try to reopen a file that may no longer even exist.
Deliberately **not** calling `_persist_current_adjustments()` first
here (unlike almost every other library mutation in this file): that
image's adjustment state is being discarded along with its entry
(and, for "Delete from Disk", the file itself), so writing it back to
the catalog immediately before deleting the entry would be pure waste.

**Removing an entry that is *not* the currently-open image** leaves the
editor completely untouched -- `_clear_current_image_if_removed` only
acts when `current_path` is actually one of `removed_paths`.

## 4. Contracts

- `LibraryCatalogService.remove_entry(self, library_id: str, path: str) -> bool`
  -- new method; removes one entry from one library's catalog; never
  touches the filesystem; no-op (`False`) on an unknown library or
  path, never raises.
- `LibraryController.remove_entry(self, file_path: str, delete_from_disk: bool = False) -> bool`
  -- new method; removes the entry from the current library, optionally
  also deleting the file from disk; refreshes libraries/collections/
  entries exactly once on success; returns whether the catalog entry
  was removed (independent of whether the file deletion, if requested,
  itself succeeded).
- `LibraryController.remove_entries(self, file_paths: list[str], delete_from_disk: bool = False) -> None`
  -- new batch method; same per-path semantics, refreshing views only
  once for the whole batch, matching `set_entries_rating`/
  `set_entries_favorite`'s established pattern.
- `LibraryController._delete_file_from_disk(self, file_path: str) -> None`
  -- new private helper; `Path(file_path).unlink(missing_ok=True)`
  wrapped in `try/except OSError` (logged via `logger.exception`, never
  raised).
- `FilmstripView.remove_requested = pyqtSignal(str, bool)` -- new
  signal (path, `delete_from_disk`), emitted only after the user
  confirms (never on Cancel).
- `FilmstripView.remove_batch_requested = pyqtSignal(list, bool)` --
  batch counterpart (paths, `delete_from_disk`).
- `FilmstripView._prompt_remove_confirmation(self, subject: str) -> Optional[bool]`
  -- new private helper backing both the single-item and batch dialogs;
  returns `True` ("Delete from Disk"), `False` ("Remove from Library"),
  or `None` ("Cancel").
- `ImageModel.clear(self) -> None` / `ImageView.clear(self) -> None` /
  `ImageController.clear_image(self) -> None` -- new methods; reset to
  the pre-load "no image" state.
- `MainWindow._on_remove_entry_requested`/`_on_remove_entries_requested`/
  `_clear_current_image_if_removed` -- new private handlers; connect
  `FilmstripView`'s two new signals to `LibraryController`'s two new
  methods, clearing the editor first when the removed path(s) include
  the currently-open image.
- No existing method's signature or behavior changed. `remove_library`/
  `clear_library_entries` are untouched.

## 5. Nuances and failure modes

**Disk-deletion failure never undoes the catalog removal.** A
monkeypatched `Path.unlink` raising `OSError` still leaves the catalog
entry removed -- pinned by
`test_remove_entry_delete_from_disk_survives_oserror`.

**An in-flight background thumbnail task for a just-removed entry.**
`LibraryController._on_thumbnail_ready` (the background thumbnail
worker's completion callback) used to call `set_entry_thumbnail_cache_
key`/`refresh_entry_status` unconditionally, both of which raise
`KeyError` on an unknown path via `_require_entry`. Removing an entry
mid-flight (the entry's own thumbnail generation task was dispatched
before the removal, and completes afterward) surfaced this as an
uncaught exception in the Qt event loop during this slice's own test
development -- a **pre-existing latent race**, exposed here because
this is the first mutation that can make an entry vanish out from under
a thumbnail task still generating one for it (clearing/removing a whole
library already cancels the worker, but cancellation can't un-queue a
cross-thread signal for a task that already finished). Fixed by
wrapping that callback's body in `try/except KeyError`, treating "entry
no longer exists" as a no-op rather than letting it crash -- a small,
directly-related robustness fix kept in this slice rather than filed
separately, since this slice's own tests are what surfaced it.

**"Remove from Library" never touches the file.** Pinned at the
catalog layer (`test_remove_entry_removes_from_catalog_but_not_disk`)
and the controller layer
(`test_remove_entry_removes_from_catalog_leaves_file_by_default`).

**"Delete from Disk" actually deletes a real file.** Pinned with a
real `tmp_path`-backed file (no filesystem mocking) at
`test_remove_entry_delete_from_disk_deletes_real_file` and the batch
counterpart `test_remove_entries_batch_delete_from_disk_deletes_every_file`.

**Removing the currently-open image clears the editor; removing a
different one does not.** Pinned at the `MainWindow` UI layer:
`test_remove_entry_requested_clears_editor_when_removing_open_image`,
`test_remove_entry_requested_leaves_editor_alone_for_other_image`,
`test_remove_entries_requested_batch_clears_editor_when_included`.

**The dialog's three outcomes drive the right signal, and Cancel emits
nothing.** Pinned in the new `tests/unit/test_views/test_filmstrip_view.py`
by mocking `QMessageBox.exec`/`clickedButton` (for
`_prompt_remove_confirmation` directly) and `QMenu.exec` (for the
context-menu wiring end to end), for both the single-item and batch
menus.

**Favorite/Rating/Flag/Keywords/Collections/Edit-Date-&-Time
regression.** Every pre-existing test for those features (catalog
service, controller, and `main_window`/UI layers) was left completely
unmodified and still passes.

## 6. Test plan

- `tests/unit/test_services/test_library_catalog_service.py`:
  `test_remove_entry_removes_from_catalog_but_not_disk`,
  `test_remove_entry_round_trips_after_reload`,
  `test_remove_entry_is_noop_on_unknown_library`,
  `test_remove_entry_is_noop_on_unknown_path`.
- `tests/unit/test_controllers/test_library_controller.py`:
  `test_remove_entry_removes_from_catalog_leaves_file_by_default`,
  `test_remove_entry_delete_from_disk_deletes_real_file` (real
  `tmp_path` file, no mocking), `test_remove_entry_delete_from_disk_survives_oserror`
  (monkeypatches `Path.unlink` to raise), `test_remove_entry_no_op_on_unknown_path`,
  `test_remove_entries_batch_removes_all_and_refreshes_once`,
  `test_remove_entries_batch_delete_from_disk_deletes_every_file`,
  `test_remove_entries_no_op_on_empty_paths_or_no_current_library`.
- `tests/unit/test_views/test_filmstrip_view.py` (new file):
  `TestPromptRemoveConfirmation` (3 tests, one per dialog outcome) and
  `TestContextMenuRemoveWiring` (4 tests: single-item Delete from Disk,
  single-item Remove from Library, single-item Cancel-emits-nothing,
  and batch Delete from Disk), mocking `QMessageBox`/`QMenu.exec`.
- `tests/ui/test_main_window.py`:
  `test_remove_entry_requested_clears_editor_when_removing_open_image`,
  `test_remove_entry_requested_leaves_editor_alone_for_other_image`,
  `test_remove_entries_requested_batch_clears_editor_when_included`.

## 7. Rollout

Purely additive: one new catalog-service method, two new
controller methods plus one new private helper, two new `FilmstripView`
signals plus one new private dialog helper and two new context-menu
actions (after a separator, so the existing metadata actions above them
are visually unaffected), two new `MainWindow` connect calls plus three
new private handler methods, and three small new "reset to empty state"
methods (`ImageModel.clear`, `ImageView.clear`,
`ImageController.clear_image`). One small defensive fix
(`_on_thumbnail_ready`'s new `try/except KeyError`) to a pre-existing
callback, directly related to and exposed by this slice's own testing.
No existing method's signature changed. A plain revert removes the
feature entirely; nothing persists any new on-disk state that would
become stale leftover data the way a new `LibraryEntry` field would
(there is no new catalog field here at all -- `remove_entry` only ever
deletes existing entries).

## 8. Implementation summary

Added `LibraryCatalogService.remove_entry()`
(`src/services/library_catalog_service.py`) -- a pure catalog-removal
primitive, never touching the filesystem. Added
`LibraryController.remove_entry()`/`remove_entries()` plus
`_delete_file_from_disk()` (`src/controllers/library_controller.py`) --
the actual `Path.unlink(missing_ok=True)` call lives here, wrapped in
`try/except OSError` (logged, never raised, never undoing the already-
succeeded catalog removal); also fixed a pre-existing latent race in
`_on_thumbnail_ready` (now tolerates a `KeyError` for an entry removed
while its thumbnail was still generating). Added
`ImageModel.clear()`/`ImageView.clear()`/`ImageController.clear_image()`
(`src/models/image_model.py`, `src/views/image_view.py`,
`src/controllers/image_controller.py`) -- reuse the app's own existing
pre-load "no image" state rather than inventing a new one. Added
`FilmstripView.remove_requested`/`remove_batch_requested` signals, a new
`_prompt_remove_confirmation()` 3-way `QMessageBox` dialog, and one new
context-menu action each for the single-item and multi-select batch
menus (`src/views/widgets/filmstrip_view.py`). Added `MainWindow`
wiring (`_on_remove_entry_requested`/`_on_remove_entries_requested`/
`_clear_current_image_if_removed`) connecting the two new signals to the
two new controller methods, clearing the editor first when the removed
path(s) include the currently-open image
(`src/views/main_window.py`). Updated
`docs/planning/PRODUCT_ROADMAP.md` rows 2 and 4 to mark Remove/Delete
photo **Done for v1 scope**, with Duplicate/virtual copies called out
explicitly as the deliberate remaining architectural gap in both rows.

**Deviation notes / judgment calls.** (1) The 3-way confirmation dialog
was placed inside `FilmstripView` itself (mirroring "Edit Keywords..."/
"Edit Date & Time..."'s existing in-view-dialog precedent), not
`MainWindow` (whose own `QMessageBox.question` precedent, e.g.
`_on_remove_library_requested`, is a plain Yes/No for a different kind
of controller-level confirmation) -- both are real patterns already in
this codebase; this one was chosen because it keeps `MainWindow`'s
wiring purely additive, matching every other context-menu action's
wiring in this session. (2) No "Duplicate" was built in any form,
including a naive file-copy stand-in, per the task brief's own explicit
instruction -- documented above as a real architectural gap, not a
missing afterthought. (3) Plain `Path.unlink()` (no OS trash
integration) and no undo for disk deletion are both deliberate, simpler
v1 choices spelled out in the confirmation dialog's own wording, not
oversights.

Verification: new tests -- 4 added to
`tests/unit/test_services/test_library_catalog_service.py`, 7 added to
`tests/unit/test_controllers/test_library_controller.py`, 7 added in
the new `tests/unit/test_views/test_filmstrip_view.py`, 3 added to
`tests/ui/test_main_window.py` (21 new tests total); complete suite run
via
`QT_QPA_PLATFORM=offscreen python3 -m pytest -q --deselect tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::test_geometry_is_restored_on_next_launch`
-- see the calling session's own report for the exact pass count from
that run.

This completes the Remove/Delete half of Phase A's Edit-menu and
Photo-menu "Duplicate/Delete/Remove photo" coverage rows. Duplicate
(virtual copies) remains a separate, deliberately deferred architectural
gap in both rows, as documented above and in the roadmap itself.
