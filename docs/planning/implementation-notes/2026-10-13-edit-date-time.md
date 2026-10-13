# Edit Date & Time (a user-editable `captured_at` field)

Related roadmap: Phase A, Photo-menu coverage (PDF section 4) in
`docs/planning/PRODUCT_ROADMAP.md` -- the coverage table's row 4 note
listed "date/time" as a Gap alongside Photo Merge, Enhance, and
Versions. This slice closes that one item: "Edit Date & Time". Album
actions, Photo Merge, Enhance, and Versions remain separate, still-open
Gaps, untouched here.

This is library-metadata plumbing mirroring four existing, complete
features in this codebase almost exactly: **Favorite** (`bool`),
**Rating** (`int` 0-5), **pick/reject flag** (`str`, 3-state), and
**keywords** (`list[str]`). Every layer below was built by reading all
four end to end first and following their exact structure for this
new field.

## 1. Problem, goal, and non-goals

**Problem.** `LibraryEntry` already has `added_at` -- "when this photo
was imported into this library" -- set once at import time and never
changed again. There was no separate, user-editable "when this photo
was actually taken" timestamp. Lightroom's own "Edit Date & Time"
exists precisely because a camera's clock can be wrong, or a scanned
film photo has no capture-time metadata at all; the user needs to be
able to correct or supply that date directly, independent of (and
without disturbing) the immutable import-time record.

**Goal.** Add a `captured_at: str` field to `LibraryEntry` (ISO-8601,
defaulting to `added_at` at import time), a
`LibraryCatalogService.set_entry_captured_at()` setter (plus a batch
counterpart at the controller layer), a `LibraryController` delegate
(single and batch), a `FilmstripView` "Edit Date & Time..." context-menu
action (single item) and "Edit Date & Time for N Photos..." (multi-select
batch) using a small `QDateTimeEdit`-based dialog, and the `MainWindow`
wiring connecting both signals to the controller -- the same layers
Favorite/Rating/Flag/Keywords already use, mirrored field-for-field and
method-for-method, extended with this slice's own batch variant
following the just-landed multi-select-batch-actions pattern.

**Non-goals (explicit scope boundary for this slice):**

- **No real EXIF `DateTimeOriginal` auto-population at import time.**
  Grepping this codebase (`image_service.py`, `raw_service.py`) for
  EXIF usage before writing any code found exactly one use:
  `ImageOps.exif_transpose(pil)` in `image_service.py`, which reads EXIF
  *orientation* to correct pixel rotation -- it does not parse or expose
  any EXIF *date* tag, and no EXIF-metadata-reading infrastructure for
  display/import purposes exists anywhere else in the codebase. Building
  that (locating/parsing `DateTimeOriginal` across JPEG/RAW formats,
  handling files with no EXIF at all, deciding a fallback for those) is
  a substantially bigger, separate piece of infrastructure than this
  metadata-plumbing slice's scope. Per the task brief's own explicit
  instruction, this is a **deliberate, documented remaining gap**, not
  an oversight: `captured_at` defaults to `added_at` (the import
  timestamp) for every newly-imported entry, exactly like every other
  per-entry field in this codebase defaults to a safe, always-available
  value rather than attempting metadata extraction that doesn't exist
  yet.
- **No timezone handling beyond the existing `added_at`/`created_at`/
  `updated_at` convention.** Those three are all produced by
  `datetime.now(timezone.utc).isoformat()` -- UTC, timezone-aware. This
  slice does not change that convention for them, and does not impose
  timezone-awareness on `captured_at` either: a user-supplied value
  typed into the "Edit Date & Time..." dialog's `QDateTimeEdit` is a
  **naive** local date/time (`QDateTime.currentDateTime()` /
  `.toPyDateTime().isoformat()`, no explicit zone), stored and
  round-tripped exactly as given. This mirrors Lightroom's own "Edit
  Date & Time" UX, which edits a plain date/time, not a timezone
  conversion -- and avoids this slice inventing a timezone-reconciliation
  policy between a naive user edit and `added_at`'s UTC-aware default
  that nothing in the brief asked for.
