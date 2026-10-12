# Export overwrite confirmation (and related prefs)

Related roadmap: Part 1, "Professional shell (non-PDF; plan alongside B
and K)" in `docs/planning/PRODUCT_ROADMAP.md`. This is dialog/UX
plumbing, not an image processor slice, so this note's section
structure is adapted accordingly rather than following the processor
template file-for-file.

## 1. Problem, goal, and non-goals

**Problem.** `ExportDialog._do_export()` reads the path typed or
browsed into `self._path_edit` and calls
`self._export_service.export_image(...)` directly, with no check for
whether that path already exists on disk, and no confirmation before
silently overwriting it. The native file picker's own "replace this
file?" prompt only fires when the user *picks* an existing file through
`QFileDialog.getSaveFileName`; it does not fire if the user types a
path to an existing file directly into the `QLineEdit`, or edits a
browsed path afterward. That gap is real and easy to hit.

**Goal.** Before exporting to a path that already exists, ask the user
to confirm, defaulting to the safe ("No"/cancel) choice, with an opt-out
("Don't ask me again") that persists across sessions via
`SettingsService`.

**Non-goals:**

- No change to the Browse/native-file-picker flow itself. Its own
  built-in overwrite prompt (when the user picks an existing file
  through the picker) is untouched; this slice only closes the gap for
  typed/edited paths.
- No batch-export support. `ExportDialog` exports a single image today;
  multi-file batch export (and whatever overwrite semantics that would
  need, e.g. "apply to all") is out of scope.
- No "always overwrite" global CLI flag or command-line/headless export
  mode. The only way to suppress the prompt is the per-user "Don't ask
  me again" checkbox, which is a GUI preference, not a flag.

## 2. Current behavior

`ExportDialog.__init__` takes an `Optional[SettingsService]` and stores
it unchanged as `self._settings_service`; it is already used
defensively elsewhere in the class (`_browse_file` checks
`is not None` before reading/writing the last-export directory), so
`settings_service` can genuinely be `None` in practice (e.g. a caller
that does not wire one up), and the new confirmation logic has to
handle that the same way.

`_do_export()` validates the path is non-empty, then unconditionally
calls `export_image(...)` and shows a success/failure `QMessageBox`,
with no existence check anywhere in between.

`SettingsService` is a thin typed wrapper over `QSettings`, with paired
`get_*`/`set_*` methods per preference and namespaced keys (e.g.
`paths/last_export_dir`, `window/geometry`). There was no existing
boolean-valued preference to mirror for the `QSettings` round-tripping
convention; the geometry/state/current-image-path getters all handle
non-`str`/absent values defensively, which this slice follows.

## 3. Design and flow

Added `_confirm_overwrite_if_needed(self, path: str) -> bool` to
`ExportDialog`, called from `_do_export()` immediately before the
`export_image(...)` call (after options are gathered, so the same
options are used regardless of whether the path is a fresh or a repeat
export):

- Returns `True` immediately (skip confirmation, proceed as before) if
  `self._settings_service is None`, or `Path(path)` does not exist, or
  `get_confirm_export_overwrite()` is `False`.
- Otherwise builds a `QMessageBox(self)` with `Icon.Question`, a
  "Don't ask me again" `QCheckBox` attached via `setCheckBox`, Yes/No
  standard buttons, and **`setDefaultButton(QMessageBox.StandardButton.No)`**
  -- defaulting to "No" is the deliberate, safer choice for a
  destructive, hard-to-undo action (hitting Enter/Return reflexively
  should not overwrite a file).
- If the result is not `Yes` (explicit "No", or the dialog is closed/
  escaped, which Qt also reports as not-Yes here), `_do_export()`
  returns immediately: `export_image` is never called, neither
  `accept()` nor `reject()` is called, and the `ExportDialog` stays
  open exactly as the user left it, so they can edit the path and try
  again.
- If the result is `Yes` and the checkbox is checked,
  `set_confirm_export_overwrite(False)` is persisted before the export
  proceeds, so future exports (in this and later sessions) skip the
  prompt until the user re-enables it elsewhere (there is currently no
  UI surface to re-enable it short of clearing settings; adding one is
  out of scope for this slice, matching the roadmap item's narrow
  framing).
