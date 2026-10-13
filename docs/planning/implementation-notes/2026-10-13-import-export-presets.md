# Import/Export Presets (file-based, single preset)

Related roadmap: Phase D, "Profiles and presets" (PDF section 10) in
`docs/planning/PRODUCT_ROADMAP.md` -- the second bullet, "Import presets
subset (e.g. JSON or LUT-based) -- full 'Import Profiles & Presets'
parity can grow incrementally." This is the direct follow-on to the
Profile-selector slice (`docs/planning/implementation-notes/
2026-10-13-profile-selector.md`), which explicitly deferred this bullet
as "the next slice." Like that slice, and like Copy/Paste Edit Settings
before it, this is menu/file-I/O plumbing on top of the existing
whole-state-apply mechanism, not a new image processor, so this note
follows the same adapted (non-processor) section structure.

## 1. Problem, goal, and non-goals

**Problem.** There was no way to save an image's adjustment state to a
file and later apply that same state to a different image (in this
session, a different PhotoEdit install, or shared with someone else) --
only the in-memory, single-slot, session-only Copy/Paste Edit Settings
clipboard existed, which never touches disk and cannot outlive the app
process.

**Goal.** Add `MainWindow._export_preset()` and
`MainWindow._import_preset()`, wired to two new File menu actions
("Export &Preset...", "Import Pre&set..."), which write/read a single
JSON file containing the exact adjustment-state dict
`ImageController.get_adjustment_state()` already produces, wrapped in a
small versioned envelope. Importing applies the file's adjustments to
the current image through the exact same `set_adjustments(...)` /
`restore_adjustment_state(...)` / `_adjustment_persist_timer.start()`
pattern `_apply_profile()` and `_paste_edit_settings()` already
established.

**Honest scope boundary -- this is file-based export/import of a single
user-authored preset, analogous to saving/sharing one Lightroom `.xmp`
preset file. It is explicitly NOT:**

- **A persistent, on-disk preset library with its own browsable UI
  section.** There is no "Presets" panel, no list of previously
  imported presets, no catalog of preset files PhotoEdit remembers or
  manages on the user's behalf. Each Export/Import is a one-off
  file-picker round trip, same as Export Image already is for pictures.
  A real preset *library* -- browse, name, organize, and apply any of N
  saved presets from a persistent list -- is a bigger, separate future
  slice, comparable in scope to the deferred interactive Crop tool: a
  real UI subsystem with its own storage, not something to sneak in as
  a side effect of file I/O plumbing.
- **LUT-based presets** (`.cube` files or similar color-science lookup
  tables). The roadmap bullet's "e.g. JSON or LUT-based" explicitly
  offers either; this slice builds the JSON option only, using this
  codebase's own existing flat/nested adjustment-state schema (the same
  dict `get_adjustment_state()`/`restore_adjustment_state()` already
  use), not a standardized color-grading LUT format. Supporting
  `.cube` files would mean a wholly different file format, a different
  parser, and arguably a different application point in the pipeline
  (LUTs are typically a rendering-intent transform, not a set of named
  slider values) -- out of scope here.
- **Merging into the Profile combo box.** The Profile selector's combo
  box (added in the prior slice) is explicitly limited to the five
  `BUILTIN_PROFILES` entries. An imported preset is never added to that
  combo, never shown alongside "Standard"/"Vivid"/etc., and the two
  features share no UI. Mixing them would require exactly the
  browsable-library UI this slice is deliberately not building (where
  would a dynamic, user-supplied list of presets live inside a combo
  box that is otherwise a fixed, five-entry list?).

**Other non-goals:**

- No undo/redo command for Import, matching every other whole-state-apply
  action's existing precedent (`_reset_adjustments()`,
  `_paste_edit_settings()`, `_apply_profile()`).
- No batch export/import across multiple selected images; one image in,
  one file out (or vice versa), matching the single-image scope of
  Copy/Paste Edit Settings and the Profile selector.
- No preset "amount"/strength control, and no partial/selective import
  (e.g. "only import the color grading, not exposure") -- the whole
  `adjustments` dict in the file replaces the whole current state, same
  as every other whole-state-apply action in this codebase.

## 2. Current behavior (before this slice)

