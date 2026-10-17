# Crash recovery notice (clean-shutdown tracking)

Related roadmap: Phase K, "Session persistence" (PDF section 23),
sub-bullet "Crash-safe draft autosave (professional): background or
event-coalesced snapshot of adjustment state + library index to a temp
or sidecar path; on startup, offer recovery if a clean shutdown flag
was not set." Like Copy/Paste Edit Settings and Export with Previous,
this is menu/controller/settings plumbing, not an image processor
slice, so this note follows that adapted section structure rather than
the processor template.

## 1. Problem, goal, and non-goals

**Scoping finding (investigated before any code was written).** The
roadmap bullet describes two halves: (a) an event-coalesced snapshot of
adjustment state, and (b) a clean-shutdown flag plus a recovery offer
on next launch. Reading the code confirmed that half (a) **already
exists** and was not built here:

- `MainWindow._adjustment_persist_timer` is a 400ms, single-shot
  `QTimer` created in `__init__` (`src/views/main_window.py`). Grepping
  `_adjustment_persist_timer.start()` across the file turns up ten call
  sites -- every tonal/HSL/curve/profile/reset/paste/zoom change that
  mutates the current image's adjustment state restarts it.
- Its `timeout` is connected to `_persist_current_adjustments()`, which
  reads `ImageController.get_adjustment_state()` and calls
  `LibraryController.set_entry_adjustment_state(library_id, file_path,
  payload)`.
- That call reaches `LibraryCatalogService.set_entry_adjustment_state()`
  (`src/services/library_catalog_service.py`), which mutates the
  in-memory `LibraryRecord`/`LibraryEntry` and then calls
  `self._save_catalog()` **synchronously, in the same call, with no
  further delay or batching**.
- `_save_catalog()` calls `_write_catalog()`, which serializes the
  whole catalog to JSON and writes it via a temp-file-then-`replace()`
  pattern (`temp_path.write_text(...)`, `temp_path.replace(self._catalog_path)`)
  -- a real, durable, atomic write to a real file on disk.

So the chain is: any adjustment change -> timer armed -> (at most 400ms
later, debounced) -> adjustment state written synchronously to the
on-disk catalog JSON, atomically. This **is** an event-coalesced
snapshot of adjustment state, already shipped by earlier slices (the
persist-timer plumbing itself, and `LibraryCatalogService`'s catalog
persistence, both predate this slice). The "library index" is the same
catalog file the adjustment state lives in, so there is no separate
index to snapshot.

**Goal (actual scope of this slice).** Build only the genuinely missing
half: track whether the previous session reached a clean shutdown, and
if it did not, show one honest, session-level notice on the next
launch, after the window is visible.

**Non-goals:**

- No new snapshot-writing subsystem, sidecar file format, or "library
  index" dump. The existing continuous catalog persistence already
  covers that need; duplicating it would be a parallel, redundant
  write path and a maintenance liability, not an improvement.
- No "recover my unsaved draft" restore flow. There is nothing *to*
  restore beyond what is already continuously persisted -- the notice
  says exactly that, rather than implying a fancier recovery action
  happened.
- No per-image "was this specific edit lost" diagnosis. The notice is
  a single session-level message, not a report of which images (if
  any) have unsaved changes -- since the existing persistence is
  already continuous, that distinction is rarely meaningful and was
  out of scope.
- No change to `ProjectModel` or a K0 schema. This slice touches only
  `SettingsService` (a new boolean key) and `MainWindow` startup/
  shutdown wiring.

## 2. Current behavior (before this slice)

`SettingsService` persisted window geometry/state, last-used
directories, the current image path, export preferences, and proxy
sizes -- but nothing about whether the previous run exited cleanly.
`MainWindow.closeEvent()` already saved geometry/state and called
`self._settings_service.sync()` near its end, but no flag distinguished
a normal `closeEvent()` exit from a crash, force-kill, or power loss
(in all of which `closeEvent()` never runs at all).

## 3. Design

### New `SettingsService` key

