# Export with Previous (remember last export options)

Related roadmap: Phase B, "Edit/File workflow and preferences MVP" in
`docs/planning/PRODUCT_ROADMAP.md` ("Export with Previous (remember last
export options; ties to app-level persistence above)."). Like the
Export overwrite confirmation and Single-instance slices, this is
dialog/settings plumbing, not an image processor slice, so this note
follows that adapted section structure rather than the processor
template.

## 1. Problem, goal, and non-goals

**Problem.** Every export in PhotoEdit requires opening `ExportDialog`
and re-choosing format, quality, resize, and preserve-aspect options,
even when the user just wants to repeat their last export (e.g. after
making a small adjustment tweak and wanting the same JPEG-at-90% they
used a minute ago). Lightroom's real File > Export with Previous solves
this by re-running the last-used export settings immediately, with no
dialog.

**Goal.** Persist the options used by the most recently *successful*
export (format, quality, width/height, preserve-aspect) via
`SettingsService`, and add a File menu action,
`_export_with_previous`, that re-runs them directly against the
current image without opening `ExportDialog`.

**Non-goals:**

- No "export preset" naming/management system with multiple saved
  presets. This only remembers the single most-recent export's
  settings, matching Lightroom's actual "Export with Previous"
  semantics, not its separate "Export presets" feature (which lets you
  name and manage several saved configurations).
- No change to `ExportDialog`'s own UI layout, its format/resize
  option lists, or `ExportService`'s resize/export logic itself.
- No batch-export support, matching the scope boundary already set by
  the Export overwrite confirmation slice.

## 2. Current behavior (before this slice)

`ExportDialog` already took an `Optional[SettingsService]` and used it
for the last-export directory and the overwrite-confirmation
preference, but nothing persisted the *options* chosen in the dialog
(format/quality/resize/preserve-aspect) -- each dialog open started
from the same fixed defaults (JPEG, quality 95, current image
dimensions, preserve-aspect checked).

`MainWindow._export_image()` always constructed and showed
`ExportDialog`; there was no way to export without going through it.