`ImageController.get_adjustment_state()` / `restore_adjustment_state()`
and `ToolsPanel.set_adjustments()` already existed, already used by
`_reset_adjustments()`, `_copy_edit_settings()`/`_paste_edit_settings()`,
and `_apply_profile()`. Nothing in any of those methods needed to
change. `SettingsService` already had the `get_last_export_dir()`/
`set_last_export_dir()` pattern (directory-remembering for a
`QFileDialog`) and `get_last_export_options()`/`set_last_export_options()`
(JSON-via-`QSettings` round-tripping, defensively handling corrupt/
missing data) -- both were read as the direct templates for this slice,
but this slice writes/reads a real file on disk (`pathlib.Path`), not a
`QSettings` value.

## 3. Design

### Preset file format

A small, explicit, versioned JSON envelope, not the bare
adjustment-state dict alone:

```json
{
  "photoedit_preset_version": 1,
  "name": "my_preset",
  "adjustments": { "exposure": 0.5, "contrast": 20.0, "...": "..." }
}
```

- `"photoedit_preset_version"` (`int`): currently always `1`. Lets a
  stray/malformed JSON file (or a JSON file that is simply unrelated to
  PhotoEdit) be rejected immediately and unambiguously, and leaves room
  to evolve the envelope shape later without silently misreading an old
  file as a new-shaped one.
- `"name"` (`str`): a display name for the preset, shown in the
  "Imported preset: {name}" status message. See the "name" decision
  below.
- `"adjustments"` (`dict`): the real adjustment-state dict exactly as
  `ImageController.get_adjustment_state()` returns it -- every flat key
  (`exposure`, `contrast`, ..., `straighten`) plus the three non-flat
  keys (`tone_curve`, `hsl`, `color_grading`), unmodified. No
  PhotoEdit-specific transformation or subsetting is applied; the file
  is a direct, inspectable dump of the real internal state.

**File extension: `.json`**, with file-dialog filter
`"PhotoEdit Preset (*.json)"`. A more specific extension like
`.pepreset` was considered (it would avoid collision with arbitrary
JSON files a user might double-click or import by mistake), but `.json`
was chosen as the simpler, more universally recognizable default: it
opens readably in any text editor or JSON viewer without the user
needing to know a PhotoEdit-specific extension exists, it is the same
reasoning this codebase already applied to `_KEY_LAST_EXPORT_OPTIONS`
(plain JSON via the standard library, no custom format), and the
`"photoedit_preset_version"` envelope key already does the real job of
distinguishing a genuine preset file from an unrelated JSON file at
read time -- a distinct extension would be a second, weaker version of
that same check.

