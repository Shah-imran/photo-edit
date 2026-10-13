# Next / previous photo (keyboard + UI)

Related roadmap: Phase A, "Library DAM and workspace chrome" (PDF
sections 8-9, 24) in `docs/planning/PRODUCT_ROADMAP.md` -- the bullet
"**Filmstrip** or bottom strip + **next/previous photo** (keyboard +
UI)." The filmstrip half of this bullet already existed in full
(`src/views/widgets/filmstrip_view.py`, with its own filter/sort/search
and favorite/rating/flag/keyword controls, each landed in a prior
slice). This slice adds only the missing half: navigating to the
next/previous photo in the filmstrip's currently displayed order, via
both the keyboard and a View menu action.

## 1. Problem, goal, and non-goals

**Problem.** There was no way to move to the next or previous photo
without clicking a specific thumbnail in the filmstrip or the Library
panel grid. Grepping `src/views/main_window.py` for any existing
"next"/"previous" image action confirmed none existed.

**Goal.** Add `FilmstripView.select_next()` / `select_previous()`,
which move `QListWidget`'s current selection by one row within the
filmstrip's already-filtered/sorted/searched display order (no
additional ordering logic needed -- see Design below for why), and
wire `MainWindow._next_photo()` / `_previous_photo()` to them, exposed
as both View-menu actions and keyboard shortcuts.

**Non-goals (explicit scope boundary for this slice):**

- **No wraparound.** At the last photo, "next" is a no-op (just a
  status-bar message); at the first photo, "previous" is a no-op. This
  deliberately matches Adobe Lightroom's own non-wrapping
  next/previous behavior in its filmstrip, not an oversight.