```python
_KEY_CLEAN_SHUTDOWN = "session/clean_shutdown"

def get_clean_shutdown(self) -> bool:
    return bool(self._settings.value(_KEY_CLEAN_SHUTDOWN, True, type=bool))

def set_clean_shutdown(self, clean: bool) -> None:
    self._settings.setValue(_KEY_CLEAN_SHUTDOWN, bool(clean))
```

`get_clean_shutdown()` defaults to `True` when unset, so a fresh
install (or a wiped settings store) never shows a false-positive
notice on its very first launch. This is a different default shape
than `get_proxy_max_size()`/`get_interactive_proxy_max_size()`, which
use a `contains()`-first check and return `Optional[int]` with *no*
in-process default (their real default lives on `ProxyManager`
instead) -- those two genuinely need to distinguish "never set" from
"explicitly set to the same value as the fallback" because they hand
that distinction to a caller elsewhere. This flag has no such external
default to defer to and always wants a concrete `True`/`False`, so it
follows `get_confirm_export_overwrite()`'s plain `type=bool` pattern
instead: passing `type=bool` to `QSettings.value()` keeps a backend
that persists booleans as the literal strings `"true"`/`"false"` (a
string is always truthy in Python) from silently defeating the flag.

### Startup sequencing (`MainWindow.__init__`)

Right after `self._settings_service` is assigned (before any other
service construction), in this exact order:

```python
self._last_shutdown_was_clean = self._settings_service.get_clean_shutdown()
self._settings_service.set_clean_shutdown(False)
self._settings_service.sync()
```

Order matters: reading *before* writing is what lets this code ever
see a `False` left over from a real crash; reading after the write
would always see the just-written `False`.

**Why `sync()` here, and why it matters more than anywhere else this
service calls it.** `QSettings` buffers writes in memory and is
documented to flush them "from time to time" and on normal destruction
-- it does not guarantee every `setValue()` reaches the backing
INI/registry/plist immediately. Every *other* `sync()` call in this
codebase (e.g. the one already in `closeEvent()`) is flushing state
that only needs to survive an *orderly* shutdown, where the process is
still running long enough for Qt's own eventual/exit-time flush to
happen anyway. This flag is different: its entire purpose is to still
be `False` on disk *after* a crash that could happen at any moment
following this line -- a crash is exactly the scenario where no later,
implicit flush will ever run. So this call cannot rely on "QSettings
will get around to it"; it must flush synchronously, right here,
before `__init__` does anything else that could fail or hang. This is
the crux of the whole feature: without this explicit `sync()`, a crash
occurring before QSettings' own next implicit flush would silently
leave the stale `True` from the *previous* clean exit on disk, and the
notice would never fire for the crash that just happened.

### Deferring the notice until after the window is visible

`MainWindow.__init__` runs entirely before `show()` is called (in
`src/main.py`, and in every test fixture via `qtbot.waitExposed`), so a
`QMessageBox` raised synchronously inside `__init__` would appear
before the window itself is on screen -- confusing UX, and were the
notice at the very top of `__init__`, nothing else would even be
constructed yet to use `QMessageBox.information(self, ...)` as a
proper parent.

A new `_maybe_show_crash_recovery_notice()` method was added and
scheduled with `QTimer.singleShot(0, self._maybe_show_crash_recovery_notice)`
at the very end of `__init__` (after `_restore_last_session_image()`).
A zero-delay `QTimer.singleShot` does not run synchronously; it queues
the callback on the Qt event loop, which only starts processing events
once something actually pumps it -- `app.exec()` in `src/main.py`
(called after `window.show()`), or `qtbot.waitExposed(window)` in tests
(which also pumps the loop). Either way, by the time the queued call
runs, the window is already visible. This mechanism was chosen over
wiring something into `src/main.py` because `MainWindow` already owns
both halves of this feature's state (`_last_shutdown_was_clean`,
`_settings_service`) and is the thing every test already constructs
directly -- adding a hook in `main.py` would need no changes to ship
the feature but would also need its own, separate, harder-to-trigger
test path for no benefit.

