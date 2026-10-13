# Preferences UI (honestly-scoped slice)

Related roadmap: Phase B, "Edit/File workflow and preferences MVP" in
`docs/planning/PRODUCT_ROADMAP.md`: "**Preferences UI:** Local Storage
path, General, Import defaults, Interface (e.g. theme from
resources/QSS), Performance (preview size / threading) -- **no**
cloud/account unless product changes." Like Copy/Paste Edit Settings
and Export with Previous, this is menu/dialog/controller plumbing, not
an image-processor slice, so this note follows that adapted section
structure rather than the processor template.

This slice is marked **Partial**, not Done, on the roadmap: of the five
sub-areas the bullet lists, only two (General, Performance) are
actually covered. The other three are documented as durable,
deliberate gaps below -- not silent omissions.

## 1. Problem, goal, and non-goals

**Problem.** PhotoEdit had no central Preferences dialog. The one
user-facing preference that already existed
(`SettingsService.get_confirm_export_overwrite` /
`set_confirm_export_overwrite`, added in a prior slice -- see
`docs/planning/implementation-notes/2026-10-12-export-overwrite-confirmation.md`)
was only reachable indirectly, via the Export dialog's own "Don't ask
me again" checkbox at the moment of an overwrite prompt. There was also
no way for a user to adjust `ProxyManager`'s preview-quality tradeoff
(it is already fully configurable via constructor parameters, just
never wired to anything above `ProcessingWorker`'s hardcoded default
construction).

**Goal.** Add a `PreferencesDialog` (`src/views/preferences_dialog.py`)
with:

- A **General** section exposing the existing confirm-overwrite
  preference as a second, more discoverable entry point (same
  underlying `SettingsService` key as the Export dialog's checkbox --
  not a new, parallel setting).
- A **Performance** section exposing two new preferences -- quality
  preview max dimension and interactive/drag preview max dimension --
  mapped onto `ProxyManager`'s already-configurable constructor
  parameters (`max_size`, `interactive_max_size`), via two new
  `ProcessingWorker` constructor parameters and `ImageController`
  reading them from `SettingsService` at construction time.

Wired into `MainWindow` via a new "&Preferences..." (`Ctrl+,`) Edit-menu
action.

**Non-goals (documented gaps, not silent omissions):**

- **Local Storage path relocation.** The library catalog and thumbnail
  cache (`LibraryCatalogService`, `LibraryThumbnailCacheService`) read
  their on-disk location once, at construction, from fixed paths. Adding
  a user-facing "change where my library lives" preference would require
  migrating existing catalog JSON and cached thumbnail files to the new
  location (or handling a stale-vs-new-path merge/cleanup), which is a
  real, separate, higher-risk undertaking involving data loss risk if
  done carelessly. Not attempted in this slice. A future slice should
  design the migration (copy-then-verify-then-delete-old, or an explicit
  "Move Library..." wizard) before exposing any path field in
  Preferences.
- **Interface theme switching.** `src/views/theme.py` defines exactly
  one `APP_STYLESHEET` constant and one `apply_theme()` function that
  always applies it -- there is no second theme, no theme registry, and
  no stored "current theme" concept anywhere in the codebase today.
  Building a theme *switcher* UI control with nothing to switch to would
  be UI for a feature that does not exist. A future slice needs to
  author a second QSS theme (e.g. a light variant) and a
  `theme_name` preference before a switcher means anything.