- **No "shift all photos by N hours" batch feature.** Lightroom
  separately offers a date-shift tool (preserving relative offsets
  across a batch, e.g. "every photo in this import is 3 hours fast").
  This slice's batch variant is explicitly simpler and different: **set
  every selected photo to the exact same `captured_at` value** (useful
  for a batch of scanned film photos with no date metadata at all, all
  given one corrected date), never an additive/relative shift. This
  matches the task brief's explicit instruction and keeps the batch
  setter a trivial loop over the single-entry setter, exactly like
  `set_entries_rating`/`set_entries_flag` already are.
- **"Recently Added" sort is NOT changed to sort by `captured_at`.**
  `FilmstripView`'s `"recent"` filter mode
  (`entries.sort(key=lambda entry: str(entry.get("added_at", "")), reverse=True)`)
  continues to sort by `added_at` exactly as before. **Decision: leave
  it untouched.** Reasoning: "Recently Added" is a smart-collection
  label with an existing, well-defined meaning -- "when I imported this
  into my library" -- and changing what an existing, already-shipped
  sort control's name means out from under users (silently redefining
  "Recently Added" to mean "most recently captured" instead) is a
  product-semantics change riskier than this slice needs to make. A
  separate "Sort by Captured Date" option is a reasonable, minimal
  future addition (the same shape as Ratings' own deferred
  "no rating-based sorting" non-goal), but it is new sort-UI surface
  this slice does not build. No `filmstrip_view.py` sort code was
  touched.
- **No dedicated "Edit Date & Time" aggregate/filter/sidebar surface.**
  Matches every per-entry-field slice before it (Favorite got a
  dedicated filter row; Rating/Flag/Keywords did not) -- no new
  `_filter_mode` value, no `"captured_at"`-based count badge in
  `LibraryController._emit_libraries()`. `captured_at` is read back only
  through the context-menu dialog's pre-fill, not surfaced in the
  filmstrip item's tooltip (see Design below for why).

## 2. Current behavior (before this slice)

