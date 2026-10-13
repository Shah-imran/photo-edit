# Filmstrip search box (filename substring filter)

Related roadmap: Phase A, "Library DAM and workspace chrome" (PDF
sections 8-9, 24) in `docs/planning/PRODUCT_ROADMAP.md` -- the bullet
"**Search** box filtering library." This is a self-contained UI
addition to `FilmstripView`, the same widget that already implements
`set_filter`/`set_sort` (the Filter/Sort smart-collection controls).
No new processor, controller, or catalog-service change was needed:
this is a pure client-side filter over the same already-loaded
`self._entries` list those two controls already operate on.

## 1. Problem, goal, and non-goals

**Problem.** `FilmstripView` had a Filter menu (All/Favorites/Recent)
and a Sort menu (Date Added/File Name), but no way to narrow the strip
by typing a search term -- the roadmap's "Search box filtering
library" bullet was entirely unimplemented.

**Goal.** Add a `QLineEdit` search box to `FilmstripView`'s header
that filters the same `self._entries` list by a case-insensitive
filename substring match, composable with the existing filter mode and
sort mode (a user can combine Favorites + a search term + Sort by
Name, all three active at once).

**Non-goals (explicit scope boundary for this slice):**

- **No search across keywords or other metadata beyond filename.**
  Keywords do not exist anywhere in this codebase yet (confirmed: no
  `keyword` field on `LibraryEntry`, no keyword UI) -- that remains a
  separate, still-open Gap noted in the Ratings and Pick/Reject
  implementation notes and the Phase A roadmap bullet itself. This
  slice searches the filename only.
- **No fuzzy or typo-tolerant matching.** Plain case-insensitive
  substring containment only, mirroring the simplicity of the existing
  sort-by-name comparison (`str(...).casefold()` for sorting;
  `.lower()` for the search match).
- **No persisted/remembered search text across app restarts.** The
  search box resets to empty (`""`) each time a fresh `FilmstripView`
  is constructed. This matches the existing behavior of
  `_filter_mode`/`_sort_mode`: grepping both names across `src/`
  outside `filmstrip_view.py` turns up nothing -- neither is read from
  or written to `SettingsService`/`QSettings` anywhere, so Filter and
  Sort mode are *also* not persisted across restarts today. Not
  persisting the search text is therefore consistent with, not a
  regression from, how the two sibling controls already behave.
- **No dedicated top-level Search panel.** PDF Sec.8 describes a
  search box plus a results/suggestions panel on the right, a larger
  piece of shell UI. This slice is scoped to the filmstrip's own
  compact header, matching the existing Filter/Sort controls' scope;
  the coverage table's Sec.8 row is updated below to describe this
  narrower, filmstrip-level search accurately rather than overstate
  it as the full panel.

## 2. Current behavior (before this slice)

`FilmstripView.__init__` built a header `QHBoxLayout` with
`_source_label`, `_count_label`, a stretch, `_filter_button`, and
`_sort_button`. `_render_entries()` read `self._entries`, applied
`self._filter_mode` ("favorites" keeps only `entry.get("favorite",
False)`; "recent" sorts by `added_at` descending) and then
`self._sort_mode` ("name" sorts by
`str(entry.get("filename") or entry.get("path", "")).casefold()`)
before populating `self._list`. There was no text-entry widget and no
search state at all.

## 3. Design

### Widget placement and sizing

The `QLineEdit` (`self._search_edit`) is inserted into the header
layout immediately after the existing `header.addStretch(1)` call and
before `self._filter_button` is added -- i.e. it sits to the left of
the Filter/Sort buttons, at the right-hand side of the header, visually
grouped with them as a small toolbar. This keeps `_source_label` and
`_count_label` exactly where they were on the far left, disturbs
nothing about the existing widgets' relative order, and reads as "the
controls that narrow what's shown" clustered together.

It is given a fixed width (`160px`) so it cannot dominate the compact
(112-132px tall) header, and a small stylesheet matching the header's
existing dark-chrome palette (background `#2a2a2a`, text `#e7e9ec`,
border `#3a3a3a`) consistent with `_filter_button`/`_sort_button`'s own
styling conventions elsewhere in this widget.