The overwrite-confirmation check (`_confirm_overwrite_if_needed`) was
a private `ExportDialog` instance method, which meant any other caller
wanting the same behavior (this slice's new `MainWindow` method) would
either have to duplicate it or go through the dialog.

## 3. Design and flow

### Options dict shape

Both `ExportDialog` and `MainWindow._export_with_previous` agree on
this exact shape, persisted as a single JSON blob:

```python
{
    "format": str,            # e.g. "JPEG", matching ExportDialog's format combo's stored name
    "quality": int,           # 1-100
    "width": Optional[int],   # None means "export at original size" (no resize)
    "height": Optional[int],  # None means "export at original size" (no resize)
    "preserve_aspect": bool,
}
```

`width`/`height` are `None`/`None` precisely when `_do_export()`'s
existing resize computation produced no resize (i.e. the spin values
equal the source image's actual dimensions) -- the persisted shape
mirrors that logic exactly rather than introducing a second notion of
"no resize."

### `SettingsService`

New key `export/last_options` (continuing the `"export/..."`
namespace introduced by the overwrite-confirmation slice), with:

- `get_last_export_options() -> Optional[dict]` -- reads the stored
  string via `self._settings.value(key)`, returns `None` if it is not
  a non-empty string, otherwise `json.loads(...)`s it inside a
  `try/except` that returns `None` on any decode failure (so a
  missing, empty, or corrupted stored value is always treated as "no
  previous export," never as a crash).
- `set_last_export_options(options: dict) -> None` -- `json.dumps(...)`
  and store. JSON (rather than `QSettings`'s own dict/QVariant
  round-tripping) was chosen for the same reason the overwrite
  confirmation slice explicitly guarded its bool round-trip: that
  round-tripping is backend-specific and unpredictable across
  platforms.

### `ExportDialog`

- On successful export (`_do_export()`, right after `export_image(...)`
  returns `True`), builds the options dict from the dialog's current
  widget state -- reusing the *same* `resize` variable `_do_export`
  already computes (so `width`/`height` are `None`/`None` exactly when
  `resize` is `None`) -- and calls `set_last_export_options(options)`
  if `self._settings_service is not None`. This runs before the
  success `QMessageBox` and `self.accept()`, but after the export
  itself succeeds, so a failed export never persists stale/attempted
  options.
- On construction, a new `_apply_last_export_options()` method (called
  right after `_setup_ui()` in `__init__`) reads
  `get_last_export_options()` and, if non-`None`, pre-populates:
  format combo (by matching stored `format` against each item's
  `currentData()['name']`), quality slider, width/height spins (only
  when *both* are non-`None` -- otherwise the existing default, current
  image dimensions, is left alone), and the preserve-aspect checkbox.

  **Signal-triggering question, resolved by inspection rather than
  assumption:** `_apply_last_export_options()` runs after `_setup_ui()`
  has already wired `self._format_combo.currentIndexChanged.connect(
  self._on_format_changed)`. Calling `self._format_combo.setCurrentIndex(i)`
  at that point is standard Qt/PyQt6 behavior -- it emits
  `currentIndexChanged` itself whenever the index actually changes, so
  `_on_format_changed` (which shows/hides the quality slider for JPEG)
  fires automatically; no explicit extra call was added. This was
  confirmed by the new `test_prepopulates_widgets_when_options_exist`
  test, which sets a non-JPEG stored format (`PNG`) and asserts the
  resulting widget state is fully consistent, which would not hold if
  the visibility side effect had silently failed to run.

- The overwrite-confirmation logic
  (previously `ExportDialog._confirm_overwrite_if_needed`, a private
  instance method) was extracted into a standalone module-level
  function, `confirm_overwrite_if_needed(parent, path, settings_service)`,
  in `export_dialog.py`, with `parent` now an explicit argument (for
  the `QMessageBox(parent)` call) instead of relying on `self`.
  `ExportDialog._do_export()` was updated to call
  `confirm_overwrite_if_needed(self, path, self._settings_service)`
  in place of its old private method. This means there is exactly one
  implementation of the logic, reused by `MainWindow` below, rather
  than two copies that could drift.

### `MainWindow._export_with_previous()`

Mirrors `_export_image()`'s has-image check and default-path
computation exactly (duplicated rather than refactored, to minimize
risk to the existing, already-tested `_export_image` flow):

1. `has_image()`/`get_export_image()` checks, same status-bar messages
   on failure as `_export_image`.
2. Computes `default_path` the same way: from the current file's path
   (`<stem>_edited<suffix>` next to it) when one exists, else falling
   back to `get_last_export_dir()`.
3. Calls `self._settings_service.get_last_export_options()`. If
   `None` -- no export has ever completed -- there is nothing to
   repeat, so this **falls back to the normal `_export_image()` flow**
   (which opens the dialog), after a status-bar message
   ("No previous export settings; opening Export dialog..."). This is
   the intended UX for "repeat the last export" when there is no
   "last" yet, not an error path.
4. Otherwise calls the shared `confirm_overwrite_if_needed(self,
   default_path, self._settings_service)`. If it returns `False`,
   aborts with a "Export cancelled" status-bar message and does not
   export.
5. On confirmation (or when none was needed), constructs a fresh
   `ExportService()` (confirmed stateless/cheap -- see section 4) and
   calls `export_image(image, default_path, format=..., quality=...,
   resize=(width, height) if both set else None, preserve_aspect=...)`
   using the persisted options.
6. On success: `set_last_export_dir(default_path)` and a status-bar
   "Exported to: ..." message, matching `_export_image`'s existing
   behavior. On failure: `QMessageBox.critical(self, "Export Failed",
   "Failed to export image.")`, matching `ExportDialog`'s own failure
   message text exactly.

### Menu wiring

Added to `_setup_menu_bar()`, right after the existing `"&Export..."`
action:

```python
file_menu.addAction(
    self._create_action(
        "Export with &Previous", self._export_with_previous, "Ctrl+Shift+E"
    )
)
```

`Ctrl+Shift+E` was checked against every other shortcut registered in
`_setup_menu_bar` (`Ctrl+O`, `Ctrl+Shift+O`, `Ctrl+E`, `Ctrl+Q`,
`Ctrl+Z`, `Ctrl+Shift+Z`, `Ctrl+R`, `0`, `1`, `Ctrl+=`, `Ctrl+-`, `F5`,
`F6`) via `grep`; no collision found, so it was used as-is.

## 4. Contracts

- `SettingsService.get_last_export_options() -> Optional[dict]`
- `SettingsService.set_last_export_options(options: dict) -> None`
- `src.views.export_dialog.confirm_overwrite_if_needed(parent, path: str, settings_service: Optional[SettingsService]) -> bool`
  -- new module-level public function, replacing the old private
  `ExportDialog._confirm_overwrite_if_needed` method (which no longer
  exists).
- `MainWindow._export_with_previous(self) -> None` -- new method,
  wired to the new "Export with &Previous" (`Ctrl+Shift+E`) File menu
  action.

**`ExportService()` statelessness, confirmed by reading the source
rather than assumed.** `ExportService.__init__` takes an optional
`image_service: Optional[ImageService] = None` and, when omitted,
constructs a plain `ImageService()`, whose own `__init__` just
constructs a default `RawService()` if none is given -- no file I/O,
no caching, no heavyweight state in either constructor. Constructing a
fresh `ExportService()` in `MainWindow`, separate from the instance
`ExportDialog` builds for itself, is exactly as cheap as `ExportDialog`
already assumes (it does the same thing in its own `__init__`).

## 5. Nuances and failure modes

**Corrupt-JSON recovery.** `get_last_export_options()` wraps
`json.loads(...)` in a `try/except (json.JSONDecodeError, TypeError,
ValueError)` and returns `None` on any failure, logged at `warning`.
This was exercised directly by writing a non-JSON garbage string
straight into the underlying `QSettings` (bypassing
`set_last_export_options` entirely) and confirming
`get_last_export_options()` returns `None` rather than raising
(`test_corrupt_stored_value_returns_none`), and similarly for an empty
stored string (`test_empty_stored_value_returns_none`).

**Shared `confirm_overwrite_if_needed`.** Extracting this into a
module-level function (rather than duplicating the overwrite-check
logic inside `MainWindow._export_with_previous`) means the exact same
confirmation semantics -- skip when no settings service, when the path
doesn't exist, or when the preference is off; default to "No";
persist "don't ask again" when checked -- apply identically whether
the export was initiated through the dialog or through "Export with
Previous." The existing overwrite-confirmation tests in
`test_export_dialog.py` needed no behavioral changes, since the
function body itself is unchanged -- only its location (module-level,
explicit `parent` argument) moved. A new
`TestExportDialogConfirmOverwriteIsNeededStandalone` class pins that
the extracted function, called directly (not through `ExportDialog`),
still returns `True` in each "skip confirmation" case.

**Export failure never persists options.** `_do_export()` only calls
`set_last_export_options(...)` inside the `if success:` branch, so a
failed export (format/IO error) never overwrites a previously-good set
of remembered options with options for an export that didn't actually
happen. Pinned by `test_does_not_persist_on_failed_export`.

**No-previous-options fallback is intentional UX, not a bug.**
`_export_with_previous()` with `get_last_export_options() is None`
calls `self._export_image()` (opening the dialog) rather than failing
silently or doing nothing -- there is genuinely nothing to "repeat"
yet, and opening the dialog is the only sensible action, matching how
Lightroom's own Export with Previous behaves identically on a profile
that has never exported before.

## 6. Test plan

`tests/unit/test_services/test_settings_service.py` (new
`TestSettingsServiceLastExportOptions` class, added alongside the
existing `isolated_settings`/`service` fixtures, no new fixtures
needed): default is `None`; round-trips a full options dict; round-
trips `width`/`height` as `None`/`None`; a directly-written corrupt
string returns `None`; a directly-written empty string returns `None`.

`tests/unit/test_views/test_export_dialog.py` (building on the
existing `qapp`/`isolated_settings`/`settings_service`/`sample_image`
fixtures and the `_make_dialog` helper): new
`TestExportDialogConfirmOverwriteIsNeededStandalone` confirms the
extracted function's skip-conditions behave identically when called
directly; new `TestExportDialogPersistsLastExportOptions` confirms a
successful `_do_export()` persists the exact dict shape, both without
and with a resize, and that a failed export persists nothing; new
`TestExportDialogPrePopulatesFromLastExportOptions` confirms
construction with stored options pre-populates every widget correctly
(including a non-JPEG format, to exercise the
`_on_format_changed`-via-signal path), construction with no stored
options leaves the existing defaults untouched, and construction with
`settings_service=None` also leaves defaults untouched.

`tests/unit/test_views/test_main_window_export_with_previous.py` (new
file; `test_main_window.py`'s own export-related coverage lives only
in `tests/ui/test_main_window.py` as general UI smoke tests with no
pre-existing export-specific test class to extend, so a new focused
unit-test file was added instead, following the same real-`MainWindow`
+ `qtbot` construction pattern as the UI test file's `main_window`
fixture, but with `image_controller.has_image`/`get_export_image`
patched directly for determinism rather than loading a real image):
no previous options falls back to `_export_image` being called (and a
missing image does *not* fall back, it just shows a status message);
with previous options, `ExportDialog` is never constructed and
`ExportService.export_image` is called once with the stored options
correctly translated into `resize=(width, height)`; overwrite
confirmation returning `False` prevents any export call; success
updates the status bar and calls `set_last_export_dir`; failure shows
`QMessageBox.critical`.

## 7. Rollout

Purely additive: a new `QSettings` key (`export/last_options`,
`None`-when-absent), a new `SettingsService` method pair, a new
module-level function in `export_dialog.py` (replacing a private
method with no external callers, so this is not a breaking rename for
any other code), a new `MainWindow` method, and a new menu action. No
existing method signature's observable behavior changed except
`ExportDialog._do_export()`'s internal call target for the
overwrite-confirmation check (same behavior, different call site). A
plain revert removes the feature entirely; older builds that never
write `export/last_options` simply always take the
no-previous-options fallback path, which is a safe, non-crashing
default either way. No migration is needed in either direction.

## 8. Implementation summary

Added `get_last_export_options`/`set_last_export_options` to
`SettingsService` (`src/services/settings_service.py`), backed by a
new JSON-serialized `export/last_options` key, with `json.loads`
failures caught and treated as "no previous options" rather than
raised.

Extracted `ExportDialog`'s private `_confirm_overwrite_if_needed`
into a standalone module-level `confirm_overwrite_if_needed(parent,
path, settings_service)` function in `src/views/export_dialog.py`
(unchanged logic, explicit `parent` argument), and updated
`_do_export()` to call it. Added persistence of the exact options dict
on successful export (reusing `_do_export`'s existing `resize`
computation), and a new `_apply_last_export_options()` method, called
from `__init__` right after `_setup_ui()`, that pre-populates the
dialog's widgets from any previously-stored options -- confirming by
direct test that `QComboBox.setCurrentIndex`'s own
`currentIndexChanged` emission (not an explicit extra call) drives the
quality-slider-visibility side effect in `_on_format_changed`.

Added `MainWindow._export_with_previous()` (`src/views/main_window.py`),
mirroring `_export_image()`'s has-image check and default-path
computation, falling back to `_export_image()` when no previous
options exist, reusing the shared `confirm_overwrite_if_needed`
function, and exporting via a freshly-constructed `ExportService()`
(confirmed stateless/cheap to construct, matching `ExportDialog`'s own
pattern). Wired to a new "Export with &Previous" File menu action with
shortcut `Ctrl+Shift+E` (checked against every other shortcut in
`_setup_menu_bar`; no collision found).

No changes were made to any processor, `ToolsPanel`, the
`ImageController` adjustment pipeline, or anything from the
Texture/Clarity/.../Straighten slices -- this feature is entirely
contained in `settings_service.py`, `export_dialog.py`, and
`main_window.py`, as scoped.

**Deviation note.** None of substance. One implementation choice made
where the spec left it open: the pre-population call
(`_apply_last_export_options()`) was placed as a separate method
called right after `_setup_ui()` in `__init__`, rather than inlined
into `_setup_ui()` itself, to keep `_setup_ui()` focused purely on
widget construction/layout and keep the "read persisted state into
widgets" concern in one clearly-named, independently testable method.

Verification: targeted new/changed tests (`test_settings_service.py` +
`test_export_dialog.py` + new `test_main_window_export_with_previous.py`)
**51 passed**; complete suite run via
`QT_QPA_PLATFORM=offscreen python3 -m pytest -q --deselect tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::test_geometry_is_restored_on_next_launch`
**872 passed, 1 skipped, 1 deselected in 119.96s** (851 pre-existing +
21 new; the deselected test is the same pre-existing
offscreen-rendering flake noted in prior implementation notes,
unrelated to this slice; the 1 skipped test is pre-existing and
unrelated to this work). No other failures or flakes observed. A live
GUI smoke test (actually clicking "Export with Previous" in the real
running app) was not performed in this non-interactive environment;
the behavior is instead pinned at the `MainWindow`/`ExportDialog`/
`SettingsService` unit level.