- **Import defaults** (e.g. "copy into library vs. reference files in
  place"). `LibraryController.import_images(file_paths)` was read in
  full: it unconditionally calls
  `self._catalog_service.add_entries(self._current_library_id,
  file_paths)`, which stores each image's existing on-disk path as a
  reference -- there is no copy-into-library code path anywhere in
  `LibraryCatalogService` or `LibraryController` to make configurable.
  There is no existing, safe toggle point to expose; inventing a new
  copy-on-import pipeline (with its own file-management, naming-
  collision, and duplicate-detection concerns) is out of scope for a
  Preferences-UI slice and is not attempted here. The dialog simply
  does not have an Import section; this is called out as a code comment
  in `PreferencesDialog._setup_ui()`.
- **Threading.** `ProcessingWorker`'s/`ImageController`'s threading model
  (one dedicated `QThread` per worker, `use_threading` constructor flag)
  is wired once at construction and assumed fixed for the controller's
  lifetime throughout `image_controller.py` (e.g. `_setup_async_processing`
  is only ever called once, from `__init__`). There is no safe way to
  expose a user-facing thread-count or concurrency setting without a
  larger reconfiguration-at-runtime change to that model, which is out of
  scope here per the task's explicit instruction.

## 2. Current behavior (before this slice)

- `SettingsService.get_confirm_export_overwrite()` /
  `set_confirm_export_overwrite()` already existed and were only read/
  written from `src/views/export_dialog.py`
  (`confirm_overwrite_if_needed()`, and the dialog's own "Don't ask me
  again" checkbox inside the overwrite-confirmation `QMessageBox`).
- `ProxyManager.__init__(self, max_size=DEFAULT_PROXY_SIZE,
  interactive_max_size=DEFAULT_INTERACTIVE_PROXY_SIZE)` was already a
  fully general constructor (`DEFAULT_PROXY_SIZE = 1400`,
  `DEFAULT_INTERACTIVE_PROXY_SIZE = 600`), but
  `ProcessingWorker.__init__` always constructed it with
  `ProxyManager()` -- no args, so always exactly the defaults -- and
  `ImageController._setup_async_processing()` always constructed both of
  its `ProcessingWorker()` instances with no args either. Nothing
  upstream of `ProxyManager` itself exposed these two sizes as
  configurable.
- `ImageController.__init__` already accepted an optional
  `settings_service: Optional[SettingsService] = None`, and
  `MainWindow.__init__` already passed its own shared
  `self._settings_service` into it
  (`ImageController(self._image_view, settings_service=self._settings_service)`),
  making this the natural, lowest-risk place to read the two new
  preferences from.

## 3. Design

### `SettingsService` additions

Two new typed getter/setter pairs, following the exact `_KEY_*` +
`QSettings.value(key, default, type=...)` pattern already used for
`get_confirm_export_overwrite`:

```python
_KEY_PROXY_MAX_SIZE = "performance/proxy_max_size"
_KEY_INTERACTIVE_PROXY_MAX_SIZE = "performance/interactive_proxy_max_size"
```

`get_proxy_max_size()` / `get_interactive_proxy_max_size()` return
`Optional[int]`: `None` when the preference has never been explicitly
set, not a hardcoded `1400`/`600` -- the default lives on
`ProxyManager.DEFAULT_PROXY_SIZE` /
`ProxyManager.DEFAULT_INTERACTIVE_PROXY_SIZE` so there is exactly one
source of truth for it. One subtlety found while implementing this:
`QSettings.value(key, None, type=int)` does **not** return `None` when
the key is absent -- PyQt6 coerces the *default* argument through
`type=int` too, turning `None` into `0`. The getters therefore check
`self._settings.contains(key)` first and only read+coerce the stored
value when it actually exists:

```python
def get_proxy_max_size(self) -> Optional[int]:
    if not self._settings.contains(_KEY_PROXY_MAX_SIZE):
        return None
    return int(self._settings.value(_KEY_PROXY_MAX_SIZE, 0, type=int))
```

(Same pattern for `get_interactive_proxy_max_size`.) This was caught by
the new `test_default_is_none` unit tests, which initially failed with
`0 is None`.

### `ProcessingWorker` wiring

`ProcessingWorker.__init__` gains two new, optional, keyword-only-by-
convention parameters:

```python
def __init__(
    self,
    parent: Optional[QObject] = None,
    proxy_max_size: Optional[int] = None,
    interactive_proxy_max_size: Optional[int] = None,
):
    ...
    self._proxy_manager = ProxyManager(
        max_size=proxy_max_size or ProxyManager.DEFAULT_PROXY_SIZE,
        interactive_max_size=(
            interactive_proxy_max_size
            or ProxyManager.DEFAULT_INTERACTIVE_PROXY_SIZE
        ),
    )
```

Both default to `None`, which falls back to `ProxyManager`'s own class
constants rather than a second, duplicated `1400`/`600` literal here --
exactly the single-source-of-truth requirement from the task. `or` is
used rather than an explicit `is None` check because `0` is never a
sane proxy size (a size of `0` would be a bug, not a legitimate
preference), so the shorter null-coalescing form is safe here.

### `ImageController` wiring

`ImageController._setup_async_processing()` (called once, from
`__init__`, only when `use_threading=True`) now reads both preferences
from `self._settings_service` when it is not `None`, and passes them
into **both** `ProcessingWorker` constructions (the live-preview
`self._processing_worker` and the full-resolution
`self._final_processing_worker`):

```python
proxy_max_size = None
interactive_proxy_max_size = None
if self._settings_service is not None:
    proxy_max_size = self._settings_service.get_proxy_max_size()
    interactive_proxy_max_size = (
        self._settings_service.get_interactive_proxy_max_size()
    )

self._processing_worker = ProcessingWorker(
    proxy_max_size=proxy_max_size,
    interactive_proxy_max_size=interactive_proxy_max_size,
)
...
self._final_processing_worker = ProcessingWorker(
    proxy_max_size=proxy_max_size,
    interactive_proxy_max_size=interactive_proxy_max_size,
)
```

When `self._settings_service is None`, both variables stay `None`, so
both `ProcessingWorker()` constructions receive `proxy_max_size=None,
interactive_proxy_max_size=None` -- which, per the `ProcessingWorker`
wiring above, falls through to exactly today's
`ProxyManager.DEFAULT_PROXY_SIZE` /
`DEFAULT_INTERACTIVE_PROXY_SIZE` behavior. Likewise, a
`SettingsService` with no stored preference returns `None` from both
getters, producing the identical no-op path. This "no-op when nothing
is configured" behavior is the slice's most important regression
guard and is pinned by dedicated tests (section 6).

### Takes effect after restart, by design

This preference is read once, at `ImageController.__init__` time (i.e.
at app startup, when `MainWindow` constructs its one
`ImageController`). It is **not** live-reloaded if the user changes it
in Preferences while the app is running. Making it live would mean
tearing down and rebuilding both `ProcessingWorker`s' `ProxyManager`s
mid-session -- invalidating whatever proxy/original image state and
in-flight processing-queue entries they currently hold, with no
established mechanism in this codebase for that kind of hot-swap. That
is out of scope for this slice. Instead, `PreferencesDialog` shows an
explicit restart note under the two spin boxes
("Preview size changes take effect after restarting PhotoEdit."), and
`MainWindow._show_preferences()` echoes the same point in its
post-accept status-bar message.

### `PreferencesDialog`

Mirrors `ExportDialog`'s general shape (`QVBoxLayout` of `QGroupBox`
sections, Cancel/OK buttons at the bottom):

- **General** `QGroupBox`: one `QCheckBox` ("Confirm before overwriting
  exported files"), initialized from
  `settings_service.get_confirm_export_overwrite()` (default `True`
  when `settings_service` is `None`, matching that getter's own
  documented default).
- **Performance** `QGroupBox`: two `QSpinBox`es (range 200-6000px,
  `" px"` suffix) -- "Preview quality (max dimension)" and "Interactive
  preview size (max dimension)" -- each initialized from the stored
  preference if set, else from `ProxyManager.DEFAULT_PROXY_SIZE` /
  `DEFAULT_INTERACTIVE_PROXY_SIZE` (shown as the real effective value,
  never left blank), plus the restart-note `QLabel` described above.
- Accept (`_on_accept`): when `settings_service is not None`, persists
  all three values, then calls `self.accept()`. When `settings_service
  is None`, there is nothing to persist to, so it just calls
  `self.accept()` -- the dialog still opens and can be looked at/closed
  without crashing, it simply cannot save anything (documented in the
  class/constructor docstring). Cancel (wired directly to
  `QDialog.reject`) never touches `settings_service` at all.

## 4. Contracts

- `SettingsService.get_proxy_max_size(self) -> Optional[int]` /
  `set_proxy_max_size(self, size: int) -> None` -- new.
- `SettingsService.get_interactive_proxy_max_size(self) -> Optional[int]` /
  `set_interactive_proxy_max_size(self, size: int) -> None` -- new.
- `ProcessingWorker.__init__(self, parent=None, proxy_max_size:
  Optional[int] = None, interactive_proxy_max_size: Optional[int] =
  None)` -- two new optional parameters appended after the existing
  `parent`; omitting them is 100% behavior-preserving.
- `ImageController.__init__` signature unchanged; its existing optional
  `settings_service` parameter now also drives these two preferences
  when present.
- `PreferencesDialog.__init__(self, settings_service:
  Optional[SettingsService] = None, parent=None)` -- new class.
- `MainWindow._show_preferences(self) -> None` -- new method, wired to
  the new "&Preferences..." (`Ctrl+,`) Edit-menu action.

## 5. Nuances and failure modes

**`QSettings.value(key, None, type=int)` default-coercion trap.** As
noted in section 3, passing `type=int` coerces the *default* value
too, not just the stored one -- so `None` silently became `0`. Caught
by the `test_default_is_none` tests before this shipped; the fix is
the explicit `contains()` check, mirrored for both new preferences.

**`0` is never passed through.** `proxy_max_size or
ProxyManager.DEFAULT_PROXY_SIZE` means a (currently impossible, since
the spin box's minimum is 200) stored `0` would also fall back to the
default rather than being passed through literally. This is
acceptable: `0` is never a meaningful proxy size, so treating it the
same as "unset" is strictly safer, not a bug.

**Per-session fixed threading model, confirmed unaffected.** Nothing
about `use_threading`, worker start/stop lifecycle, or
`ProcessingController` changed; `proxy_max_size` /
`interactive_proxy_max_size` only ever flow into `ProxyManager`'s two
existing size fields, never into any thread-count or queue-concurrency
code path.

**Preferences dialog with no settings service.** Deliberately still
opens and is fully interactive (so a caller without a
`SettingsService`, e.g. in an isolated test or a stripped-down
embedding, never crashes just by opening Preferences), but Accept has
nothing to write to, so it behaves identically to Cancel for state
(nothing persists) while still returning an accepted dialog result.

**`ProxyManager.max_size` setter exists but is unused by this wiring.**
`ProxyManager` already has a live `max_size` property setter that
regenerates the proxy immediately (`if value != self._max_size: ...
self._generate_proxy()`). This slice does not call it anywhere --
preferences are only ever passed in at `ProxyManager` construction
time, never mutated on a live instance. That setter remains available
for a future slice that wants to make this preference actually live
mid-session; today's choice not to use it is itself the documented
"restart required" decision from section 3.

## 6. Test plan

- `tests/unit/test_services/test_settings_service.py`: new
  `TestSettingsServiceProxyMaxSize` and
  `TestSettingsServiceInteractiveProxyMaxSize` classes -- default is
  `None`, set-then-get round-trips as an `int`, overwriting a
  previously-set value, and the two keys are independent of each
  other.
- `tests/unit/test_views/test_preferences_dialog.py` (new file):
  widgets show `ProxyManager`'s defaults when nothing is stored; a
  default-checked confirm-overwrite checkbox; widgets reflect existing
  stored preferences; the dialog does not crash with
  `settings_service=None`; Accept persists all three values; Accept
  with no settings service does not crash and still accepts; Cancel
  (`reject()`) persists nothing.
- `tests/unit/test_processing/test_processing_worker.py`: new
  `TestProcessingWorkerProxySizePreferences` class -- default
  construction (`ProcessingWorker()`) still produces
  `ProxyManager.DEFAULT_PROXY_SIZE`/`DEFAULT_INTERACTIVE_PROXY_SIZE`
  (regression guard); explicit `proxy_max_size`/
  `interactive_proxy_max_size` reach the internal `ProxyManager`
  unchanged; explicit `None` values fall back to the same defaults as
  omitting them entirely.
- `tests/unit/test_controllers/test_image_controller.py`: new
  `TestImageControllerProxySizePreferences` class (`use_threading=True`,
  so both real `ProcessingWorker`s are actually constructed) -- a
  `SettingsService` with stored preferences reaches both
  `controller._processing_worker.proxy_manager` and
  `controller._final_processing_worker.proxy_manager`;
  `settings_service=None` leaves both workers at
  `ProxyManager`'s class defaults (most important regression guard);
  a `SettingsService` with no stored preferences behaves identically to
  `settings_service=None`.

## 7. Rollout

Additive only: two new `SettingsService` key/getter/setter pairs, two
new optional `ProcessingWorker.__init__` parameters (both defaulting to
`None`, preserving today's exact construction when omitted), a few new
lines in `ImageController._setup_async_processing()` guarded by the
existing `self._settings_service is not None` pattern already used
throughout that file, one new dialog module
(`src/views/preferences_dialog.py`), and one new `MainWindow` menu
action + method. No existing method signature changed its meaning for
an existing caller; every call site that constructed a
`ProcessingWorker()` or `ImageController(...)` with its previous
arguments continues to behave identically. A plain revert removes the
feature with no data migration in either direction (the two new
`QSettings` keys are simply never read again; nothing else depends on
them).

## 8. Implementation summary

Added `SettingsService.get_proxy_max_size`/`set_proxy_max_size` and
`get_interactive_proxy_max_size`/`set_interactive_proxy_max_size`
(`src/services/settings_service.py`), two new optional
`ProcessingWorker.__init__` parameters that forward into its internal
`ProxyManager` construction with `ProxyManager`'s own class constants
as the single source of truth for the fallback
(`src/processing/processing_worker.py`), and
`ImageController._setup_async_processing()` reading those two
preferences from `self._settings_service` (when present) and passing
them into both of its `ProcessingWorker` constructions
(`src/controllers/image_controller.py`). Added a new
`PreferencesDialog` (`src/views/preferences_dialog.py`) with General
(confirm-overwrite toggle) and Performance (two preview-size spin
boxes, plus a restart note) sections, and wired it into `MainWindow`
via a new "&Preferences..." (`Ctrl+,`) Edit-menu action and
`_show_preferences()` method (`src/views/main_window.py`). `Ctrl+,` was
checked against every shortcut already registered in
`_setup_menu_bar()` (`Ctrl+O`, `Ctrl+Shift+O`, `Ctrl+E`,
`Ctrl+Shift+E`, `Ctrl+Q`, `Ctrl+Z`, `Ctrl+Shift+Z`, `Ctrl+R`,
`Ctrl+Alt+C`, `Ctrl+Alt+V`, `0`, `1`, `Ctrl+=`, `Ctrl+-`, `F5`, `F6`)
and the global menu-bar-hidden shortcuts registered via
`self.addAction(action)` in `_create_action`; no collision was found,
so the standard cross-platform Preferences convention was used as-is.

Local Storage path relocation, Interface theme switching, Import
defaults, and threading were deliberately **not** built in this slice
-- see section 1 for why each is a durable gap rather than an
omission, and `docs/planning/PRODUCT_ROADMAP.md`'s Phase B bullet,
updated to **Partial** (not Done) to reflect this.

**Deviation note.** None of substance. The one thing not anticipated
going in was the `QSettings.value(key, None, type=int)` default-
coercion behavior (section 3/5) -- caught immediately by the new
`test_default_is_none` tests and fixed with an explicit
`contains()` check before this was considered complete.

Verification: new tests across the four files above, **19 passed**
(`SettingsService` / 6 tests across two new classes,
`PreferencesDialog` / 7 tests across three new classes,
`ProcessingWorker` / 3 tests, `ImageController` / 3 tests); complete
suite run via
`QT_QPA_PLATFORM=offscreen python3 -m pytest -q --deselect
tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::test_geometry_is_restored_on_next_launch`
**898 passed, 1 skipped, 1 deselected in 115.97s** (879 pre-existing +
19 new; the deselected test is the same pre-existing
offscreen-rendering flake noted in prior implementation notes,
unrelated to this slice; the 1 skipped test is pre-existing and
unrelated to this work). No other failures or flakes observed. A live
GUI smoke test (actually opening Preferences and pressing `Ctrl+,` in
the real running app) was not performed in this non-interactive
environment; the behavior is instead pinned at the `SettingsService` /
`PreferencesDialog` / `ProcessingWorker` / `ImageController` unit-test
level.