`setClearButtonEnabled(True)` is used -- confirmed as a real,
documented `QLineEdit` method (Qt's own built-in "clear" action that
appears as a small x icon once text is present) by checking PyQt6's
`QLineEdit` API before using it. It is a one-line, zero-risk addition:
it needs no extra signal wiring (clearing the text already fires
`textChanged` with `""`, which flows through the normal
`set_search_text` path), so it was included rather than skipped.

### `set_search_text(self, text: str) -> None`

```python
def set_search_text(self, text: str) -> None:
    normalized = text.strip().lower()
    if normalized == self._search_text:
        return
    self._search_text = normalized
    self._render_entries()
```

**Normalization: `strip().lower()`, not bare `.lower()`.** A search
for `"  sunset"` (accidental leading space from a trackpad slip or
paste) should behave identically to `"sunset"` -- stripping
leading/trailing whitespace before comparing is the more forgiving,
expected behavior and costs nothing, since no legitimate filename
substring match depends on leading/trailing whitespace in the *search
term* itself (the filenames being matched against are not stripped --
only the search term is).

**No-op guard, and whether it is actually needed.** The spec asked to
confirm whether `QLineEdit.textChanged` already avoids firing on a
true no-op, rather than assume. Checked: `textChanged` fires whenever
the line edit's displayed text actually changes (Qt diffs the text
internally), so typing into an already-empty box and deleting
immediately, or two identical keystrokes, do not cause duplicate
signal emissions at the *widget* level. However, the guard in
`set_search_text` is not redundant: it protects against a *different*
case the widget-level dedup cannot see -- the normalized form. Typing
`"Sun"` then `"SUN"` fires two distinct `textChanged` signals (the raw
text did change), but both normalize to `"sun"`; without the guard,
the second keystroke would trigger a needless second
`_render_entries()` call (a full list-widget rebuild) for a result
that is byte-for-byte identical to what's already showing. The guard
is cheap and removes that redundant render, mirroring the same
"no-op if unchanged" reasoning `LibraryCatalogService.set_entry_favorite`/
`set_entry_rating`/`set_entry_flag` apply at the service layer (skip
the write/signal-emit entirely when the normalized value already
matches current state) -- applied here at the UI layer instead, since
`FilmstripView` holds no persisted state to save, only a rebuild to
skip.

### Composing with filter mode and sort mode in `_render_entries()`

The search filter is added as a third, independent filtering stage,
inserted **after** the existing filter-mode branch and **before** the
sort step:

```python
entries = list(self._entries)
if self._filter_mode == "favorites":
    entries = [entry for entry in entries if entry.get("favorite", False)]
elif self._filter_mode == "recent":
    entries.sort(key=lambda entry: str(entry.get("added_at", "")), reverse=True)
if self._search_text:
    entries = [
        entry
        for entry in entries
        if self._search_text in str(entry.get("filename") or entry.get("path", "")).lower()
    ]
if self._sort_mode == "name":
    entries.sort(key=lambda entry: str(entry.get("filename") or entry.get("path", "")).casefold())
```

**Why filter-before-sort.** Filtering first shrinks the list before
the (more expensive, comparison-heavy) sort runs over it -- the more
natural and marginally more efficient order, and it does not change
the observable result either way since filtering and sorting here are
independent operations over disjoint concerns (membership vs. order).

**Field choice: `filename` falling back to `path`.** This reuses
*exactly* the same field-selection expression the pre-existing
sort-by-name logic already uses
(`entry.get("filename") or entry.get("path", "")`), not a new or
different field. Reading the entry payload shape confirmed this is the
right, already-available field: `_entry("...")` test fixtures and the
real `LibraryController` payload dicts both carry `"filename"` (and
always carry `"path"`), while `"rating"` (`int`) and `"flag"`
(`"none"`/`"pick"`/`"reject"`) are numeric/enum-like fields with no
meaningful "substring of a filename" semantics -- a user typing
`"pick"` into a *filename* search box searching for a literal
"pick"-named file (e.g. `pickup_truck.jpg`) is the correct, unsurprising
behavior; treating `"pick"` as a secret shorthand for "flag == pick"
would be a surprising, undocumented second meaning for the same input
and was explicitly not built, per the spec's own scoping to
filename-only search.