`LibraryEntry` had `added_at` (set once at import, in
`LibraryCatalogService._build_entry()`, and never mutated again by any
existing code path) but no separate, user-editable capture-time field.
`FilmstripView`'s context menu had "Edit Keywords..." (a plain
`QInputDialog.getText` free-text edit) as its only "open a dialog, parse
free text, emit a signal" action; nothing resembling a date/time picker
existed anywhere in the UI. `LibraryController._entry_payload()`/
`_on_thumbnail_ready()` already carried `"added_at"` in both payload
dicts (used only by the `"recent"` filter's sort key, never displayed),
but had no notion of a second, editable timestamp.

## 3. Design

### `LibraryEntry.captured_at: str = ""` and `_normalize_captured_at()`

Added directly alongside `collection_ids` in the dataclass, threaded
through the exact same `to_dict()`/`from_dict()` methods every other
field already uses. Unlike `_clamp_rating`/`_normalize_flag` (which each
fall back to one fixed literal, `0`/`"none"`, for every entry),
`captured_at` has no single universal sensible default -- the right
fallback for one entry (its own `added_at`, or on `set_entry_captured_at`,
its own current `captured_at`) is wrong for another. So the new
module-level helper takes the fallback as a parameter instead of
hard-coding one:

```python
def _normalize_captured_at(value, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        try:
            datetime.fromisoformat(value.strip())
        except ValueError:
            return fallback
        return value.strip()
    return fallback
```

This never raises: a missing key, `None`, a non-string, an empty/
whitespace-only string, or a string `datetime.fromisoformat()` rejects,
all fall back to `fallback` rather than propagating bad data or
crashing. A well-formed ISO-8601 string round-trips **unchanged** (not
re-formatted through `datetime`), so a user-supplied value with no
timezone offset is stored exactly as typed -- this is what lets the
"no timezone handling beyond the existing convention" non-goal hold:
the helper imposes no opinion of its own about timezone-awareness,
only syntactic validity.

In `LibraryEntry.from_dict()`, `added_at` is computed into a local
variable first (previously inlined directly into the constructor call)
so it can be passed as `captured_at`'s fallback:

```python
added_at = str(payload.get("added_at", _utc_now_iso()))
return cls(
    ...,
    added_at=added_at,
    ...,
    captured_at=_normalize_captured_at(payload.get("captured_at"), added_at),
)
```

In `LibraryCatalogService._build_entry()` (import time), the new entry
is constructed with `captured_at=added_at` directly -- the deliberate
"no real EXIF" default from the Non-goals above, spelled out in an
inline comment pointing at this note.

### `set_entry_captured_at`'s return contract: `Optional[LibraryEntry]`, not raise

**Deviation from the Rating/Flag/Keywords setters' exact shape, by the
task brief's own explicit instruction.** `set_entry_rating`/
`set_entry_flag`/`set_entry_keywords` all call
`_require_library`/`_require_entry`, which **raise** `KeyError` on an
unknown library id or path -- safe in practice only because their one
real caller, `LibraryController`, always guards with
`if not self._current_library_id or not file_path: return` first.
`set_entry_captured_at` instead follows the more defensive contract this
slice's brief explicitly asked for ("no-op on unknown library/path"),
matching the style `add_entry_to_collection`/
`remove_entry_from_collection` already use elsewhere in this same
service: `get_library()` (never raises) plus a `try/except KeyError`
around `_require_entry()`, returning `None` on either failure instead of
raising.

```python
def set_entry_captured_at(self, library_id, path, captured_at):
    library = self.get_library(library_id)
    if library is None:
        return None
    try:
        entry = self._require_entry(library, path)
    except KeyError:
        return None
    normalized = _normalize_captured_at(captured_at, entry.captured_at)
    if entry.captured_at == normalized:
        return entry
    entry.captured_at = normalized
    library.updated_at = _utc_now_iso()
    self._save_catalog()
    return entry
```

The no-op/dirty-save structure itself (normalize, compare, return early
if unchanged, otherwise mutate + bump `updated_at` + save) is otherwise
identical to every other per-entry setter in this service.

### `QDateTimeEdit`-based dialog, not a free-text `QInputDialog`

**Decision: a small `QDialog` containing one `QDateTimeEdit` (with
`setCalendarPopup(True)`) plus a standard OK/Cancel `QDialogButtonBox`.**
The task brief explicitly invited either a plain `QInputDialog.getText`
edit (matching "Edit Keywords..."'s own style) or a `QDateTimeEdit`-based
dialog "if trivial... only a LITTLE more code." This came out to
roughly 25 lines (`_prompt_for_captured_at()`) versus "Edit Keywords..."'s
~10-line `QInputDialog.getText` call plus its own comma-split parsing --
a little more code, but it buys **validation for free**: a
`QDateTimeEdit` simply cannot represent an invalid date/time (there is
no "unparseable text" state to defensively reject), unlike a free-text
field that would need its own `datetime.fromisoformat()` try/except and
a decision about what to do on failure. This is judged the better
trade for a date/time specifically (unlike keywords, which have no
natural structured-widget equivalent at all). It deliberately stops
short of a custom calendar-picker widget -- `QDateTimeEdit`'s built-in
`setCalendarPopup(True)` is the standard Qt widget, nothing hand-painted.

```python
def _prompt_for_captured_at(self, current_value: str) -> tuple[str | None, bool]:
    dialog = QDialog(self)
    dialog.setWindowTitle("Edit Date & Time")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Captured at:"))
    editor = QDateTimeEdit(dialog)
    editor.setCalendarPopup(True)
    editor.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
    initial = QDateTime.fromString(current_value, Qt.DateFormat.ISODate)
    if not initial.isValid():
        initial = QDateTime.currentDateTime()
    editor.setDateTime(initial)
    layout.addWidget(editor)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None, False
    return editor.dateTime().toPyDateTime().isoformat(), True
```

This directly answers the task brief's "parse/validate the user's input
defensively" requirement: there is no free-text parse step at all, so
there is nothing to reject -- an unparseable *pre-fill* value (e.g. a
corrupt stored `captured_at`) falls back to "now" via
`QDateTime.fromString(...).isValid()`, and the widget itself prevents
the user from ever typing something syntactically invalid in the first
place.

### `UserRole + 7`

`FilmstripView` already used `UserRole` (path) through `UserRole + 6`
(collection ids) -- confirmed by grepping every `UserRole` use in
`filmstrip_view.py` before picking a value, the same check every prior
slice's note records doing. `captured_at` is stored at the next unused
offset, **`UserRole + 7`** (a `str`), set in `_apply_entry_payload()`
alongside the other seven and read back in `_show_context_menu()` to
pre-fill the single-item dialog.

### No tooltip change

Unlike Rating/Flag/Keywords (each of which added its own line to the
existing `Favorite\n`-prefixed tooltip), `captured_at` is **not** added
to the tooltip. It is read back only to pre-fill the "Edit Date &
Time..." dialog. This was a judgment call: the tooltip already carries
four lines in the worst case (favorite + rating + flag + keywords) plus
the filename, and a date/time string is comparatively low-value
information to surface passively on hover versus the other four (which
are all "does this image need attention" signals) -- a reasonable
minimal v1 scope, not a limitation of the underlying data (the value is
fully available via the payload/`UserRole + 7` for any future tooltip
line a later slice wants to add).

### Context menu: one flat action (single), one flat action (batch)

Exactly like "Edit Keywords...", a single flat `menu.addAction("Edit
Date & Time...")` (no submenu -- there's nothing to enumerate, unlike
Rating's six-option submenu). The multi-select batch context menu gets
its own flat `"Edit Date & Time for {count} Photos..."` action,
following the same `{count}`-suffixed-label convention every other
batch action in that menu already uses. Both call the same
`_prompt_for_captured_at()` dialog helper -- the single-item branch
pre-fills the right-clicked item's current value; the batch branch
passes `""` (no single "current value" is well-defined across a
multi-item selection with potentially different timestamps, so it
pre-fills to "now" via the dialog's own fallback, exactly like a
corrupt/missing single-item value would).

### `LibraryController`/`MainWindow` wiring

`LibraryController.set_entry_captured_at(file_path, captured_at)`
mirrors `set_entry_rating`/`set_entry_flag`/`set_entry_keywords`
exactly: guard on `_current_library_id`/`file_path`, delegate to the
catalog service, then `_emit_libraries()` +
`_rebuild_entries_for_current_library()`. The batch counterpart,
`set_entries_captured_at(file_paths, captured_at)`, mirrors
`set_entries_rating`/`set_entries_flag` exactly: loop the per-entry
catalog-service call across every path, refresh views only **once** at
the end (not once per path). `"captured_at"` was added to **both**
`LibraryController._entry_payload()`'s and `_on_thumbnail_ready()`'s
payload dict literals -- the exact gap the task brief flagged as
recurring in the two most recent slices (Collections, multi-select
batch actions), caught here by reading both methods side-by-side before
editing either one, and confirmed by the existing
`test_entry_payload_and_thumbnail_ready_payload_have_identical_keys`
regression test (a pure key-set-equality check, so this slice's new key
makes it pass trivially as long as both dicts gained it, which they
did).

`MainWindow` adds two lines -- one per signal, single and batch --
immediately below the existing keywords/keywords-batch wiring:

```python
self._filmstrip_view.captured_at_changed.connect(
    self._library_controller.set_entry_captured_at
)
...
self._filmstrip_view.captured_at_batch_changed.connect(
    self._library_controller.set_entries_captured_at
)
```

## 4. Contracts

- `LibraryEntry.captured_at: str = ""` -- new dataclass field, threaded
  through `to_dict()`/`from_dict()` via a new module-level
  `_normalize_captured_at(value, fallback) -> str` helper. Never empty
  in practice once an entry exists: `_build_entry()` always seeds it to
  `added_at`, and `from_dict()`'s fallback is always `added_at` too.
- `LibraryCatalogService.set_entry_captured_at(self, library_id: str, path: str, captured_at: str) -> Optional[LibraryEntry]`
  -- new method; normalizes `captured_at` (falls back to the entry's own
  current value on malformed input); no-op (no save, no `updated_at`
  bump) if the normalized value is unchanged; returns `None` (not a
  raise) on an unknown library id or path.
- `LibraryController.set_entry_captured_at(self, file_path: str, captured_at: str) -> None`
  -- new method; delegates to the catalog service against
  `self._current_library_id`, then refreshes views exactly like
  `set_entry_rating`/`set_entry_flag`/`set_entry_keywords`.
- `LibraryController.set_entries_captured_at(self, file_paths: list[str], captured_at: str) -> None`
  -- new batch method; sets every given path to the SAME value (not an
  offset/shift), refreshing views only once.
- `LibraryController._entry_payload()`/`_on_thumbnail_ready()` per-entry
  payload dicts both now include `"captured_at": entry.captured_at`.
- `FilmstripView.captured_at_changed = pyqtSignal(str, str)` -- new
  signal (path, new ISO-8601 `captured_at` string), emitted by the
  single-item context menu's "Edit Date & Time..." action.
- `FilmstripView.captured_at_batch_changed = pyqtSignal(list, str)` --
  new batch signal (paths, new ISO-8601 `captured_at` string), emitted
  by the multi-select batch context menu's "Edit Date & Time for N
  Photos..." action.
- `FilmstripView` stores an item's `captured_at` at
  `Qt.ItemDataRole.UserRole + 7` (a `str`), the next unused offset after
  `UserRole + 6` (collection ids).
- `FilmstripView._prompt_for_captured_at(self, current_value: str) -> tuple[str | None, bool]`
  -- new private helper backing both the single-item and batch dialogs;
  returns `(new_iso_string, True)` on OK, `(None, False)` on Cancel.
- `MainWindow` connects `self._filmstrip_view.captured_at_changed` to
  `self._library_controller.set_entry_captured_at`, and
  `self._filmstrip_view.captured_at_batch_changed` to
  `self._library_controller.set_entries_captured_at`.
- No existing method's signature or behavior changed. Favorite's,
  Rating's, Flag's, and Keywords' item text, tooltip prefixes,
  `UserRole` offsets, context-menu actions, and signals are all
  unmodified. `FilmstripView`'s `"recent"` sort still sorts by
  `added_at`, untouched (see Non-goals).

## 5. Nuances and failure modes

**Old catalog files predating this slice.** A catalog JSON file written
before this slice has no `"captured_at"` key on any entry at all.
`LibraryEntry.from_dict()` computes `added_at` first, then passes it as
`_normalize_captured_at()`'s fallback for the missing `"captured_at"`
key, so loading an old catalog produces entries with
`captured_at == added_at` for every image, with no migration step and
no error -- pinned by
`test_captured_at_missing_from_old_catalog_payload_defaults_to_added_at`.

**Corrupt or malformed persisted values.** A hand-edited or corrupted
catalog file could contain `"captured_at": "definitely-not-a-timestamp"`
or any non-string type. `_normalize_captured_at()` falls back to
`added_at` (on load) or the entry's own current `captured_at` (on
`set_entry_captured_at`) rather than raising or propagating an invalid
value into the UI -- pinned by
`test_captured_at_from_corrupt_payload_falls_back_to_added_at` and
`test_set_entry_captured_at_falls_back_on_malformed_input`.

**`set_entry_captured_at` on an unknown library id or path.** Returns
`None` rather than raising -- pinned by
`test_set_entry_captured_at_returns_none_for_unknown_library_or_path`.
This is the one deliberate shape deviation from Rating/Flag/Keywords'
own setters noted in Design above.

**A corrupt/unparseable pre-fill value reaching the dialog.** The
dialog itself never sees an invalid string reach the `QDateTimeEdit`
widget: `QDateTime.fromString(current_value, Qt.DateFormat.ISODate)`
followed by an `.isValid()` check falls back to
`QDateTime.currentDateTime()` before `setDateTime()` is ever called --
pinned by `test_filmstrip_prompt_for_captured_at_rejects_invalid_date_via_widget`.

**Batch "set all to the same value", not a per-path offset.** Exactly
like `set_entries_rating`/`set_entries_flag`,
`set_entries_captured_at`/`captured_at_batch_changed` set every selected
path to the identical value the single dialog produced -- there is no
per-path date-shift/offset logic (explicitly out of scope, see
Non-goals) -- pinned by
`test_set_entries_captured_at_batch_sets_same_value_for_all` and
`test_filmstrip_batch_edit_date_time_emits_captured_at_batch_changed`.

**Favorite/Rating/Flag/Keywords regression.** Every pre-existing test
for those four features (catalog service, controller, and
filmstrip-view layers) was left completely unmodified and still passes,
confirming this slice's addition did not silently alter any of them.

## 6. Test plan

- `tests/unit/test_services/test_library_catalog_service.py`:
  `test_captured_at_defaults_to_added_at_for_new_entries`,
  `test_captured_at_state_survives_reload` (round-trip through a fresh
  `LibraryCatalogService` instance, mirroring
  `test_flag_state_survives_reload`),
  `test_set_entry_captured_at_is_a_no_op_when_unchanged` (asserts
  `library.updated_at` does not change on a second, identical call),
  `test_set_entry_captured_at_falls_back_on_malformed_input`,
  `test_set_entry_captured_at_returns_none_for_unknown_library_or_path`,
  `test_captured_at_missing_from_old_catalog_payload_defaults_to_added_at`,
  `test_captured_at_from_corrupt_payload_falls_back_to_added_at`.
- `tests/unit/test_controllers/test_library_controller.py`:
  `test_set_entry_captured_at_delegates_and_refreshes_entries`,
  `test_set_entries_captured_at_batch_sets_same_value_for_all` (mirrors
  `test_set_entries_rating_sets_all_to_same_value`, using the existing
  `_import_two_images` helper). The existing
  `test_entry_payload_and_thumbnail_ready_payload_have_identical_keys`
  (key-set equality only) was re-run unmodified and still passes with
  this slice's new `"captured_at"` key present in both dicts.
- `tests/unit/test_views/test_workspace_widgets.py`:
  `test_filmstrip_context_menu_edit_date_time_emits_captured_at_changed`
  (asserts the dialog is pre-filled with the item's current
  `captured_at` and that the emitted signal carries the dialog's
  returned value), `test_filmstrip_context_menu_edit_date_time_cancel_emits_nothing`,
  `test_filmstrip_prompt_for_captured_at_rejects_invalid_date_via_widget`
  (patches `QDialog.exec` only, to confirm the fallback-to-"now" behavior
  for a malformed pre-fill without a real modal event loop),
  `test_filmstrip_batch_edit_date_time_emits_captured_at_batch_changed`
  (multi-select; patches `QMenu.exec` to select the batch action and
  `FilmstripView._prompt_for_captured_at` to avoid driving a second real
  dialog).

## 7. Rollout

Purely additive: one new dataclass field (`LibraryEntry.captured_at`,
seeded to `added_at` at import, so every existing in-memory/freshly-
loaded entry is unaffected), one new catalog-service method, two new
controller methods (single + batch), two new dict keys added to
existing payload literals, two new `FilmstripView` signals plus an
extended (not replaced) single-item and batch context menu, one new
private dialog helper, and two new `MainWindow` connect calls. No
existing method's signature changed. A plain revert removes the feature
entirely; any `"captured_at"` keys already written to a catalog file by
this feature become inert, unread leftover JSON if the feature is
removed later -- the same revert-safety story every prior per-entry-
field slice (Ratings, Pick/Reject, Keywords) already documented for its
own leftover key.

## 8. Implementation summary

Added `captured_at: str = ""` to `LibraryEntry`
(`src/services/library_catalog_service.py`), threaded through
`to_dict()`/`from_dict()` with a new `_normalize_captured_at(value,
fallback)` module-level helper (fallback-parameterized, unlike
`_clamp_rating`/`_normalize_flag`'s fixed-literal fallbacks, since
`captured_at` has no single universal default). `_build_entry()` now
seeds every newly-imported entry's `captured_at` to its own `added_at`
(the deliberate "no real EXIF" default -- see Non-goals). Added
`LibraryCatalogService.set_entry_captured_at()`, following the
`add_entry_to_collection`-style defensive `Optional[...]`-return
contract (a documented, deliberate deviation from Rating/Flag/
Keywords' raise-on-unknown-path shape, per the task brief's explicit
instruction) with the same no-op-if-unchanged/bump-`updated_at`/save
structure every other setter uses. Added
`LibraryController.set_entry_captured_at()` and
`set_entries_captured_at()` (`src/controllers/library_controller.py`),
mirroring `set_entry_rating`/`set_entries_rating`, and added
`"captured_at": entry.captured_at` to **both**
`_entry_payload()`'s and `_on_thumbnail_ready()`'s payload dicts. Added
`FilmstripView.captured_at_changed`/`captured_at_batch_changed`
(`src/views/widgets/filmstrip_view.py`), a new
`_prompt_for_captured_at()` helper backing a small `QDateTimeEdit` +
OK/Cancel `QDialog` (chosen over a free-text `QInputDialog.getText`
edit for its built-in validation, per the task brief's own invitation),
stored the value at `UserRole + 7`, and extended both the single-item
and multi-select batch context menus in place with an "Edit Date &
Time..." / "Edit Date & Time for N Photos..." action each. Added two
new `MainWindow` connect lines
(`captured_at_changed` -> `set_entry_captured_at`,
`captured_at_batch_changed` -> `set_entries_captured_at`) directly below
the existing keywords/keywords-batch wiring. Updated
`docs/planning/PRODUCT_ROADMAP.md`'s coverage-table row 4 to mark Edit
Date & Time **Done for v1 scope**, with real EXIF auto-population
listed explicitly as the deliberate remaining gap, alongside album
actions/Photo Merge/Enhance/Versions.

**Deviation notes.** Two "your call" design decisions documented above,
both per the task brief's own explicit invitation to use judgment:
(1) `set_entry_captured_at` returns `Optional[LibraryEntry]`/no-ops on
an unknown library or path, rather than raising like
Rating/Flag/Keywords' setters do -- the task brief's own wording for
this method ("no-op on unknown library/path") directly specified this
shape, overriding the more general "mirror Rating/Flag's exact shape"
instruction where the two conflicted. (2) A `QDateTimeEdit`-based
dialog was built instead of a plain `QInputDialog.getText` edit, for
its free input validation; "Recently Added" sort was left sorting by
`added_at` (not changed to sort by `captured_at`), as a deliberately
narrower, lower-risk v1 scope; a batch variant WAS built (the
"set all selected to the same value" case the task brief called out as
"a reasonable, in-scope extension given the infrastructure now exists"
and "useful for a scanned batch of old film photos with no EXIF at
all"), following the just-landed `set_entries_rating`/`set_entries_flag`
pattern exactly, with no awkwardness found that would have justified
skipping it.

Verification: new tests -- 7 added to
`tests/unit/test_services/test_library_catalog_service.py`, 2 added to
`tests/unit/test_controllers/test_library_controller.py`, 4 added to
`tests/unit/test_views/test_workspace_widgets.py` (13 new tests total);
complete suite run via
`QT_QPA_PLATFORM=offscreen python3 -m pytest -q --deselect tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::test_geometry_is_restored_on_next_launch`
**1451 passed, 1 skipped, 1 deselected in 175.09s** (the deselected test
is the same pre-existing offscreen-rendering flake noted in every prior
implementation note, unrelated to this slice; the 1 skipped test is
pre-existing and unrelated). No failures or flakes observed in this
run.

This completes the "date/time" half of Phase A's Photo-menu coverage
row that this slice set out to close. Album actions, Photo Merge,
Enhance, and Versions remain separate, still-open Gaps in that same
row; real EXIF-based `captured_at` auto-population at import time
remains the one deliberate, documented gap within this slice's own
scope.
