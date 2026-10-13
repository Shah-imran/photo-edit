# Pick/Reject flags (tri-state marker)

Related roadmap: Phase A, "Library DAM and workspace chrome" (PDF
sections 8-9, 24) in `docs/planning/PRODUCT_ROADMAP.md` -- the bullet
"**Ratings** and **pick/reject** (or flags); **keywords** on disk or
sidecar (design choice: XMP vs JSON)." The prior slice
(`docs/planning/implementation-notes/2026-10-13-ratings.md`) built the
Ratings half of that bullet and explicitly deferred pick/reject flags
as "the next slice." This note is that slice. Keywords remain a
separate, still-undone gap -- not covered here either.

This is library-metadata plumbing mirroring two existing, complete
features in this codebase almost exactly: **Favorite** (a per-image
boolean) and, more recently and more closely, **Rating** (a per-image
`int` 0-5). Every layer below was built by reading both end to end
first and following their exact structure for the flag.

## 1. Problem, goal, and non-goals

**Problem.** There was no way to mark an image as a keeper ("Pick") or
a reject, independent of the 0-5 star rating or the boolean Favorite.
Lightroom calls this the pick/reject flag; it is a tri-state marker,
not a boolean and not a graded scale.

**Goal.** Add a `flag: str` (one of `"none"`/`"pick"`/`"reject"`)
field to `LibraryEntry`, a `LibraryCatalogService.set_entry_flag()`
setter, a `LibraryController.set_entry_flag()` delegate, a
`FilmstripView` context-menu section ("Flag as Pick" / "Flag as
Reject" / "Remove Flag") emitting `flag_changed`, and the one-line
`MainWindow` wiring connecting the two -- the same five layers
Favorite and Rating already use, mirrored field-for-field and
method-for-method.

**Non-goals (explicit scope boundary for this slice):**

- **Keywords are not this slice.** The roadmap bullet mentions them
  too; they remain an undone Gap, unrelated to the work here.
- **No dedicated "Pick"/"Reject" filter/collection entry in the
  library sidebar.** Matching Ratings' own non-goal (itself narrower
  than Favorites' dedicated filter row): no new sidebar row, no new
  `_filter_mode` value, no `"pick_count"`/`"reject_count"`-style
  aggregate in `LibraryController._emit_libraries()`. A flag is
  surfaced via the filmstrip item's **tooltip only** (see Design
  below), exactly like Rating.
- **No flag-based sorting.** `FilmstripView`'s existing sort control
  (`"added"`/`"name"`) is untouched.
- **No change to the existing favorite "★" item-text display.** The
  item's `text()` is still reserved for the favorite marker only; the
  flag (like the rating) is tooltip-only.

This completes both halves of the roadmap bullet's "Ratings and
pick/reject (or flags)" scope: Ratings (previous slice) and pick/reject
flags (this slice) are now both **Done**. Keywords remains the one
still-open item in that bullet.

## 2. Current behavior (before this slice)

`LibraryEntry` had `favorite: bool` and `rating: int` but no notion of
a pick/reject flag at all. `FilmstripView`'s `_apply_entry_payload()`
read `payload.get("favorite", False)` and `payload.get("rating", 0)`
to build the item's text/tooltip/stored `UserRole` data; its
`_show_context_menu()` had a Favorite toggle action and a "Set Rating"
submenu, but nothing for pick/reject.
`LibraryController._entry_payload()`/`_on_thumbnail_ready()` already
included `"favorite"` and `"rating"` in both per-entry payload dicts;
neither included anything about a flag, because there was nothing to
include.

## 3. Design

### Representation: a validated `str`, not a `bool` or an `Enum`

The flag is a plain `str` field (`flag: str = "none"`), with exactly
three valid values: `"none"`, `"pick"`, `"reject"`. This follows the
same convention every other per-entry metadata field in this codebase
already uses -- `favorite: bool`, `rating: int` -- simple JSON-primitive
types that round-trip through `to_dict()`/`from_dict()` with no custom
(de)serialization step. A Python `Enum` would need its own
serialization glue (`.value` on write, `Enum(value)` on read, with a
`try`/`except` for invalid values) to get the same JSON-primitive
round-trip that a bare `str` gets for free; introducing one here would
be a bigger structural change than this slice's scope calls for, for a
field with only three possible values. A `str` with a validated/
clamped allowed-value set follows the existing convention most
directly.

### `_normalize_flag(value) -> str` helper

Mirrors `_clamp_rating`'s "coerce defensively, never raise on bad
persisted data" pattern, module-level in
`library_catalog_service.py`:

```python
def _normalize_flag(value) -> str:
    if value in ("pick", "reject"):
        return value
    return "none"
```