- On `Yes` either way, the existing export flow runs completely
  unchanged: `export_image(...)`, then the existing success/failure
  `QMessageBox`, then `self.accept()` on success.

## 4. Contracts

New `SettingsService` methods, following the exact
`get_last_export_dir`/`set_last_export_dir` pairing style and the
existing `"<namespace>/<key>"` naming convention:

- `get_confirm_export_overwrite(self) -> bool` -- reads key
  `export/confirm_overwrite` via
  `self._settings.value(key, True, type=bool)`. **Default is `True`**
  (confirmation is shown) when the preference has never been set.
- `set_confirm_export_overwrite(self, confirm: bool) -> None` --
  persists `bool(confirm)` to the same key.

`ExportDialog._confirm_overwrite_if_needed` is a private helper, not a
public contract; the only externally-visible behavior change is that
`_do_export()` may now return early without exporting or closing the
dialog.

## 5. Nuances and failure modes

**`QSettings` boolean round-tripping.** On some platforms `QSettings`
persists booleans as the literal strings `"true"`/`"false"`, and
reading them back with a bare `.value(key, default)` (no `type=` hint)
hands back that string -- which is always truthy in Python, so a
stored `False` would silently behave as `True`. `get_confirm_export_overwrite`
passes `type=bool` explicitly to `QSettings.value(...)` specifically to
avoid this, and the result is additionally wrapped in `bool(...)` so
the method's return value is always a real Python `bool`, never a
`QVariant`-ish passthrough. This was exercised directly:
`test_set_false_round_trips_as_actual_bool` asserts
`service.get_confirm_export_overwrite() is False` (identity check, not
just falsy) after a `set_confirm_export_overwrite(False)` round-trip
through a real file-backed `QSettings` (the `isolated_settings`
fixture), not a mock -- so this is a genuine, not merely assumed, fix
for the quirk.

**`settings_service=None`.** Confirmed by reading `ExportDialog.__init__`
directly: `settings_service: Optional[SettingsService] = None` is a
real, reachable state (already handled defensively in `_browse_file`),
not a type-hint-only possibility. `_confirm_overwrite_if_needed` checks
`is None` first, before touching `Path(path)` or any settings call, so
a dialog built without a `SettingsService` behaves exactly as it did
before this slice: no prompt, direct export.
`test_skipped_when_settings_service_is_none` pins this.

**Abandoning the dialog on "No".** Explicitly not calling `accept()` or
`reject()` on "No" means the dialog's modal event loop is unaffected --
the user is simply back at the `ExportDialog` with their path, format,
and resize settings exactly as they were, free to edit the path and hit
Export again. This was verified by mocking `accept`/`reject` directly
on the dialog instance and asserting neither was called
(`test_no_aborts_export_and_leaves_dialog_open`).

**Checkbox construction.** `QMessageBox.setCheckBox` takes ownership of
a `QCheckBox` instance that must be constructed by the caller (it is
not auto-created); the checkbox is read via `.isChecked()` only after
`exec()` returns, matching how Qt expects this API to be used (the
checked-state is available once the modal loop has closed, which also
matches "Don't ask me again" always being the user's committed choice
when they picked an answer, not a transient state read mid-interaction).

## 6. Test plan

`tests/unit/test_services/test_settings_service.py` (new
`TestSettingsServiceConfirmExportOverwrite` class, added to the
existing file rather than creating a parallel one): default is `True`
when unset; `set_confirm_export_overwrite(False)` round-trips to the
actual Python `False` singleton (`is False`, not just falsy); setting
back to `True` round-trips to `True`. Uses the file's existing
`isolated_settings`/`service` fixtures (a real temp-file-backed
`QSettings`, per that file's established pattern -- no mocking of
`QSettings` itself).

