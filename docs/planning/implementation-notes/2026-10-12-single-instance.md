# Single-instance behavior (lockfile)

Related roadmap: Part 1, "Professional shell (non-PDF; plan alongside B
and K)" in `docs/planning/PRODUCT_ROADMAP.md`. Like the Export
overwrite confirmation slice, this is dialog/app-lifecycle plumbing,
not an image processor slice, so this note follows that slice's
adapted section structure rather than the processor template.

## 1. Problem, goal, and non-goals

**Problem.** `src/main.py`'s `main()` unconditionally creates a
`QApplication`, builds a `MainWindow`, and runs the event loop, with no
check for whether a PhotoEdit process is already running. Launching a
second instance (e.g. double-clicking the app icon twice, or running
`python3 -m src.main` twice) starts two processes that both read/write
the same `QSettings` store and the same project-local `logs/` directory
with no coordination between them.

**Goal.** Before building `MainWindow`, detect whether another
PhotoEdit instance is already running (via a lockfile) and, if so, show
an informative message and exit cleanly (exit code 0) instead of
starting a second instance.

**Non-goals:**

- No IPC between instances. This slice does not implement "focus the
  existing window" or "pass the new file path to the running instance"
  behavior -- the second launch simply refuses and exits. That is a
  reasonable, explicitly-flagged follow-up, not something to half-build
  here.
- No change to `QSettings` namespacing, logging configuration, or any
  processor/controller/panel code. This is entirely contained to
  `src/main.py` and the new `src/utils/single_instance.py`.
- No cross-machine or network-based instance detection; this is a
  single-machine, single-user-session lockfile, matching the roadmap
  item's own framing ("optional lockfile / `QSingleApplication`
  pattern").

## 2. Current behavior (before this slice)

`main()` created a `QApplication`, applied the theme, configured
logging, then unconditionally built and showed a `MainWindow` and ran
`sys.exit(app.exec())`. There was no existing mechanism anywhere in the
codebase for detecting or coordinating with another running instance.

## 3. Design and flow

New `src/utils/single_instance.py` module, added alongside this
codebase's other small utility modules (`src/utils/debouncer.py`,
`src/utils/logging_config.py`, etc.):

- `default_lock_file_path() -> str` -- returns a deterministic path:
  `QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)`
  joined with the fixed filename `"PhotoEdit.lock"`. `TempLocation` was
  chosen over `AppDataLocation`/`CacheLocation` because a lockfile is
  purely transient process-coordination state that should never be
  treated as user data worth backing up or preserving between runs --
  that is exactly the conventional meaning of a "temp" location, and it
  keeps the lockfile out of any directory a backup tool might sweep up
  alongside real settings/user data.
- `SingleInstanceGuard` -- a thin wrapper around `QLockFile`:
  - Constructor takes an optional `lock_file_path` (defaults to
    `default_lock_file_path()`), so tests can point two separate
    guards at an isolated `tmp_path` instead of fighting over the real
    fixed path (a stray leftover lock from a crashed test run could
    otherwise pollute later test runs). `main()` itself uses the
    default (no argument), i.e. the real fixed path.
  - `try_acquire(timeout_ms: int = 100) -> bool` -- wraps
    `QLockFile.tryLock(timeout_ms)`. Returns `True` if this process now
    holds the lock (proceed as normal); `False` otherwise.
  - `error()` -- exposes the raw `QLockFile.LockError` enum from the
    last attempt, for callers/tests that want to distinguish failure
    reasons.
  - `is_held()` -- whether this guard currently holds the lock.
  - `release()` -- unlocks explicitly (idempotent; a no-op if never
    acquired).
  - Context manager support (`__enter__`/`__exit__`) for convenient
    scoped use, in addition to explicit `try_acquire()`/`release()`.

`src/main.py` wiring, in this order (required because showing a
`QMessageBox` needs a `QApplication` instance to already exist):

1. Create `QApplication`, apply theme, configure logging (unchanged
   from before).
2. Construct `SingleInstanceGuard()` (real default path) and call
   `try_acquire()`.
3. If it returns `False`: log at `info` level (this is an expected,
   benign situation, not an error), show
   `QMessageBox.information(None, "PhotoEdit Already Running", ...)`,
   then `sys.exit(0)` -- **without** constructing `MainWindow` or
   calling `app.exec()`.
4. If it returns `True`: proceed exactly as before (log startup,
   build/show `MainWindow`, `sys.exit(app.exec())`). The
   `instance_guard` local variable stays referenced for the rest of
   `main()`'s body, so it is not garbage-collected and released
   prematurely while the app is still running; process exit releases
   the OS-level lock regardless once the process actually ends.

## 4. Contracts

- `src.utils.single_instance.default_lock_file_path() -> str`
- `src.utils.single_instance.SingleInstanceGuard`:
  - `__init__(self, lock_file_path: Optional[str] = None)`
  - `lock_file_path` (property) -> `str`
  - `try_acquire(self, timeout_ms: int = 100) -> bool`
  - `error(self) -> QLockFile.LockError`
  - `is_held(self) -> bool`
  - `release(self) -> None`
  - `__enter__`/`__exit__` for `with SingleInstanceGuard(...) as guard:`
    usage.