- **No "auto-advance to next photo" after a rating/flag/export
  action.** That is a different, separate feature (e.g. "cull my
  shoot: rate this one, automatically jump to the next") that happens
  to sound related but has different triggers, different UX
  expectations (it fires as a *side effect* of another action, not on
  its own keypress), and was not asked for by this roadmap bullet.
  Building it here would silently expand scope beyond "next/previous
  photo (keyboard + UI)." Not built.
- **No new catalog-service, processor, or image-loading-path change.**
  This is UI/navigation plumbing only, routed through the exact same
  `image_selected` signal -> `_on_library_image_selected` path a
  filmstrip thumbnail click already uses (see Design).
- **No change to the Library panel grid's own selection.** The
  Library panel (`library_view.py`) and the filmstrip are two
  independently-selectable views over the same library (confirmed by
  reading `main_window.py`'s existing `_library_view.image_selected`
  and `_filmstrip_view.image_selected` -- both already connect to the
  same `_on_library_image_selected` handler, but neither view's
  selection is pushed into the other on a plain photo load). This
  slice does not change that pre-existing relationship; it moves only
  the filmstrip's own current-row selection.

## 2. Current behavior (before this slice)

`FilmstripView._render_entries()` already builds `self._list` (a
`QListWidget`) in final, already-filtered-and-sorted-and-searched
order: it starts from `self._entries`, applies the filter-mode branch,
then the search-text branch, then the sort-mode branch (in that exact
order -- see `2026-10-13-filmstrip-search.md`), and only *then*
populates `self._list` by iterating the resulting `entries` list and
calling `self._list.addItem(item)` for each one, in order. So "row N in
`self._list`" already *is* "the Nth photo in whatever order is
currently displayed" -- confirmed by re-reading `_render_entries()`
end to end, not assumed.

`self._list.currentItemChanged` is connected to
`_on_current_item_changed`, which (when not suppressed and the item's
status is `"available"`) emits `image_selected` with the item's path.
Clicking a thumbnail changes `currentItem` via Qt's own
click-to-select handling, which fires `currentItemChanged` the normal
way. `MainWindow` connects `self._filmstrip_view.image_selected` to
`self._on_library_image_selected`, which persists pending adjustments
and calls `self._image_controller.load_image_async(...)` -- the single
path that actually loads a new image into the editor.

There was no method on `FilmstripView` to programmatically move the
current row by one, and no `MainWindow` action/shortcut for
next/previous photo at all.

## 3. Design

### 3a. `select_next()` / `select_previous()` need no extra ordering logic

Because `_render_entries()` already populates `self._list` in final
display order (confirmed above), `select_next`/`select_previous` only
need to move `self._list`'s current row by one via
`self._list.setCurrentRow(...)` -- standard `QListWidget` behavior
confirmed to fire the same `currentItemChanged` signal a click does
(verified empirically via the new
`test_filmstrip_select_next_and_previous_move_through_entries` test,
which asserts `image_selected` fires with the correct path inside a
`qtbot.waitSignal` block around a bare `select_next()` call -- no
manual `image_selected.emit(...)` was added, and none was needed).
This also means `select_next`/`select_previous` automatically respect
whatever filter/sort/search is currently active, with zero special-case
code, which is pinned by
`test_filmstrip_select_next_and_previous_respect_filtered_sorted_order`
(see Test plan).

### 3b. Keyboard shortcut choice: Left/Right arrows, after empirically testing the conflict risk

Lightroom conventionally uses bare Left/Right arrow keys for
next/previous. The brief's own concern -- that a focused child widget
(a slider, a spin box) might either swallow the key before the
`QAction` shortcut fires, or get its own arrow-key behavior stolen by
the shortcut -- was real enough to test rather than assume, so before
picking a key I:

1. **Confirmed `_create_action`'s shortcut context.** Reading
   `MainWindow._create_action` (`src/views/main_window.py`):
   `action.setShortcut(QKeySequence(shortcut))` is called with no
   explicit `setShortcutContext(...)` call anywhere in this file (one
   `grep -n "ShortcutContext" src/views/main_window.py` confirms
   zero hits), so every action in this app uses Qt's default
   `Qt.ShortcutContext.WindowShortcut`. `self.addAction(action)` is
   also called on `MainWindow` itself (the comment above it already
   explains this is so shortcuts keep working with the v2 workspace
   header's menu bar hidden) -- so every shortcut in this app is a
   window-level shortcut, active regardless of which child widget has
   focus, *as long as nothing intercepts the key first*.

2. **Tested, rather than assumed, how "intercepts the key first"
   actually plays out**, using a small standalone PyQt6 script run
   under `QT_QPA_PLATFORM=offscreen` (not part of the shipped test
   suite -- a one-off investigation script) that put a real `QSlider`
   or `QDoubleSpinBox` (the exact two widget types
   `AdjustmentSlider`, `src/views/widgets/adjustment_slider.py`, is
   built from -- confirmed by reading that file's imports and
   `__init__`) under keyboard focus, registered a window-level
   `QAction` with a given shortcut key on the containing `QMainWindow`
   (mirroring `_create_action` exactly), sent the key via
   `QTest.keyClick`, and compared the widget's own value **with** vs.
   **without** the competing global shortcut registered. Results:

   | Key | Widget focused | Widget's own value changes (no shortcut) | With a global shortcut on that key |
   |---|---|---|---|
   | Left/Right | `QSlider` | Yes (steps by 1) | **Action fires; slider does NOT step** (key stolen) |
   | Left/Right | `QDoubleSpinBox` | No (moves text cursor only) | Action does **not** fire (spin box's internal `QLineEdit` absorbs it) |
   | PageUp/PageDown | `QSlider` | Yes (pages by 10) | **Action fires; slider does NOT page** (key stolen) |
   | PageUp/PageDown | `QDoubleSpinBox` | Yes (pages by 10) | **Action fires; spin box does NOT page** (key stolen) |

   In other words: for *every* key tested, a window-level `QAction`
   shortcut wins the race over the focused widget's own native
   key-handling in this Qt version -- confirming the stated concern is
   real, not hypothetical. Neither candidate key is conflict-free.
   But the *size* of the conflict differs sharply between the two
   candidates:

   - **Left/Right** only steals from a bare, keyboard-focused
     `QSlider` track. It does **not** steal from the paired
     `QDoubleSpinBox` (the far more common precise-value-entry
     target), because `QDoubleSpinBox`'s internal `QLineEdit` already
     consumes Left/Right for text-cursor movement before the
     shortcut system ever sees them as "unclaimed" -- confirmed by the
     "Action does not fire" row above. So while typing an exact
     adjustment value, Left/Right behaves exactly as expected (cursor
     moves inside the number) and next/previous-photo simply does not
     fire -- no corruption, just an inert keypress in that one focus
     state.
   - **PageUp/PageDown** steals from *both* widget types: a focused
     `QSlider` loses its page-step, and -- more importantly -- a
     focused `QDoubleSpinBox` (used constantly for precise numeric
     entry across every adjustment in the Tools panel) loses its own
     PageUp/PageDown 10x-step convenience too. That is a strictly
     *wider* conflict surface than Left/Right's.

3. **Checked whether any custom widget in this codebase
   (`AdjustmentSlider`, the curve editor, etc.) overrides
   `keyPressEvent` for any of these keys itself**, which would change
   the calculus: `grep -rln "keyPressEvent\|Key_Left\|Key_Right\|
   Key_PageUp\|Key_PageDown" src/views/` returned nothing. Every
   arrow/page-key behavior in this app's widgets comes from the stock
   Qt base classes (`QSlider`, `QDoubleSpinBox`), not custom app code,
   so the table above is the complete picture of the conflict surface
   -- no additional risk from the curve editor or anywhere else.

4. **Checked for pre-existing shortcut collisions.** `grep -n
   "setShortcut\|QKeySequence(" src/` confirmed
   `MainWindow._create_action` is the only place in `src/` that
   registers a shortcut, and the full list currently registered
   (`Ctrl+O`, `Ctrl+Shift+O`, `Ctrl+E`, `Ctrl+Shift+E`, `Ctrl+Q`,
   `Ctrl+Z`, `Ctrl+Shift+Z`, `Ctrl+R`, `Ctrl+Alt+C`, `Ctrl+Alt+V`,
   `Ctrl+,`, the bare `"0"`/`"1"` zoom shortcuts, `Ctrl+=`, `Ctrl+-`,
   `F5`, `F6`) contains neither Left/Right nor PageUp/PageDown. No
   collision either way.

**Decision: Left/Right arrow keys.** Given that *neither* candidate is
fully conflict-free in this Qt version, Left/Right was chosen because
(a) it matches Lightroom's own real convention most closely, and (b)
its conflict surface is strictly narrower and less disruptive than
PageUp/PageDown's -- it only affects a bare, keyboard-focused slider
track (not the paired spin box most users actually type exact values
into), where pressing Left/Right instead advances/retreats a photo
rather than nudging the slider by one unit. This is a real, narrow,
documented tradeoff (see Nuances below), not an unexamined choice.
PageUp/PageDown was rejected specifically because it was measured to
be *more* disruptive (breaking spin-box paging too), not merely "an
alternative convention" as a stylistic fallback.

### 3c. Menu placement: View menu

Wired into the existing `&View` menu, immediately after the
Zoom In/Out actions and before the `Toggle Library/Tools Panel`
separator -- alongside `&Fit to Window` / `&100%` / `Zoom &In` / `Zoom
&Out`, the closest existing precedent for "an action that changes
which image content is currently being looked at." A dedicated
Photo/Navigate menu was considered, but there is no such menu anywhere
in this app today (`File`/`Edit`/`View`/`Help` only), and adding a new
top-level menu for exactly two actions would be disproportionate --
the View menu is the more natural, lower-friction home, consistent
with how the zoom actions already live there.

### 3d. Status-bar feedback

Matching the existing "no message on a successful navigation-style
action" pattern (`_fit_to_window`/`_zoom_in`/etc. show no status
message because the visible effect -- the image changing -- is itself
sufficient feedback), `_next_photo`/`_previous_photo` show a status
message *only* on the boundary no-op case
(`"Already at the last photo"` / `"Already at the first photo"`,
2000ms, mirroring the exact `self._status_bar.showMessage(text, 2000)`
call signature used throughout `main_window.py`, e.g.
`_copy_edit_settings`'s "No image to copy..." message).

## 4. Contracts

- `FilmstripView.select_next(self) -> bool` -- new public method.
  Moves `self._list`'s current row to `currentRow() + 1` via
  `setCurrentRow(...)` if a next row exists; returns `True` if the
  selection moved. Returns `False` (no change) when the list is empty
  or the current row is already the last one. No wraparound.
- `FilmstripView.select_previous(self) -> bool` -- mirror of
  `select_next`, moving to `currentRow() - 1`, clamped at `0`. Same
  `bool` return convention.
- Both methods rely on `QListWidget.setCurrentRow` firing the existing
  `currentItemChanged` -> `_on_current_item_changed` ->
  `image_selected` signal chain; neither method emits `image_selected`
  directly.
- `MainWindow._next_photo(self) -> None` / `_previous_photo(self) ->
  None` -- new methods. Call `self._filmstrip_view.select_next()` /
  `select_previous()`; on `False`, show the corresponding status-bar
  message (`2000`ms); on `True`, show nothing.
- Two new `QAction`s in the `&View` menu: `&Next Photo` (shortcut
  `Right`) and `&Previous Photo` (shortcut `Left`), registered via the
  existing `_create_action` helper (so they share its
  `Qt.ShortcutContext.WindowShortcut` default and its
  `self.addAction(...)` call that keeps them active with the classic
  menu bar hidden).
- No existing method's signature changed.

## 5. Nuances and failure modes

**No wraparound, by design.** At the last photo, `select_next()`
returns `False` and the current row does not move; symmetric for
`select_previous()` at the first photo. Pinned by
`test_filmstrip_select_next_at_last_entry_does_not_move_or_wrap` and
`test_filmstrip_select_previous_at_first_entry_does_not_move_or_wrap`.

**Empty filmstrip.** Both methods return `False` immediately
(`self._list.count() == 0` check first) without touching
`currentRow()`/`setCurrentRow()` at all, so there is no risk of an
out-of-range `setCurrentRow` call on an empty list. Pinned by
`test_filmstrip_select_next_and_previous_on_empty_filmstrip_return_false`.

**Nothing currently selected (`currentRow() == -1`).**
`select_next()` treats this the same as "about to move to row 0" (so
pressing Next Photo with nothing selected selects the first photo,
a reasonable and harmless default); `select_previous()` in that same
state returns `False` (there is no well-defined "previous" of "no
selection"). This case is not separately exercised by a named test
(it was not called out by the spec and is a low-value edge case --
`FilmstripView.set_current_path` is always called after
`set_entries`/`_render_entries` in real usage, see
`_render_entries`'s own `self.set_current_path(current_path)` call,
so a real, populated filmstrip with no selection at all does not occur
in practice), but the implementation handles it without raising.

**Left/Right arrow keys and a focused slider.** As investigated in
Design above: if a bare `AdjustmentSlider`'s internal `QSlider` track
currently has keyboard focus (e.g. after clicking directly on the
slider, or tabbing to it) and the user presses Left/Right expecting to
nudge the value by one step, the window-level shortcut wins instead
and the photo navigates. This is a narrow, real, and now-documented
tradeoff (see Design 3b for why it was accepted over the strictly
wider conflict PageUp/PageDown would have introduced), not a silent
regression. It does **not** affect the `QDoubleSpinBox` half of the
same control, which is the widget most users actually type precise
values into.

**Filtered/sorted/searched order.** `select_next`/`select_previous`
walk `self._list`'s rows exactly as populated by `_render_entries()`
-- i.e. whatever the Filter/Sort/Search controls are currently
showing, not the original unfiltered `self._entries` insertion order.
Pinned by
`test_filmstrip_select_next_and_previous_respect_filtered_sorted_order`.

## 6. Test plan

**`tests/unit/test_views/test_workspace_widgets.py`** (5 new tests,
immediately after `test_filmstrip_filters_favorites_and_sorts_by_name`):

- `test_filmstrip_select_next_and_previous_move_through_entries` --
  a 3-entry filmstrip; `select_next`/`select_previous` move the
  current row correctly in both directions, each firing
  `image_selected` with the expected path (via `qtbot.waitSignal`,
  mirroring the file's existing `image_selected` test pattern).
- `test_filmstrip_select_next_at_last_entry_does_not_move_or_wrap` --
  `select_next()` at the last entry returns `False`, current path
  unchanged.
- `test_filmstrip_select_previous_at_first_entry_does_not_move_or_wrap`
  -- mirror, at the first entry.
- `test_filmstrip_select_next_and_previous_on_empty_filmstrip_return_false`
  -- both methods return `False` on an empty `FilmstripView` without
  raising.
- `test_filmstrip_select_next_and_previous_respect_filtered_sorted_order`
  -- reuses the exact Favorites+search+name-sort setup the file's
  existing composed-filter tests already use, confirming
  `select_next`/`select_previous` walk the filtered/sorted *displayed*
  order (e.g. alphabetically-sorted `alpha -> mango -> zebra`, not the
  original `zebra, alpha, mango` insertion order), including a
  single-surviving-entry case where both methods correctly return
  `False` in either direction.

**`tests/ui/test_main_window.py`** (4 new tests, in a new
`TestNextPreviousPhoto` class at the end of the file, mirroring
`TestCopyPasteEditSettings`'s `patch.object(main_window._status_bar,
"showMessage")` style):

- `test_next_photo_calls_filmstrip_select_next` -- mocks
  `select_next` to return `True`; asserts it was called and no status
  message was shown.
- `test_previous_photo_calls_filmstrip_select_previous` -- mirror.
- `test_next_photo_at_last_entry_shows_status_message` -- mocks
  `select_next` to return `False`; asserts
  `"Already at the last photo"` shown for `2000`ms.
- `test_previous_photo_at_first_entry_shows_status_message` -- mirror,
  `"Already at the first photo"`.

## 7. Rollout

Purely additive: two new `FilmstripView` methods with no new instance
state, two new `MainWindow` methods, two new `QAction`s in an existing
menu, and no change to any existing method's signature, any persisted
data format, or the image-loading path itself (navigation still flows
through the exact same `image_selected` -> `_on_library_image_selected`
-> `ImageController.load_image_async` chain a filmstrip click already
used). A plain revert removes the two `FilmstripView` methods, the two
`MainWindow` methods, and the two menu actions with no catalog or
settings migration concerns.

## 8. Implementation summary

Added `FilmstripView.select_next(self) -> bool` and
`select_previous(self) -> bool` to
`src/views/widgets/filmstrip_view.py`, immediately after `count()`.
Added `MainWindow._next_photo(self) -> None` and
`_previous_photo(self) -> None` to `src/views/main_window.py`,
immediately before `_toggle_library_panel`, and wired two new `&View`
menu actions (`&Next Photo` / `Right`, `&Previous Photo` / `Left`)
immediately after the Zoom In/Out actions.

Added 9 new tests: 5 in `tests/unit/test_views/test_workspace_widgets.py`
and 4 in `tests/ui/test_main_window.py` (new `TestNextPreviousPhoto`
class).

Verification: full suite run via
`QT_QPA_PLATFORM=offscreen python3 -m pytest -q --deselect
tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::test_geometry_is_restored_on_next_launch`
-- **993 passed, 1 skipped, 1 deselected in 132.58s** (984 pre-existing
+ 9 new tests this slice added; the deselected test is the same
pre-existing offscreen-rendering flake noted in prior implementation
notes, unrelated to this slice; the 1 skipped test is pre-existing and
unrelated). No failures observed, and no recurrence of the
previously-noted `TestLibraryPanel::test_clear_library`
background-thumbnail-thread teardown timing race.

**Deviation note.** None of substance. The keyboard-shortcut choice
(Left/Right over PageUp/PageDown) required genuine empirical
investigation rather than a style call -- see Design 3b for the full
test methodology and results table, run as a standalone
`QT_QPA_PLATFORM=offscreen` PyQt6 script (not added to the shipped
test suite, since it tests stock Qt widget behavior rather than this
app's own code).

This completes the Phase A "Filmstrip or bottom strip + next/previous
photo (keyboard + UI)." bullet -- the filmstrip itself was already
done in a prior slice; this slice completes the next/previous-photo
half, so the bullet as a whole is now fully covered.