`tests/unit/test_views/test_export_dialog.py` (new file; the first
test coverage for `export_dialog.py`): built with the same `qapp`
module-scoped fixture pattern used in `test_tools_panel.py`/
`test_image_controller.py`, and `patch('src.views.export_dialog.QMessageBox')`
mirroring `test_image_controller.py`'s existing
`patch('src.controllers.image_controller.QMessageBox')` pattern exactly.
Covers: confirmation skipped when the path does not exist; skipped when
the setting is `False` even though the path exists; skipped when
`settings_service` is `None` even though the path exists; shown (an
instantiated, `exec()`-called `QMessageBox`) when the path exists and
the setting is `True` (the default); "No" aborts the export (mocked
`export_image` never called) without calling `accept()` or `reject()`;
"Yes" proceeds with the same `export_image` call as the unconfirmed
path; "Don't ask me again" checked on "Yes" calls
`set_confirm_export_overwrite(False)`; unchecked does not call it.
`QMessageBox` and `QCheckBox` are both mocked at the module level
(`src.views.export_dialog.QMessageBox`/`QCheckBox`) so no real blocking
dialog is ever shown, consistent with how this codebase already mocks
`QMessageBox` for destructive-action confirmations.

## 7. Rollout

Purely additive: a new defaulted `QSettings` key
(`export/confirm_overwrite`, default `True`) and a new private
`ExportDialog` method. No existing key, method signature, or call site
is removed or changed shape. A plain revert removes the feature
entirely; older builds that never write the new key simply keep
defaulting to "always confirm," which is the safe default either way.
No migration is needed in either direction.

## 8. Implementation summary

Added `get_confirm_export_overwrite`/`set_confirm_export_overwrite` to
`SettingsService` (`src/services/settings_service.py`), backed by a new
`export/confirm_overwrite` key following the existing
`"<namespace>/<key>"` naming convention, defaulting to `True` and using
`QSettings.value(key, True, type=bool)` plus an explicit `bool(...)`
wrap to avoid the `QSettings` string/bool round-tripping quirk (pinned
by an identity (`is False`) test against a real file-backed
`QSettings`, not a mock).

Added `ExportDialog._confirm_overwrite_if_needed` (`src/views/export_dialog.py`),
called from `_do_export()` right before the existing `export_image(...)`
call. It skips the prompt (returns `True`) whenever
`settings_service is None`, the path does not exist
(`pathlib.Path(path).exists()`), or the preference is `False`;
otherwise it shows a `QMessageBox` with Yes/No buttons, a "Don't ask me
again" `QCheckBox`, and `setDefaultButton(QMessageBox.StandardButton.No)`
as the deliberate safe default. "No" (or any non-Yes result, including
a closed dialog) aborts the export without calling `export_image`,
`accept()`, or `reject()`, leaving the dialog open. "Yes" persists
`set_confirm_export_overwrite(False)` first if the checkbox was
checked, then proceeds with the unmodified existing export flow.

No changes were made to `ImageController`, `ProcessingQueue`,
`ProcessingWorker`, `CombinedAdjustmentCommand`, or `ToolsPanel` --
this feature is entirely contained in `export_dialog.py` and
`settings_service.py`, as scoped.

**`settings_service=None` handling.** Confirmed by reading
`ExportDialog.__init__`'s signature directly
(`settings_service: Optional[SettingsService] = None`) that this is a
real, reachable path (already defensively checked elsewhere in the
class, in `_browse_file`), not merely a type-hint possibility. The new
confirmation helper checks for `None` first and skips the prompt
entirely in that case, matching the existing defensive style.
`test_skipped_when_settings_service_is_none` pins this.

**Deviation note.** None of substance. The spec's exact `QMessageBox`
construction (`Icon.Question`, `setCheckBox`, Yes/No standard buttons,
`setDefaultButton(No)`) was followed as given. Tests mock both
`QMessageBox` and `QCheckBox` at the `src.views.export_dialog` module
level (rather than only `QMessageBox`) because the checkbox instance's
`isChecked()` return value needs to be controlled per test case to
exercise the "Don't ask me again" branch deterministically.

Verification: targeted new/changed tests (`test_settings_service.py` +
new `test_export_dialog.py`) **30 passed**; complete suite run via
`QT_QPA_PLATFORM=offscreen python3 -m pytest -q --deselect tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::test_geometry_is_restored_on_next_launch`
**843 passed, 1 deselected in 114.34s** (that deselected test is the
same pre-existing offscreen-rendering flake noted in prior
implementation notes, unrelated to this slice). No other failures or
flakes observed. A live GUI smoke test (opening the real dialog and
clicking through Yes/No/checkbox interactively) was not performed in
this non-interactive environment.