```python
def _maybe_show_crash_recovery_notice(self) -> None:
    if self._last_shutdown_was_clean:
        return
    QMessageBox.information(
        self,
        "PhotoEdit",
        "PhotoEdit may not have closed cleanly last time. Your edits "
        "are saved automatically as you work, so no changes should "
        "have been lost.",
    )
```

### Shutdown sequencing (`MainWindow.closeEvent`)

One line added, directly before the existing `sync()` call, so the
`True` it writes is included in that same flush:

```python
self._settings_service.set_clean_shutdown(True)
self._settings_service.sync()
```

## 4. Contracts

- `SettingsService.get_clean_shutdown(self) -> bool` -- new method,
  default `True` when unset.
- `SettingsService.set_clean_shutdown(self, clean: bool) -> None` --
  new method.
- `MainWindow._last_shutdown_was_clean: bool` -- new instance
  attribute, set once in `__init__` from the settings read, before the
  flag is flipped to `False` for the current session. Not mutated
  again after `__init__`.
- `MainWindow._maybe_show_crash_recovery_notice(self) -> None` -- new
  method, invoked exactly once per `MainWindow` instance via
  `QTimer.singleShot(0, ...)`.
- `MainWindow.closeEvent` -- behavior change: now also persists
  `clean_shutdown=True` before its existing `sync()` call. No signature
  change.
- No existing method's signature changed.

## 5. Nuances and failure modes

**Self-healing across repeated crashes.** If the app crashes twice in a
row (never reaching `closeEvent` either time), the flag simply stays
`False` on disk the whole time: the first crash leaves it `False`
(written at startup before the crash), the second launch reads that
`False`, shows the notice, immediately rewrites `False` again (still
"in progress"), and if *that* session also crashes, the flag is still
`False`, so the *third* launch also correctly shows the notice. The
notice only stops appearing once a session actually reaches
`closeEvent()` and writes `True`. This means the behavior degrades
exactly as intended: it never incorrectly suppresses the notice after
repeated crashes, and it always clears on the next genuinely clean
exit (self-healing in one clean run, not requiring any special
reset logic).

**A crash inside `_maybe_show_crash_recovery_notice()` itself, or
between startup and `closeEvent`, every single time.** Since the flag
is already written as `False` at the top of `__init__` (before the
notice is even scheduled), a crash at any point afterwards -- including
inside the notice handler itself -- still leaves `False` on disk, so
the *next* launch still correctly offers the notice. The notice
mechanism's own fragility cannot suppress a future notice; only a
genuine clean `closeEvent()` can.