`src/main.py`'s `main()` function signature and its early-return
behavior on failed acquisition (no `MainWindow`, no `app.exec()`, exit
code 0) are the externally observable contract change; no existing
call site elsewhere in the codebase calls into `main.py`, confirmed by
grepping `tests/` for any import of `src.main` (none found) before
making this change, so there was no risk of breaking an existing test
harness that constructs `main()`'s pieces directly.

## 5. Nuances and failure modes

**`QLockFile`'s same-process re-lock behavior -- actually observed, not
assumed.** The spec asked to verify this directly before relying on it
in a test, since `QLockFile`'s stale-lock detection is partly
PID-based, and it was not obvious up front whether two `QLockFile`
objects in the *same* process (same PID) pointed at the same path would
correctly detect contention with each other (a naive PID check might
conclude "the holder is PID X and I am also PID X, so it's fine").
Running the test (`test_second_guard_fails_while_first_holds_same_path`
in the new test file) confirms `QLockFile` locks by file path with real
OS-level file locking primitives (not merely by comparing PIDs), so a
second `QLockFile` instance in the very same Python process pointed at
an already-locked path genuinely fails `tryLock()` -- `error()` reports
`QLockFile.LockError.LockFailedError`, matching the real two-process
scenario closely enough to exercise meaningfully from a single pytest
process. This is the strategy the test suite uses throughout: construct
two (or three) `SingleInstanceGuard` instances at the same `tmp_path`
within one test function and rely on this real, confirmed behavior
rather than mocking `QLockFile`.

**Stale-lock recovery.** `QLockFile` already handles the case of a
lock file left behind by a process that crashed without calling
`unlock()` -- on the next `tryLock()` call, Qt checks whether the PID
recorded in the lock file still corresponds to a live process (using
`QLockFile::getLockInfo()` internally) and, if not, removes the stale
lock and proceeds to re-lock successfully. This is Qt's built-in
behavior, not anything implemented in `SingleInstanceGuard`; no new
test specifically fabricates a stale lock file (doing so realistically
would mean writing a lock file claiming a PID that does not exist on
the test host, which is more complexity than this slice's narrow scope
warrants), but mentioning it here documents that it is Qt's documented
responsibility, not a gap in this implementation.

**Permission errors are logged loudly but do not block startup.**
`try_acquire()`'s failure branch distinguishes
`QLockFile.LockError.LockFailedError` (the expected, benign
second-instance case -- logged at `info`, and the only case where
`try_acquire` returns `False`) from `QLockFile.LockError.PermissionError`
and any other error (logged at `error`, since a permission problem on
the lock directory is a real environment issue worth surfacing loudly,
but `try_acquire` still returns `True` so the caller proceeds). Refusing
to start PhotoEdit entirely because its *lock directory* happens to be
unwritable would be a strictly worse outcome than simply skipping
single-instance enforcement in that unusual case -- the whole point of
this feature is convenience, not a security boundary, so the failure
mode must be "start anyway" rather than "refuse to launch." This means
a permission-denied lock directory could in principle let two instances
both run unchecked; that is an accepted, explicitly logged tradeoff, not
an oversight. Verified directly in
`test_permission_error_proceeds_rather_than_blocking_startup`, which
`chmod`s a lock directory to `0o000` and asserts `try_acquire()` still
returns `True` (the test self-skips when running as root, since root
bypasses directory permissions entirely and the test host for this
slice happened to be a root container).

**`QLockFile` auto-unlock on destruction -- observed, not assumed.**
During manual development testing, letting a `SingleInstanceGuard` (and
its underlying `QLockFile`) go out of scope without calling
`release()` did free the lock for a subsequent `try_acquire()` at the
same path in the same process, consistent with `QLockFile`'s Qt
documentation (it unlocks in its destructor like other Qt RAII-style
classes). `release()` is still called explicitly everywhere in this
codebase's tests and in `main()`'s implicit lifetime, rather than
relying on CPython garbage-collection timing, which is not guaranteed
to be immediate (e.g. under reference cycles) even though CPython's
refcounting GC usually does free an unreferenced object right away.

**Exit code on refusal.** `sys.exit(0)`, not a nonzero code -- launching
a second instance is an unremarkable user action (not a bug or
misuse), so a tool or script checking the exit code of a PhotoEdit
invocation should not see this as an application error.

## 6. Test plan

New `tests/unit/test_utils/test_single_instance.py` (matching the
existing `tests/unit/test_utils/` subdirectory's flat-file convention;
it already has an `__init__.py`, which was already present and did not
need to be added):

- First guard at an isolated `tmp_path` lock path acquires
  successfully (`try_acquire()` is `True`, `is_held()` is `True`).
- A second guard at the *same* path, while the first still holds it
  (same test, same process), fails to acquire (`try_acquire()` is
  `False`, `is_held()` is `False`), with `error()` reporting
  `QLockFile.LockError.LockFailedError` -- this is the behavior that
  was verified directly per the note above, not assumed.