### Empty-string regression safety

`if self._search_text:` is false for `""`, so the search filtering
list comprehension is skipped entirely and `entries` passes through
unchanged when no search term is active -- byte-for-byte the same
code path that existed before this slice. This is pinned directly by
`test_filmstrip_search_cleared_restores_all_entries` and is implicit
in every other pre-existing filter/sort test, none of which call
`set_search_text` at all and therefore exercise `self._search_text ==
""` (its `__init__` default) throughout.

## 4. Contracts

- `FilmstripView.__init__` now sets `self._search_text: str = ""`
  alongside the existing `self._filter_mode`/`self._sort_mode` state.
- `FilmstripView._search_edit: QLineEdit` -- new header widget,
  placeholder "Search photos...", fixed width 160px, built-in clear
  button enabled, `textChanged` connected to `set_search_text`.
- `FilmstripView.set_search_text(self, text: str) -> None` -- new
  public method. Normalizes via `strip().lower()`, stores the result
  on `self._search_text`, no-ops (no re-render) if the normalized value
  is unchanged, otherwise calls `self._render_entries()`.
- `FilmstripView._render_entries()` -- extended (not replaced) with a
  third filtering stage: when `self._search_text` is non-empty, keeps
  only entries whose `entry.get("filename") or entry.get("path", "")`
  (lowercased) contains `self._search_text` as a substring. Runs after
  the filter-mode branch and before the sort-mode branch. An empty
  `self._search_text` is a complete no-op, identical to pre-slice
  behavior.
- No existing method's signature changed. `set_filter`, `set_sort`,
  `set_entries`, `update_entry_thumbnail`, `current_path`, `count`, and
  every context-menu/signal behavior are all unmodified.

## 5. Nuances and failure modes

**Search with no matches.** An empty result list is valid and
expected -- `_render_entries()` already handles an empty `entries` list
unconditionally (it is the same code path a from-scratch empty library
or an all-filtered-out Favorites view already exercises), clearing
`self._list` and setting the count label to `"0 photos"`. Pinned by
`test_filmstrip_search_with_no_matches_is_empty_not_crash`.

**Case sensitivity.** Both the stored search term and the compared
filename are lowercased before the `in` check, so `"SUNSET"`,
`"Sunset"`, and `"sunset"` all match a file named `sunset.jpg`
identically. Pinned by `test_filmstrip_search_is_case_insensitive`.

**Whitespace in the search term.** `"  sunset  "` normalizes to
`"sunset"` via `strip()` before the substring check, so leading/
trailing whitespace from an accidental space never causes a search
that should match to silently fail. Pinned by
`test_filmstrip_search_whitespace_is_stripped`.

**Composing with filter mode.** Favorites-only entries that don't
match the search term are excluded; search-matching entries that
aren't favorited are also excluded -- only the intersection survives.
Pinned by `test_filmstrip_search_composes_with_favorites_filter`
(three entries: a favorited+matching one, a favorited+non-matching
one, and a matching+non-favorited one -- only the first survives both
`set_filter("favorites")` and `set_search_text("sun")`).

**Composing with sort mode.** The search-filtered subset is still
sorted correctly by name when `"name"` sort is active -- the sort step
runs *after* the search filter in `_render_entries()`, over whatever
subset survived it. Pinned by
`test_filmstrip_search_composes_with_name_sort`.

**Order of operations does not change user-observable behavior.**
Filter mode, search, and sort are each independent (filtering by
membership twice is commutative; sorting afterward does not care which
filter removed which entries first), so the exact order chosen here
(filter mode -> search -> sort) produces the same final list as any
other order of the two filtering stages would, before the one sort
stage runs last.

## 6. Test plan

All new tests live in `tests/unit/test_views/test_workspace_widgets.py`,
immediately after the existing
`test_filmstrip_filters_favorites_and_sorts_by_name`, mirroring its
exact fixture (`_entry(path, *, status="available")`) and assertion
style:

- `test_filmstrip_search_filters_by_filename_substring` -- basic
  substring match narrows the visible list.