This covers every case `_clamp_rating` covers for its own field: a
missing key (`payload.get("flag", "none")` already defaults to
`"none"` before this even runs), `None`, a corrupt/garbage string, or
a wrong type entirely (e.g. a stray `int` or `list` in a hand-edited
catalog file) -- all coerce to `"none"`, never raise.

`FilmstripView` keeps its own small local copy of this same helper,
rather than importing the catalog service's. This mirrors the
**already-existing** precedent `_clamp_rating` set in the Ratings
slice: both `library_catalog_service.py` and `filmstrip_view.py` each
keep their own private copy of `_clamp_rating`, not a shared one.
Confirmed by reading both files before writing this slice's version --
`filmstrip_view.py`'s `_clamp_rating` coerces an incoming payload value
defensively for UI purposes, while the catalog service's own
`_clamp_rating` guards persisted data; they happen to do the same
thing but serve different layers, and this slice's `_normalize_flag`
duplicates that same shape rather than introducing a new shared-module
refactor.

### Clamp (normalize) vs. raise in `set_entry_flag`

**Decision: normalize, not raise.** Mirrors `set_entry_rating`'s own
decision exactly, for the same reason: the one real call site
(`FilmstripView`'s context menu) only ever passes one of the three
well-formed values anyway, so defensive normalization is pure
defense-in-depth against a future caller or a programming error, not
user-facing validation that needs to exist. A raise would turn an
easily-recoverable mistake into a hard crash for no behavioral benefit.

### `set_entry_flag`'s no-op/dirty-save structure

Mirrors `set_entry_favorite`/`set_entry_rating` exactly: look up the
entry via `_require_entry`, normalize the incoming value, return early
(no `library.updated_at` bump, no `_save_catalog()` call) if the
normalized value equals the entry's current `flag`, otherwise mutate
the entry, bump `library.updated_at`, and save.

### `UserRole` offset: `UserRole + 4`

`FilmstripView` already used `UserRole` (path), `UserRole + 1`
(status), `UserRole + 2` (favorite), `UserRole + 3` (rating) --
confirmed by grepping every `UserRole` use in `filmstrip_view.py`
before picking a value. The flag is stored at **`UserRole + 4`** (a
`str`, `"none"`/`"pick"`/`"reject"`), the next unused offset, set in
`_apply_entry_payload()` alongside the other four and read back in
`_show_context_menu()` to decide whether to show "Remove Flag" and
what the item's current flag is.

### Tooltip-only flag display

In `_apply_entry_payload()`, the flag line is appended to the *same*
prefix-building logic that already builds the favorite line and the
rating line, after both, without disturbing either:

```python
prefix = ("Favorite\n" if favorite else "")
if rating > 0:
    prefix += f"Rating: {'★' * rating}{'☆' * (5 - rating)}\n"
if flag == "pick":
    prefix += "Pick\n"
elif flag == "reject":
    prefix += "Rejected\n"
item.setToolTip(prefix + tooltip)
```

`item.setText(...)` is completely untouched -- it still only ever
reflects `favorite`. All three signals (favorite, rating, flag) can
appear in the same tooltip simultaneously, each on its own line, in
that fixed order (favorite, then rating, then flag), e.g.
`"Favorite\nRating: ★★★★★\nPick\n<name>"`.

### Context menu: flat actions, not a submenu

`_show_context_menu()` was extended in place (not duplicated) with a
third menu section. **Decision: three flat actions** ("Flag as Pick",
"Flag as Reject", "Remove Flag"), not a `QMenu("Set Flag")` submenu
like Rating's six-option "Set Rating" submenu. Rationale: a submenu
earns its keep when collapsing many options (Rating's six) into one
top-level entry; for exactly three options, a submenu adds an extra
click/hover level for no payoff, and three flat top-level actions read
at least as cleanly in this menu's existing visual structure (which
already mixes flat actions -- the Favorite toggle -- with a submenu --
Set Rating). "Remove Flag" is shown only when the item's current flag
is not `"none"` (read off `UserRole + 4`), avoiding an always-present
no-op action; "Flag as Pick" and "Flag as Reject" are always shown
(selecting the flag the item is already set to is a harmless no-op at
the service layer, since `set_entry_flag` already no-ops on an
unchanged value).

### `LibraryController`/`MainWindow` wiring

`LibraryController.set_entry_flag(file_path, flag)` mirrors
`set_entry_favorite`/`set_entry_rating` exactly: guard on
`_current_library_id`/`file_path`, delegate to
`self._catalog_service.set_entry_flag(self._current_library_id, file_path, flag)`,
then `self._emit_libraries()` and
`self._rebuild_entries_for_current_library()` the same way. No
`"pick_count"`/`"reject_count"` aggregate was added to
`_emit_libraries()`'s per-library payload, for the same reason Ratings
added no `"rating_count"` (see Non-goals). `"flag"` *was* added to
both of `LibraryController`'s per-entry payload dict literals
(`_entry_payload()` and `_on_thumbnail_ready()`), alongside their
existing `"favorite"`/`"rating"` lines.

`MainWindow` adds one line, immediately below the existing rating
wiring:

```python
self._filmstrip_view.flag_changed.connect(
    self._library_controller.set_entry_flag
)
```

## 4. Contracts

- `LibraryEntry.flag: str = "none"` -- new dataclass field, threaded
  through `to_dict()`/`from_dict()` via a new module-level
  `_normalize_flag(value) -> str` helper.
- `LibraryCatalogService.set_entry_flag(self, library_id: str, path: str, flag: str) -> LibraryEntry`
  -- new method; normalizes `flag` to `"none"`/`"pick"`/`"reject"`;
  no-op (no save, no `updated_at` bump) if the normalized value is
  unchanged.
- `LibraryController.set_entry_flag(self, file_path: str, flag: str) -> None`
  -- new method; delegates to the catalog service against
  `self._current_library_id`, then refreshes views exactly like
  `set_entry_favorite`/`set_entry_rating`.
- `LibraryController._entry_payload()`/`_on_thumbnail_ready()` per-entry
  payload dicts both now include `"flag": entry.flag`.
- `FilmstripView.flag_changed = pyqtSignal(str, str)` -- new signal
  (path, new flag value `"none"`/`"pick"`/`"reject"`), emitted by the
  context menu's "Flag as Pick"/"Flag as Reject"/"Remove Flag" actions.
- `FilmstripView` stores an item's flag at
  `Qt.ItemDataRole.UserRole + 4` (a `str`), alongside the existing
  `UserRole` (path), `UserRole + 1` (status), `UserRole + 2`
  (favorite), `UserRole + 3` (rating).
- `MainWindow` connects `self._filmstrip_view.flag_changed` to
  `self._library_controller.set_entry_flag`.
- No existing method's signature or behavior changed. Favorite's and
  Rating's item text, tooltip prefixes, `UserRole` offsets,
  context-menu actions, and signals are all unmodified.

## 5. Nuances and failure modes

**Old catalog files predating this slice.** A catalog JSON file
written before this slice has no `"flag"` key on any entry at all.
`LibraryEntry.from_dict()`'s `payload.get("flag", "none")` already
defaults cleanly to `"none"` before `_normalize_flag` even runs, so
loading an old catalog produces entries with `flag == "none"` for
every image, with no migration step and no error. Pinned directly by
`test_flag_missing_from_old_catalog_payload_defaults_to_none`, which
also re-confirms `favorite`/`rating` default correctly in the same
payload (mirroring the equivalent Ratings-slice test that itself
re-confirmed `favorite`'s default).

**Corrupt or garbage persisted values.** A hand-edited or corrupted
catalog file could contain `"flag": "corrupt-garbage-value"` or any
non-string type. `_normalize_flag()` coerces all of these to `"none"`
rather than raising or propagating an invalid value into the UI --
pinned by `test_flag_from_corrupt_payload_normalizes_to_none` and
`test_set_entry_flag_normalizes_garbage_values_to_none` (the latter
covering both a garbage string and `None` passed directly to the
setter).

**Favorite, rating, and flag coexisting in one tooltip.** Explicitly
tested: a favorited, 5-star, picked entry's tooltip is
`"Favorite\nRating: ★★★★★\nPick\n<name>"` -- all three lines present,
in that fixed order, none overwriting another.

**Favorite/Rating regression.** Every pre-existing Favorite and
Rating test (catalog service, controller, and filmstrip-view layers)
was left completely unmodified and still passes unchanged, confirming
this slice's addition did not silently alter either feature.

## 6. Test plan

- `tests/unit/test_services/test_library_catalog_service.py`:
  `test_flag_state_survives_reload` (round-trip through a fresh
  `LibraryCatalogService` instance, mirroring
  `test_rating_state_survives_reload`),
  `test_flag_defaults_to_none_for_new_entries`,
  `test_set_entry_flag_is_a_no_op_when_unchanged` (asserts
  `library.updated_at` does not change on a second, identical call),
  `test_set_entry_flag_normalizes_garbage_values_to_none` (a garbage
  string and `None`),
  `test_flag_missing_from_old_catalog_payload_defaults_to_none` (an
  old-format payload missing the `"flag"` key entirely, also
  re-checking `favorite`/`rating` default correctly),
  `test_flag_from_corrupt_payload_normalizes_to_none`.
- `tests/unit/test_controllers/test_library_controller.py`:
  `test_set_entry_flag_delegates_and_refreshes_entries` (asserts the
  controller delegates to the catalog service and triggers an
  `entries_rebuilt` signal whose payload carries the new flag),
  mirroring `test_set_entry_rating_delegates_and_refreshes_entries`.
- `tests/unit/test_views/test_workspace_widgets.py`:
  `test_filmstrip_flag_appears_in_tooltip_only_and_leaves_text_alone`,
  `test_filmstrip_favorite_rating_and_flag_all_show_in_tooltip_together`,
  `test_filmstrip_context_menu_flag_as_pick_emits_flag_changed`,
  `test_filmstrip_context_menu_flag_as_reject_emits_flag_changed`,
  `test_filmstrip_context_menu_remove_flag_emits_none`, and
  `test_filmstrip_context_menu_remove_flag_absent_when_unflagged`
  (patches `QMenu.exec` to deterministically "select" a specific
  action, or to inspect the built menu's action list without actually
  selecting anything, without a real modal event loop).
- Explicit regression check: every pre-existing Favorite and Rating
  test in all three files above was re-run unmodified as part of the
  full suite and still passes (see Verification below) -- no new
  regression test was needed beyond running the existing suite, since
  none of those tests' source lines changed.

## 7. Rollout

Purely additive: one new dataclass field (`LibraryEntry.flag`, default
`"none"`, so every existing in-memory/freshly-loaded entry is
unaffected), one new catalog-service method, one new controller
method, two new dict keys added to existing payload literals, one new
`FilmstripView` signal plus an extended (not replaced) context menu,
and one new `MainWindow` connect call. No existing method's signature
changed. A plain revert removes the feature entirely; any `"flag"`
keys already written to a catalog file by this feature become inert,
unread leftover JSON if the feature is removed later (the same
revert-safety story "Ratings" documented for its own leftover
`"rating"` key, and "Import presets" documented before that).

## 8. Implementation summary

Added `flag: str = "none"` to `LibraryEntry`
(`src/services/library_catalog_service.py`), threaded through
`to_dict()`/`from_dict()` with a new `_normalize_flag()` module-level
helper, plus `LibraryCatalogService.set_entry_flag()` mirroring
`set_entry_rating()`'s no-op/dirty-save structure exactly (normalize,
not raise, on an invalid input). Added `LibraryController.set_entry_flag()`
(`src/controllers/library_controller.py`), mirroring
`set_entry_rating()`, and added `"flag": entry.flag` to both of
`_entry_payload()`'s and `_on_thumbnail_ready()`'s payload dicts.
Added `FilmstripView.flag_changed = pyqtSignal(str, str)`
(`src/views/widgets/filmstrip_view.py`), a local `_normalize_flag()`
helper mirroring the file's existing local `_clamp_rating()`, extended
`_apply_entry_payload()` to store the flag at `UserRole + 4` and append
a `"Pick\n"`/`"Rejected\n"`-style tooltip line (only when not
`"none"`, never touching the existing favorite item-text or either
existing tooltip prefix), and extended `_show_context_menu()` in place
with three flat actions ("Flag as Pick", "Flag as Reject", "Remove
Flag" -- the last shown only when a flag is currently set). Added the
one-line
`self._filmstrip_view.flag_changed.connect(self._library_controller.set_entry_flag)`
wiring to `src/views/main_window.py`, directly below the existing
rating wiring. Updated `docs/planning/PRODUCT_ROADMAP.md`'s Phase A
bullet and the coverage table's PDF row 4 to mark pick/reject flags
**Done** alongside Ratings, leaving keywords as the one remaining
**Gap** in that bullet.

**Deviation note.** None of substance. One "your call" design decision
documented above, per the task brief's own invitation: flat
context-menu actions (not a submenu) for the three-option Pick/Reject
choice, and showing "Remove Flag" only when a flag is already set.

Verification: new tests -- 6 added to
`tests/unit/test_services/test_library_catalog_service.py`, 1 added to
`tests/unit/test_controllers/test_library_controller.py`, 6 added to
`tests/unit/test_views/test_workspace_widgets.py` (13 new tests
total); complete suite run via
`QT_QPA_PLATFORM=offscreen python3 -m pytest -q --deselect tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::test_geometry_is_restored_on_next_launch`
**962 passed, 1 skipped, 1 deselected in 128.75s** (962 = the prior
slice's 949 passed + 13 new tests this slice added; the deselected
test is the same pre-existing offscreen-rendering flake noted in prior
implementation notes, unrelated to this slice; the 1 skipped test is
pre-existing and unrelated). No failures observed in this run,
including no recurrence of the previously-noted
`TestLibraryPanel::test_clear_library` background-thumbnail-thread
teardown timing race (a pre-existing, unrelated intermittent flake
noted in the Ratings slice's own note).

This completes the pick/reject half of Phase A's "Ratings and
pick/reject (or flags); keywords" bullet. Combined with the prior
Ratings slice, both halves of that bullet's rating/flag scope are now
**Done**; keywords remains explicitly undone and is a separate,
future Gap.