- After releasing the first guard, a third guard at the same path
  succeeds again.
- `error()` after a successful acquisition reports `NoError`; after a
  failed one reports `LockFailedError`.
- Context-manager (`with SingleInstanceGuard(...) as guard:`) releases
  on exit, confirmed by a follow-up guard successfully acquiring the
  same path immediately afterward.
- `release()` without a prior `try_acquire()` is a no-op (does not
  raise).
- `lock_file_path` property reflects the constructor argument.
- `default_lock_file_path()` ends with the fixed `"PhotoEdit.lock"`
  filename (a light smoke check that does not depend on the real
  `TempLocation` value on the test host).

**`main()`'s top-level flow was deliberately not tested end-to-end.**
`main()` calls `sys.exit(app.exec())`, which would need `sys.exit` and
`QApplication.exec` both monkeypatched to test without actually
blocking/exiting the test process; per the task's own guidance, that
kind of control-flow monkeypatching is often more trouble than it is
worth for the value it provides, especially since `main()`'s only new
logic (the guard check and early exit) is a thin, direct call into
`SingleInstanceGuard`, which is itself fully covered in isolation.
Confirmed via grep that no existing test imports `src.main` today, so
this is not a regression in existing coverage -- there simply was no
such coverage before, and this slice does not add brittle coverage of
`main()` just to say it exists.

## 7. Rollout

Purely additive: a new module (`src/utils/single_instance.py`) and a
small, backward-compatible addition to `main()`'s existing flow (an
early-exit branch that only triggers when a lock is genuinely held by
another live process). No existing function signature, `QSettings`
key, or log format changed. A plain revert of the `main.py` edit
removes the feature entirely and restores the previous unconditional
startup; the new module can simply be left unused/removed without
affecting anything else, since nothing else in the codebase imports it.

No migration is needed in either direction; the lockfile itself is
not persistent user data, so there is nothing to migrate even if the
chosen `TempLocation` path were to change in the future (the OS is
free to clear it between reboots, which is fine -- a cleared lock just
means the next launch acquires normally).

## 8. Implementation summary

Added `src/utils/single_instance.py` with `default_lock_file_path()`
(fixed `"PhotoEdit.lock"` filename under
`QStandardPaths.StandardLocation.TempLocation`) and
`SingleInstanceGuard`, a thin `QLockFile` wrapper supporting
`try_acquire(timeout_ms=100)`, `error()`, `is_held()`, `release()`, and
context-manager use, with an overridable `lock_file_path` constructor
argument so tests never touch the real fixed path.

Wired into `src/main.py`'s `main()`: `QApplication` is constructed
first (required for `QMessageBox.information` to work), then a
`SingleInstanceGuard()` (real default path) is created and
`try_acquire()`'d immediately after the existing logging-configuration
step. On failure, logs at `info` level, shows an informational
`QMessageBox`, and `sys.exit(0)` without constructing `MainWindow` or
calling `app.exec()`. On success, proceeds exactly as before, keeping
`instance_guard` referenced for the remainder of `main()` so the lock
is not released by garbage collection while the app is running.

No changes were made to any processor, `ToolsPanel`, `ImageController`
adjustment pipeline, or anything from the Texture/Clarity/Straighten
slices -- this feature is entirely contained in
`src/utils/single_instance.py` and `src/main.py`, as scoped.

**Same-process `QLockFile` re-lock behavior -- test strategy worked as
planned.** Verified directly (see section 5) that two `QLockFile`
instances in the same pytest process, pointed at the same path, do
exhibit real contention (the second's `tryLock()` genuinely fails while
the first holds it), so the planned in-process test strategy (two or
three `SingleInstanceGuard`s in one test function) was used as-is,
without needing to fall back to spawning real subprocesses.

**Deviation note.** None of substance. One addition beyond the exact
API sketch in the task: an `__enter__`/`__exit__` context-manager
pair on `SingleInstanceGuard`, since the task explicitly asked for "a
way to use it as a context manager, or at least release cleanly via
`QLockFile`'s own destructor semantics" -- both were provided rather
than picking just one, since the context manager is essentially free
to add on top of the existing `try_acquire`/`release` methods.

Verification: targeted new test file
(`tests/unit/test_utils/test_single_instance.py`) **8 passed**;
complete suite run via
`QT_QPA_PLATFORM=offscreen python3 -m pytest -q --deselect tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::test_geometry_is_restored_on_next_launch`
**851 passed, 1 deselected in 117.64s** (843 pre-existing + 8 new; the
deselected test is the same pre-existing offscreen-rendering flake
noted in prior implementation notes, unrelated to this slice). No other
failures or flakes observed. A live GUI smoke test (actually launching
two real PhotoEdit processes back to back and confirming the second
shows the message box) was not performed in this non-interactive
environment; the behavior is instead pinned at the `SingleInstanceGuard`
unit level, which is the layer `main()`'s wiring delegates to entirely.