- `test_filmstrip_search_cleared_restores_all_entries` -- setting
  `""` after a non-empty search restores every entry (the empty-string
  regression-safety property called out above).
- `test_filmstrip_search_composes_with_favorites_filter` -- the single
  most important test in this slice: Favorites filter AND a search
  term both active, intersection only (see Nuances above for the exact
  three-entry setup).
- `test_filmstrip_search_composes_with_name_sort` -- Sort by Name AND
  a search term both active; the filtered subset remains correctly
  ordered.
- `test_filmstrip_search_with_no_matches_is_empty_not_crash` -- a
  search term matching nothing empties the list and label without
  raising.
- `test_filmstrip_search_is_case_insensitive` -- `"SUNSET"` and
  `"sunset"` both match `sunset.jpg`.
- `test_filmstrip_search_whitespace_is_stripped` -- `"  sunset  "`
  still matches `sunset.jpg`.

No behavioral test was added for the built-in clear button itself --
it is a stock Qt `QLineEdit` feature (`setClearButtonEnabled(True)`)
with no custom logic in this codebase to verify.

## 7. Rollout

Purely additive: one new instance attribute
(`self._search_text = ""`, matching pre-existing behavior for every
caller that never calls `set_search_text`), one new header widget, one
new public method, and a three-line extension inside
`_render_entries()` guarded by `if self._search_text:` (a no-op when
empty, which is the default and the state after every existing test
and every existing call site that doesn't use the new method). No
existing method's signature changed and no persisted-data format
changed. A plain revert removes the widget, the method, and the
`_render_entries()` branch with no catalog or settings migration
concerns, since nothing here is persisted.

## 8. Implementation summary

Added `self._search_text: str = ""` to `FilmstripView.__init__`
(`src/views/widgets/filmstrip_view.py`), a `QLineEdit` header widget
(`self._search_edit`, placeholder "Search photos...", fixed width
160px, built-in clear button enabled) inserted between the header's
existing stretch and `_filter_button`, a new
`set_search_text(self, text: str) -> None` method (normalize via
`strip().lower()`, no-op if unchanged, otherwise store and
`_render_entries()`), and a three-line filtering stage in
`_render_entries()` that keeps only filename-matching entries when
`self._search_text` is non-empty, running after the existing
filter-mode branch and before the existing sort-mode branch so all
three controls compose correctly. Added `QLineEdit` to the file's
`PyQt6.QtWidgets` import block.

Added 7 new tests to
`tests/unit/test_views/test_workspace_widgets.py`, immediately after
the existing Filter/Sort test, covering: basic substring filtering,
clearing restores all entries, composing with the Favorites filter
(the single most important test, verifying intersection rather than
one mechanism clobbering the other), composing with Sort by Name,
a no-match search producing an empty (not crashed, not
fallback-to-all) list, case-insensitivity, and whitespace
normalization.

Updated `docs/planning/PRODUCT_ROADMAP.md`'s Phase A bullet to mark
"**Search** box filtering library." **Done**, and updated the coverage
table's PDF Sec.8 row to describe the filmstrip-level filename search
that now exists, distinguishing it from the still-open, larger
dedicated top-level Search panel gap (PDF Sec.8's search box +
results/suggestions panel on the right).

**Deviation note.** None of substance. Two "your call" design
decisions made per the task brief's own invitation: (1) the search box
is placed between the header's stretch and the Filter button (grouped
visually with the other narrowing controls) rather than immediately
after the count label; (2) the built-in `QLineEdit` clear button was
used, confirmed as a real PyQt6 API before relying on it.

Verification: 7 new tests added; full suite run via
`QT_QPA_PLATFORM=offscreen python3 -m pytest -q --deselect tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::test_geometry_is_restored_on_next_launch`
**969 passed, 1 skipped, 1 deselected in 130.06s** (969 = the prior
slice's 962 passed + 7 new tests this slice added; the deselected test
is the same pre-existing offscreen-rendering flake noted in prior
implementation notes, unrelated to this slice; the 1 skipped test is
pre-existing and unrelated). No failures observed, including no
recurrence of the previously-noted
`TestLibraryPanel::test_clear_library` background-thumbnail-thread
teardown timing race.

This completes the Phase A "Search box filtering library." bullet.