**Not a substitute for actual data-loss detection.** The notice cannot
and does not distinguish "a crash happened but the debounced timer had
already written everything" (the overwhelmingly common case, since the
timer runs on essentially every edit) from "a crash happened less than
400ms after an edit, before the timer fired" (a narrow real gap, but
one that predates this slice and is unaffected by it -- it is a
property of the 400ms debounce window itself, not of this clean-
shutdown tracking). The notice's wording was deliberately written to
make a true, modest claim ("saved automatically... no changes *should*
have been lost") rather than an unconditional guarantee.

**Multiple `MainWindow` instances in one process (tests).** Each
`MainWindow()` construction reads-then-clears the flag independently,
which is exactly what the test suite relies on to exercise both
branches without needing a real crash.

## 6. Test plan

`tests/unit/test_services/test_settings_service.py`:
`TestSettingsServiceCleanShutdown` -- default `True` when unset; set
`False`, read back `is False`; set `True` again, read back `is True`.

`tests/ui/test_main_window.py`: new `TestCrashRecoveryNotice` class,
alongside `TestMainWindowSettingsPersistence` (closest sibling: it
already exercises `SettingsService` + real `MainWindow` construction/
close cycles):

- Constructing a `MainWindow` with a currently-`True` flag (the
  default/clean case) does not call `QMessageBox.information`, and
  leaves the flag `False` immediately after construction (the new
  session is marked in-progress either way).
- Constructing one with the flag pre-set to `False` does call
  `QMessageBox.information` (asserted via `patch` on
  `src.views.main_window.QMessageBox.information`) with text containing
  "may not have closed cleanly", and leaves the flag `False` after
  construction too -- same post-construction state as the clean case,
  confirming only the notice differs, not the bookkeeping.
- Calling `.close()` on a constructed window sets the flag back to
  `True` and calls `SettingsService.sync()` (asserted via
  `patch.object(settings, "sync", wraps=settings.sync")`).

## 7. Rollout

Purely additive: one new `SettingsService` key/getter/setter, one new
`MainWindow` instance attribute, one new method, three lines added to
`__init__`/`closeEvent`. No existing method signature changed, no
schema change, nothing to migrate. A plain revert removes the feature
entirely; any stale `session/clean_shutdown` key left in an old
settings file is simply ignored by code that no longer reads it.

## 8. Implementation summary

Added `SettingsService.get_clean_shutdown()` /
`set_clean_shutdown()` (`src/services/settings_service.py`, new
`_KEY_CLEAN_SHUTDOWN = "session/clean_shutdown"`). In
`MainWindow.__init__` (`src/views/main_window.py`), immediately after
`self._settings_service` is assigned: read the flag into
`self._last_shutdown_was_clean`, write `False`, and call `sync()`
synchronously so the "session in progress" marker is crash-resilient
from the earliest possible point. At the end of `__init__`, scheduled
`_maybe_show_crash_recovery_notice()` via `QTimer.singleShot(0, ...)`
so the notice (`QMessageBox.information`) only ever appears after the
window is visible. In `closeEvent`, added
`self._settings_service.set_clean_shutdown(True)` directly before the
existing `self._settings_service.sync()` call.

Confirmed, by direct code reading (not assumed), that the "event-
coalesced snapshot of adjustment state" half of the roadmap bullet was
already fully implemented by pre-existing infrastructure -- the 400ms
`_adjustment_persist_timer` (ten call sites across `main_window.py`)
feeding `LibraryController.set_entry_adjustment_state()` ->
`LibraryCatalogService.set_entry_adjustment_state()`, which calls
`_save_catalog()` synchronously and writes the catalog JSON atomically
via a temp-file-then-`replace()` pattern. This slice therefore adds
only the clean-shutdown-flag-and-notice half, as scoped above, and does
not duplicate that existing write path.

**Deviation note.** None of substance. The spec left the exact hook
point for the post-show notice to this slice's judgment; `QTimer.
singleShot(0, ...)` fired from the end of `MainWindow.__init__` was
chosen over a `src/main.py` hook, for the reasons given in section 3
(co-locating the mechanism with the state it depends on, and with the
existing test-construction path).

Verification: new tests (`TestSettingsServiceCleanShutdown` in
`tests/unit/test_services/test_settings_service.py`,
`TestCrashRecoveryNotice` in `tests/ui/test_main_window.py`) **6
passed** (3 + 3); complete suite run via `QT_QPA_PLATFORM=offscreen
python3 -m pytest -q --deselect
tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::test_geometry_is_restored_on_next_launch`
**1024 passed, 1 skipped, 1 deselected in 141.80s** (1018 pre-existing
+ 6 new; the deselected test is the same pre-existing offscreen-
rendering flake noted in prior implementation notes, unrelated to this
slice; the 1 skipped test is pre-existing and unrelated). No other
failures or flakes observed in this run (including no occurrence of
the separately-noted intermittent `TestLibraryPanel::test_clear_library`
flake). A live GUI smoke test (actually killing the process and
relaunching to see the real notice) was not performed in this non-
interactive environment; the behavior is instead pinned at the
`MainWindow`/`SettingsService` unit-test level, including through a
real `QTimer.singleShot` + `qtbot.waitExposed` event-loop pump rather
than calling the notice method directly.