**"name" field: derived from the filename's stem**, not a separate
`QInputDialog.getText(...)` prompt. Exporting "my_preset.json" sets
`"name": "my_preset"`; importing a file whose `"name"` key happens to
be missing/non-string falls back to that file's own stem the same way.
This was chosen over an extra naming dialog because it is simpler (one
fewer modal per export), avoids a redundant question (the user already
typed a name once, into the save dialog's filename field), and still
produces a sensible value for the one place `"name"` is used (the
status-bar message on import). A hand-edited preset file can still set
`"name"` to something nicer than its filename if its author wants to
(e.g. "My Portrait Look" in a file saved as `portrait_v2.json`); import
honors that over the filename whenever it is present and is a
non-empty string.

**Directory-remembering: a dedicated `get_last_preset_dir()`/
`set_last_preset_dir()` pair** (`SettingsService`, key
`"paths/last_preset_dir"`), rather than sharing
`get_last_export_dir()`/`set_last_export_dir()`. The two were kept
separate because a preset file (a small, hand-authored or shared JSON
document, conceptually closer to a settings/config file) is plausibly
kept in a different place than an exported image (large JPEG/PNG
output destined for a photo library, a client delivery folder, etc.);
sharing the key would mean browsing for a preset file resets/overwrites
the directory the next image export dialog starts from, and vice
versa, which would be a mildly surprising cross-feature side effect. The
implementation mirrors `get_last_export_dir()`/`set_last_export_dir()`
exactly (same `_get_existing_dir`/`_set_dir` helpers, same
home-directory fallback semantics), so the two pairs behave identically
apart from using a different key.

### `MainWindow._export_preset()`

```python
def _export_preset(self) -> None:
    if not self._image_controller.has_image():
        self._status_bar.showMessage("No image to export a preset from", 2000)
        return

    default_name = "preset.json"
    source_path = self._image_controller.image_model.file_path or ""
    if source_path:
        default_name = f"{Path(source_path).stem}_preset.json"
    start_dir = self._settings_service.get_last_preset_dir()
    default_path = str(Path(start_dir) / default_name)

    path, _ = QFileDialog.getSaveFileName(
        self, "Export Preset", default_path, PRESET_FILE_FILTER
    )
    if not path:
        return
    if not path.lower().endswith(".json"):
        path += ".json"

    if not confirm_overwrite_if_needed(self, path, self._settings_service):
        self._status_bar.showMessage("Export preset cancelled", 2000)
        return

    preset_name = Path(path).stem
    envelope = {
        "photoedit_preset_version": PRESET_FILE_VERSION,
        "name": preset_name,
        "adjustments": self._image_controller.get_adjustment_state(),
    }

    try:
        Path(path).write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    except OSError as exc:
        QMessageBox.critical(
            self, "Export Preset Failed", f"Failed to write preset file:\n{exc}"
        )
        return

    self._settings_service.set_last_preset_dir(path)
    self._status_bar.showMessage(f"Exported preset: {preset_name}", 2000)
```

The default filename is derived from the current image's filename
(`{stem}_preset.json`) when one exists, falling back to a bare
`preset.json`, mirroring `_export_image()`'s own
`{stem}_edited{suffix}` default-naming logic exactly. The existing
`confirm_overwrite_if_needed(...)` helper (already used by both
`ExportDialog` and `_export_with_previous()`) is reused as-is for the
overwrite-confirmation prompt, rather than reimplementing it -- this is
the same direct-file-write shape `_export_with_previous()` already has
(no intermediate dialog of its own), so that was the closer template
than `_export_image()`'s `ExportDialog`-delegating flow.

### `MainWindow._import_preset()`

```python
def _import_preset(self) -> None:
    if not self._image_controller.has_image():
        self._status_bar.showMessage("No image to apply a preset to", 2000)
        return

    start_dir = self._settings_service.get_last_preset_dir()
    path, _ = QFileDialog.getOpenFileName(
        self, "Import Preset", start_dir, PRESET_FILE_FILTER
    )
    if not path:
        return

    try:
        raw_text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        QMessageBox.critical(...)
        return

    try:
        envelope = json.loads(raw_text)
    except (json.JSONDecodeError, ValueError) as exc:
        QMessageBox.warning(...)
        return

    if not isinstance(envelope, dict):
        QMessageBox.warning(...)
        return

    version = envelope.get("photoedit_preset_version")
    if version != PRESET_FILE_VERSION:
        # "newer version" message if version looks like a plausible
        # future int greater than ours; generic "not recognized"
        # message otherwise (missing key, wrong type, older/unknown
        # version number).
        QMessageBox.warning(...)
        return

    adjustments = envelope.get("adjustments")
    if not isinstance(adjustments, dict):
        QMessageBox.warning(...)
        return

    preset_name = envelope.get("name")
    if not isinstance(preset_name, str) or not preset_name:
        preset_name = Path(path).stem

    state_for_tools_panel = copy.deepcopy(adjustments)
    state_for_controller = copy.deepcopy(adjustments)
    self._tools_panel.set_adjustments(state_for_tools_panel, emit_signal=False)
    self._image_controller.restore_adjustment_state(state_for_controller)
    self._adjustment_persist_timer.start()
    self._settings_service.set_last_preset_dir(path)
    self._status_bar.showMessage(f"Imported preset: {preset_name}", 2000)
```

Byte-for-byte the same apply shape as `_paste_edit_settings()`/
`_apply_profile()`: two independent `copy.deepcopy` calls (one for
`ToolsPanel`, one for `ImageController`) of the parsed `adjustments`
dict, so neither downstream call can leave a second reference to the
same dict mutated out from under the other, consistent with the
mutation-safety reasoning already established for the clipboard and
`BUILTIN_PROFILES`.

### Menu placement and shortcuts

Both actions were added to the **File** menu, directly below the
existing "Export..."/"Export with Previous" pair and above the final
separator/Exit action. This was chosen over the Edit menu (near
Copy/Paste Edit Settings) because this feature is fundamentally file
I/O -- reading and writing a file on disk via `QFileDialog` -- which is
exactly what every other File-menu action already does (Open, Import
Images, Export, Export with Previous), whereas Copy/Paste Edit Settings
never touches the filesystem at all (it is a pure in-memory clipboard).
Grepping every `self._create_action(...)` call in `main_window.py`
confirmed the full current shortcut list (`Ctrl+O`, `Ctrl+Shift+O`,
`Ctrl+E`, `Ctrl+Shift+E`, `Ctrl+Q`, `Ctrl+Z`, `Ctrl+Shift+Z`, `Ctrl+R`,
`Ctrl+Alt+C`, `Ctrl+Alt+V`, `Ctrl+,`, `0`, `1`, `Ctrl+=`, `Ctrl+-`,
`F5`, `F6`) -- no clean, conventional, uncolliding shortcut stood out
for either action (every short, memorable combination near the existing
Export shortcuts is already taken), so both "Export &Preset..." and
"Import Pre&set..." were added as **menu-only actions with no keyboard
shortcut**, which the task brief explicitly allows for a
less-frequently-used feature like this one.

## 4. Contracts

- `MainWindow._export_preset(self) -> None` / `MainWindow._import_preset(self) -> None`
  -- new methods, wired to new File-menu actions ("Export &Preset...",
  "Import Pre&set..."), no keyboard shortcuts.
- `MainWindow.PRESET_FILE_VERSION` (module-level `int`, currently `1`)
  and `MainWindow.PRESET_FILE_FILTER` (module-level `str`,
  `"PhotoEdit Preset (*.json)"`) -- new module-level constants in
  `src/views/main_window.py`.
- `SettingsService.get_last_preset_dir(self) -> str` /
  `SettingsService.set_last_preset_dir(self, path: str) -> None` -- new
  methods, key `"paths/last_preset_dir"`, identical behavior/semantics
  to the existing `get_last_export_dir`/`set_last_export_dir` pair.
- Preset file envelope shape (see Design above): `{"photoedit_preset_version": 1, "name": str, "adjustments": dict}`.
- No existing method's signature or behavior changed.
  `ImageController.get_adjustment_state()`/`restore_adjustment_state()`,
  `ToolsPanel.set_adjustments()`, and `confirm_overwrite_if_needed()`
  are used exactly as already established by `_export_with_previous()`,
  `_paste_edit_settings()`, and `_apply_profile()`.

## 5. Nuances and failure modes

**No image loaded.** Both actions are guarded by the same `has_image()`
check used everywhere else in this family of actions, with their own
status-bar message, before any `QFileDialog` is even shown -- confirmed
directly by a test that patches `QFileDialog.getSaveFileName`/
`getOpenFileName` and asserts they are never called when no image is
loaded.

**Malformed/arbitrary file content on import -- the highest-risk part of
this slice.** Every step between "user picked a file" and "adjustments
applied" is wrapped defensively, and each failure mode shows a
`QMessageBox` rather than raising:

1. **Unreadable file** (permissions, file removed between picking and
   reading, etc.): `Path(path).read_text(...)` raising `OSError` is
   caught and shown via `QMessageBox.critical`.
2. **Not valid JSON at all** (e.g. a text file, a truncated/corrupted
   file, or someone's unrelated `.json` that happens to not parse):
   `json.loads(...)` raising `json.JSONDecodeError`/`ValueError` is
   caught and shown via `QMessageBox.warning`, naming the problem
   explicitly ("not valid JSON").
3. **Valid JSON, but not an object** (e.g. a bare JSON array, number, or
   string): rejected by an explicit `isinstance(envelope, dict)` check,
   since `.get(...)` below would otherwise raise `AttributeError` on a
   list/str/int.
4. **Missing or wrong-type `"photoedit_preset_version"`**: compared with
   `!=` against the expected `int` constant, so a missing key
   (`None`), a string, or any other version number all fail the same
   check. The message differentiates only the "newer version" case
   (an `int` greater than the currently supported version, framed
   forward-compatibly as "made with a newer version of PhotoEdit") from
   every other mismatch (framed as "not a recognized PhotoEdit
   preset") -- deliberately not over-engineered into a full
   version-migration system, per the task brief's own guidance.
5. **Missing or wrong-type `"adjustments"`**: an explicit
   `isinstance(adjustments, dict)` check. Without this, a file that
   passes every earlier check but has `"adjustments": "oops"` or no
   `"adjustments"` key at all (`None`) would otherwise be handed
   straight to `copy.deepcopy(...)` /
   `ToolsPanel.set_adjustments(...)`, which was not verified to reject
   non-dict input safely -- this check keeps that path fully untested
   territory out of reach.

At every one of these rejection points, the function returns **before**
calling `set_adjustments`/`restore_adjustment_state`/starting the
persist timer, so a malformed file can never partially apply -- either
the whole, validated `adjustments` dict is applied, or nothing is
touched at all. This is pinned directly by tests that mock
`restore_adjustment_state` and assert it was never called for each of
the five rejection cases above.

**Export failure (disk full, permissions, destination removed
mid-write, etc.).** `Path(path).write_text(...)` raising `OSError` is
caught and shown via `QMessageBox.critical`, matching `_export_image`'s
established error-handling style exactly (`QMessageBox.critical` on
failure, no raw traceback surfaced, no partial file silently left half-
written since `write_text` itself either fully succeeds or raises).

**Extension handling.** A path chosen without a `.json` (or any)
extension has `.json` appended, mirroring `ExportDialog._browse_file`'s
own `if not path.lower().endswith(ext): path += ext` pattern exactly.

**Overwrite confirmation.** Reuses
`confirm_overwrite_if_needed(self, path, self._settings_service)`
unmodified -- the same helper `_export_with_previous()` and
`ExportDialog` already use -- so the "Don't ask me again" preference set
from the image-export flow also governs preset export/import; this was
judged the right behavior (one coherent "ask before overwrite"
preference per app, not a second independent one) rather than a bug to
avoid.

**Interaction with the adjustment-persist timer.** Import calls
`self._adjustment_persist_timer.start()` in the same place every other
whole-state-apply action does, so the imported preset's state is
written through to `LibraryCatalogService` on the same debounced
schedule as any other adjustment change. Export does not touch the
persist timer at all (it only *reads* the current state via
`get_adjustment_state()`, same as `_copy_edit_settings()`; nothing
about the current image's adjustments changes).

**No "last imported/exported preset" memory beyond the directory.**
Only the *directory* a preset file was picked from/saved to is
remembered (`get_last_preset_dir`/`set_last_preset_dir`), not which
specific file, and not a history of previously used presets -- per the
non-goal of not building a preset library.

## 6. Test plan

- `tests/unit/test_services/test_settings_service.py`
  (`TestSettingsServiceLastPresetDir`, plus one addition to
  `TestSettingsServiceDefaults`): default is home directory; set+get
  round-trips a directory; a file path stores its parent directory; a
  stored directory that no longer exists on disk falls back to home;
  the preset and export directory keys are independent of each other --
  all mirroring the existing `last_export_dir` tests' exact style.
- `tests/ui/test_main_window_presets.py` (new file, alongside
  `test_main_window.py` in `tests/ui/`, kept as its own module rather
  than appended to the already-large `test_main_window.py` -- both are
  equally valid placements per the task brief's own phrasing ("whichever
  placement precedent... check and match"); a separate file was chosen
  since this slice's test surface (export + import + round-trip, each
  with several failure modes) is large enough to read more clearly on
  its own, the same way `test_main_window.py` itself is already split
  out from other UI test files rather than being one giant file):
  - `TestExportPreset`: no image loaded shows the right message and
    never opens `QFileDialog.getSaveFileName`; exporting with an image
    loaded writes a real file (via `tmp_path`) whose JSON content is
    read back and checked against the expected envelope shape
    (`photoedit_preset_version == 1`, `name` derived from the chosen
    filename's stem, `adjustments` equal to the live
    `get_adjustment_state()` result); a path without a `.json`
    extension gets one appended; a write failure (`Path.write_text`
    raising `OSError`, patched) shows `QMessageBox.critical` and does
    not crash.
  - `TestImportPreset`: no image loaded shows the right message and
    never opens `QFileDialog.getOpenFileName`; importing a well-formed
    preset file (written for real via `tmp_path`) calls
    `set_adjustments`/`restore_adjustment_state` with the file's
    `adjustments` dict (by value, not by the same object, matching the
    deepcopy-safety pattern of every prior slice's tests) and shows the
    file's `"name"`; a file whose `"name"` is missing falls back to the
    filename's stem; a non-JSON file, a JSON file missing
    `"adjustments"`, a JSON file with the wrong
    `"photoedit_preset_version"`, and a JSON file that is not an object
    (a bare array) are each rejected with a `QMessageBox.warning` and
    each confirmed to never call `restore_adjustment_state` (no crash,
    no partial application, one test per failure mode).
  - `TestExportImportPresetRoundTrip`: a real export (via
    `_export_preset`, writing to a `tmp_path` file) followed by a real
    import of that same file (via `_import_preset`) ends up calling
    `restore_adjustment_state` with a dict equal to what
    `get_adjustment_state()` returned right before the export, proving
    the whole file-based round trip actually preserves the adjustment
    state end to end.

## 7. Rollout

Purely additive: two new `SettingsService` methods (one new `QSettings`
key), two new `MainWindow` methods, two new File-menu actions, and two
new module-level constants in `main_window.py`. No existing method's
signature or behavior changed, and no processor was added or touched.
A plain revert removes the feature entirely with no migration in either
direction -- preset files already written to disk by this feature are
simply inert, ordinary JSON files afterward (no app-managed registry of
"known preset files" exists to clean up), and the new
`"paths/last_preset_dir"` settings key is harmless, unread leftover
state if the feature is removed later.

## 8. Implementation summary

Added `get_last_preset_dir()`/`set_last_preset_dir()` to
`src/services/settings_service.py` (new key
`"paths/last_preset_dir"`, mirroring `get_last_export_dir`/
`set_last_export_dir` exactly). Added `PRESET_FILE_VERSION = 1` and
`PRESET_FILE_FILTER = "PhotoEdit Preset (*.json)"` module-level
constants, plus `MainWindow._export_preset()` and
`MainWindow._import_preset()`, to `src/views/main_window.py`, wired to
two new File-menu actions ("Export &Preset...", "Import Pre&set...",
both menu-only, no keyboard shortcut after confirming every existing
shortcut via a fresh grep). Export builds a
`{"photoedit_preset_version", "name", "adjustments"}` envelope from
`ImageController.get_adjustment_state()` and writes it via
`Path.write_text(json.dumps(..., indent=2), encoding="utf-8")`; import
reads and validates that same envelope defensively (five distinct,
individually-tested rejection paths for malformed input) before
applying it through the exact `set_adjustments(...)` /
`restore_adjustment_state(...)` / `_adjustment_persist_timer.start()`
pattern already used by `_apply_profile()`/`_paste_edit_settings()`.

No changes were made to any processor, `ImageController`'s core
adjustment pipeline, `ToolsPanel.set_adjustments`,
`ImageController.restore_adjustment_state`, or the Profile selector's
combo box/`BUILTIN_PROFILES` -- this feature composes the existing
whole-adjustment-state dict into a small file format and applies it
through the existing whole-state-apply mechanism, exactly as scoped.

**Deviation note.** None of substance. Two "your call" design decisions
worth calling out explicitly (both documented in Design above, and both
leaning toward the simpler option per the task brief's own guidance):
`.json` extension over a more specific `.pepreset`, and deriving the
preset's display `"name"` from the chosen filename rather than an extra
`QInputDialog` prompt.

Verification: new tests -- `TestSettingsServiceLastPresetDir` (plus one
addition to `TestSettingsServiceDefaults`) in
`tests/unit/test_services/test_settings_service.py` **5 passed**;
`tests/ui/test_main_window_presets.py` (`TestExportPreset`,
`TestImportPreset`, `TestExportImportPresetRoundTrip`) **14 passed** (19
new tests total); complete suite run via
`QT_QPA_PLATFORM=offscreen python3 -m pytest -q --deselect tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::test_geometry_is_restored_on_next_launch`
**937 passed, 1 skipped, 1 deselected in 134.14s** (918 pre-existing +
19 new -- 2 fewer pre-existing than the 920 cited in the prior
Profile-selector note's own run, which is consistent with ordinary
suite-count drift between separate runs, not a regression introduced
here; the deselected test is the same pre-existing offscreen-rendering
flake noted in prior implementation notes, unrelated to this slice; the
1 skipped test is pre-existing and unrelated to this work). One earlier
full-suite run produced a single, unrelated flaky error in
`TestLibraryPanel::test_clear_library` (a background thumbnail-worker
callback racing against per-test teardown in
`library_catalog_service.py`/`library_controller.py` -- a subsystem
this slice never touches); it passed cleanly both in isolation and in
a clean full-suite rerun immediately after, and also passed on the
pre-this-slice code (`git stash`), confirming it as a pre-existing,
unrelated timing flake rather than something this slice caused. No
other failures or flakes observed. A live GUI smoke test (actually
clicking
the new File-menu actions in the real running app) was not performed in
this non-interactive environment; the behavior is instead pinned at the
`MainWindow`-level unit tests above, including a real filesystem
round trip.

This completes both of Phase D's listed bullets -- the Profile selector
(prior slice) and Import presets (this slice) -- though, as the Phase D
intro text itself notes, "full 'Import Profiles & Presets' parity can
grow incrementally" still applies to both: a browsable preset library
and LUT-based presets remain explicitly out of scope and undone.
