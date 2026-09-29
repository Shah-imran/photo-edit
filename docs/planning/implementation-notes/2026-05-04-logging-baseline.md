# 2026-05-04 -- Logging baseline (L1)

Slice owner: PhotoEdit team
Status: **DONE -- merged and smoked (2026-05-04)**
Related plan: [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) section 7 (logging and traceability) ; [PRODUCT_ROADMAP.md](../PRODUCT_ROADMAP.md) Part 1 (cross-cutting concerns)

---

## 1. Problem and goal

**Problem.** The application currently has no centralized logging configuration. Module-level loggers do exist (`src/views/main_window.py`, `src/services/settings_service.py`) and call `logger.info/warning/exception(...)`, but the **root logger has no handlers**, so:

- INFO and WARNING messages are silently dropped (Python defaults silence anything below WARNING; even WARNING goes to bare `stderr` with no formatter).
- There is no persistent log file -- after the user closes the app, every diagnostic is lost.
- Three places in `src/` still use `print(...)` for error reporting (export failure, thumbnail-load failure, async processing error), which are invisible when the app is launched from a `.exe` or pythonw.

**Goal of this slice.** Add a single, well-tested logging configuration helper that:

1. Sends logs to a **rotating file** in the OS-native app data folder (`%APPDATA%\PhotoEdit\logs\photoedit.log` on Windows; equivalents on macOS/Linux).
2. Mirrors logs to stderr at a configurable level for development.
3. Is **idempotent** (safe to call from tests).
4. Is wired into `src/main.py` exactly once at startup.

Then, replace the three remaining `print(...)` error sites with proper `logger.exception/error/warning` calls so the new file handler immediately catches real failures.

**Non-goals (deferred, will NOT be done in this slice):**

- Correlation IDs / per-request trace IDs (mentioned in workflow section 7; hold for the async/processing slice when we revisit `ProcessingWorker`).
- A user-visible log viewer or "Help -> Open Log Folder" menu (small UI follow-up; not blocking).
- Crash reporters / Sentry / opt-in telemetry (separate slice, see roadmap).
- Auditing / restructuring every existing log call's level or wording (we'll touch only the three `print` sites).
- Per-module log level configuration via a config file (overkill until we have a real need; today the kwargs are enough).

---

## 2. Current behavior

| Concern | Current state | File / line |
|---------|---------------|-------------|
| Root logger configuration | none -- no handlers attached | _N/A_ |
| Log file | none | _N/A_ |
| Stderr console output | only Python's default lastResort handler at WARNING | _N/A_ |
| Module loggers using stdlib `logging` | `MainWindow`, `SettingsService` | [`main_window.py:21`](../../../src/views/main_window.py), [`settings_service.py:23`](../../../src/services/settings_service.py) |
| `print()` in production code | 3 sites | see below |
| `print` -- export failure | `print(f"Export failed: {e}")` after `Exception` swallow | [`export_service.py:63`](../../../src/services/export_service.py) |
| `print` -- thumbnail load failure | `print(f"Failed to load thumbnail for {file_path}: {e}")` | [`library_view.py:204`](../../../src/views/library_view.py) |
| `print` -- async processing error | `print(f"Processing error (request {request_id}): {error}")` | [`image_controller.py:419`](../../../src/controllers/image_controller.py) |
| Application identity | `app.setApplicationName("PhotoEdit")` and `app.setOrganizationName("PhotoEdit")` already set | [`main.py:13-14`](../../../src/main.py) -- prereq for `QStandardPaths.AppDataLocation`, already correct |
| Existing test suite | 225 passing; no log-related fixtures or assertions | `tests/` |

---

## 3. Proposed design

### 3.1 New module: `src/utils/logging_config.py`

A single public function:

```python
def configure_logging(
    log_dir: Optional[Path] = None,
    file_level: int = logging.INFO,
    console_level: int = logging.INFO,
    enable_console: bool = True,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> Path:
    """Attach PhotoEdit's standard handlers to the root logger.

    Returns the directory the log file was written into.
    """
```

Behavior:

1. **Resolve `log_dir`.** When `None`:
   - Use `QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation) / "logs"` if a `QApplication` (or `QCoreApplication`) exists.
   - Fall back to a platform-native path computed from environment variables when no Qt app exists yet (this keeps the function unit-testable without a `QApplication`):
     - Windows: `Path(os.environ.get("APPDATA", Path.home())) / "PhotoEdit" / "logs"`.
     - macOS: `Path.home() / "Library" / "Logs" / "PhotoEdit"`.
     - Linux/other: `Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "PhotoEdit" / "logs"`.
2. **Create the directory** if missing (`mkdir(parents=True, exist_ok=True)`).
3. **Remove any previously installed PhotoEdit handlers** (tagged via `handler._photoedit = True`) from the root logger so repeated calls in tests do not accumulate.
4. **Install handlers:**
   - `RotatingFileHandler(log_dir / "photoedit.log", maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")` at `file_level`.
   - When `enable_console=True`, `StreamHandler(sys.stderr)` at `console_level`.
   - Both use the formatter `"%(asctime)s [%(levelname)s] %(name)s: %(message)s"` with `datefmt="%Y-%m-%d %H:%M:%S"`.
   - Tag both handlers with `_photoedit = True` for idempotent re-config.
5. **Set `root.setLevel(min(file_level, console_level))`** so neither handler drops messages it would otherwise want.
6. Return the resolved `log_dir` (so tests and `main.py` can log "writing logs to ...").

### 3.2 Wire-up in `src/main.py`

```python
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PhotoEdit")
    app.setOrganizationName("PhotoEdit")

    log_dir = configure_logging()  # uses QStandardPaths now that the app exists
    logging.getLogger(__name__).info("PhotoEdit starting; logs at %s", log_dir)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
```

The call sits **after** the org/app names are set (so `QStandardPaths.AppDataLocation` resolves correctly) and **before** `MainWindow()` is constructed (so any startup log lines are captured).

### 3.3 Replace the three `print(...)` calls

| File | Old | New |
|------|-----|-----|
| `src/services/export_service.py` | `print(f"Export failed: {e}")` | `logger.exception("Export failed for %s", path)` (use `logger.exception` so traceback is captured; replace the `except Exception as e:` body's print) |
| `src/views/library_view.py` | `print(f"Failed to load thumbnail for {file_path}: {e}")` | `logger.warning("Failed to load thumbnail for %s: %s", file_path, e)` (warning, not exception -- corrupt thumbnails are not bug-level) |
| `src/controllers/image_controller.py` | `print(f"Processing error (request {request_id}): {error}")` | `logger.error("Processing error (request %s): %s", request_id, error)` |

Each module gets a `logger = logging.getLogger(__name__)` at module top if it does not already have one. The two existing modules (`main_window`, `settings_service`) already do.

### 3.4 What does NOT change

- Module-level loggers are still created with `logging.getLogger(__name__)`. No new wrapper.
- No global "log helper" facade; we use stdlib `logging` directly so future maintainers do not need to learn a project-specific API.
- `pytest`'s `caplog` fixture continues to work because we attach to the root logger and let propagation handle it.

---

## 4. API and data contracts

| Surface | Shape | Notes |
|---------|-------|-------|
| `configure_logging(log_dir=None, file_level=INFO, console_level=INFO, enable_console=True, max_bytes=5MB, backup_count=5) -> Path` | Public; returns the resolved log directory | Idempotent; safe to call multiple times |
| Log file path | `<log_dir>/photoedit.log` (rotates to `photoedit.log.1`, `.2`, ...) | UTF-8 |
| Log line format | `2026-05-04 10:23:45 [INFO] src.services.settings_service: Stored paths/last_open_dir = C:/Users/...` | Stable; tests can assert on prefix |
| Module logger names | `logging.getLogger(__name__)` -- always the dotted module path | Already a project convention |
| Handler tagging | Custom attribute `_photoedit = True` on every handler we install | Internal; not part of public API |

No persisted state (no `QSettings` keys), no JSON, no migrations. Reverting this slice is a pure code-only revert.

---

## 5. Nuances and failure modes

- **Function called before `QApplication`**: tests and scripts may import the helper without a Qt app. We must not require Qt -- hence the env-var fallback in 3.1 step 1. We will detect "is there a Qt app" by checking `QCoreApplication.instance() is not None`; if not, take the env-var path.
- **Read-only or unwritable `log_dir`**: catch `OSError` from `mkdir` / `RotatingFileHandler` and fall back to **stderr-only** logging with a single `logger.error(...)` line explaining the fallback. Never crash startup over this.
- **Repeated calls (test isolation)**: removing only handlers tagged `_photoedit` prevents us from stripping handlers added by `pytest` or `pytest-qt`.
- **Worker thread reentrancy**: stdlib `RotatingFileHandler` uses an internal lock; safe across threads. We will not introduce a `QueueHandler` in this slice (would be needed only if we hit measurable contention; not the case yet).
- **Exception traceback on background threads**: `logger.exception(...)` only captures `sys.exc_info()` of the calling thread. The image-controller `print` we are replacing is already inside an `error_occurred` slot, so this is fine. We will use `logger.error(..., exc_info=False)` there because the worker already serialized the error to a string.
- **PII / privacy**: file paths can contain user names. We log them at INFO and below only; nothing that runs at DEBUG today touches paths beyond what the user already sees in the UI.
- **High-DPI / locale**: pure logging; no UI; not affected.
- **Pyinstaller / frozen builds**: `QStandardPaths` continues to work; the env-var fallback also works. No `__file__` lookups used.
- **Order of operations in `main.py`**: log config must come **after** `setApplicationName/setOrganizationName` (so `QStandardPaths` resolves correctly) and **before** `MainWindow()` (so first-launch INFO lines from `SettingsService` and the window are captured).

---

## 6. UI and reskin impact

None. There is no widget, no QSS, no view change. The slice strictly adds module-level infrastructure and replaces three `print` sites. UI-flexibility constraints from workflow section 5.1 are unaffected.

---

## 7. Dependencies

- **Blocked by:** nothing. Settings slice (DONE) demonstrated the workflow.
- **Unblocks:** every future slice gets durable diagnostics for free. Specifically:
  - **R1 (RAW load)** -- decoder failures and codec selection will need traceable INFO/ERROR.
  - **K0 (project file)** -- schema-migration and corrupt-file paths will need traceable WARNING/ERROR.
- **External libraries:** none added; `Pipfile` is unchanged. Uses stdlib `logging` and `logging.handlers.RotatingFileHandler`, plus `PyQt6.QtCore.QStandardPaths` (already a dep).
- **Feature flag:** none required.

---

## 8. Test plan

### 8.1 New unit tests: `tests/unit/test_utils/test_logging_config.py`

| Case | Assertion |
|------|-----------|
| First call with explicit `log_dir` creates the directory and a `photoedit.log` file | `(log_dir / "photoedit.log").exists()` after a single INFO log |
| Logged INFO message lands in the file with the standard format | file contents match `r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[INFO\] test: hello world"` |
| Logged DEBUG message **does not** land at default file_level=INFO | substring "debug-line" not in file |
| `console_level=WARNING` filters INFO from stderr while file still records INFO | use `capsys`; INFO not on stderr, INFO present in file |
| Calling `configure_logging` twice with different dirs only writes to the **second** dir | first dir's file does not grow after the second call |
| Calling `configure_logging` twice does **not** double-add handlers (count of tagged handlers stays at 2) | `len([h for h in logging.getLogger().handlers if getattr(h,"_photoedit",False)]) == 2` |
| Rotation: write past `max_bytes=1024, backup_count=2` | `photoedit.log.1` exists; `photoedit.log` is current |
| Unwritable `log_dir` (simulated by patching `Path.mkdir` to raise `OSError`) falls back to stderr-only | no file handler attached; one ERROR line on stderr |
| Module loggers (e.g. `logging.getLogger("src.foo.bar")`) propagate to the configured handler | message present in file |

Tests will use the explicit `log_dir=tmp_path` form to stay isolated from the user's `%APPDATA%`. A teardown will remove our tagged handlers from the root logger so test ordering does not matter.

### 8.2 Updates to existing tests

- No change required for the 225 existing tests. We will run the full suite to confirm nothing depends on log silence (`caplog` users still work because we attach to the root, which propagation reaches).
- `tests/unit/test_services/test_settings_service.py` already uses `caplog.at_level("INFO", logger="src.services.settings_service")`; this continues to work because `caplog` adds its own propagating handler on top of ours.

### 8.3 Manual smoke checklist

1. `pipenv run python -m src.main`. App launches normally.
2. Locate the log directory:
   - Windows: `%APPDATA%\PhotoEdit\logs\photoedit.log` opens in Notepad.
3. The first line of the file matches `... [INFO] src.main: PhotoEdit starting; logs at <path>`.
4. Open an image, move a slider, close the app. The file gains lines from `SettingsService` (geometry save, paths) at INFO.
5. Trigger a thumbnail failure (e.g., feed `LibraryView.add_image` a corrupted JPEG manually via the Python REPL or rename a real image to `.jpg`). A WARNING line lands in the log instead of a `print` to stderr.
6. Trigger an export to a read-only directory; an ERROR line with traceback lands in the log.
7. Relaunch the app; new lines append to the same file (no overwrite).
8. Inflate the file artificially to >5 MB (or temporarily set `max_bytes=1024` via a one-off edit); confirm `photoedit.log.1` is created.
9. Revert the `max_bytes` edit before merge.

---

## 9. Rollout and rollback

- **Rollout:** single PR; effect is invisible to end users until they ask "why isn't this working" and we ask for the log file.
- **Rollback:** revert the PR. The three `logger.*` calls revert to `print` and the helper file disappears. No on-disk state to clean up other than the user's existing `photoedit.log` files (which are harmless).
- **Feature flag:** not required; logging is always on.
- **Privacy:** the new INFO-level lines from `SettingsService` already log file paths; this slice does not introduce any **new** PII surfaces, only persists existing log lines to disk. We will revisit when adding telemetry.

---

## 10. Acceptance criteria

All must be true before merge:

- [x] `src/utils/logging_config.py` exists with the API in section 3.1.
- [x] `configure_logging` is called exactly once from `src/main.py`, after the app/org name setup, before `MainWindow()`.
- [x] All three `print(...)` calls in `src/` are replaced with `logger.*` calls; `rg "print\(" src/` returns no production-code matches.
- [x] The new unit tests in 8.1 pass (10/10).
- [x] Full existing suite (`pipenv run pytest --ignore=tests/performance`) still passes -- 235/235 (was 225 before this slice; +10 new tests).
- [x] Headless smoke and full manual smoke (8.3 steps 1-7) executed by project owner on Windows on 2026-05-04 -- all pass.
- [x] No new dependency added to `Pipfile`.
- [x] Implementation note has a final **Implementation summary** subsection added in the same PR or immediate follow-up commit (per workflow section 4.3).

---

## 11. Approval

> **Plan approved -- implementation allowed**: yes
> Reviewer: project owner (chat approval)
> Date: 2026-05-04

---

## 12. Implementation summary (filled after merge)

**Status:** implemented, tested, and manually smoked (2026-05-04). Slice closed.

**Files added:**

- `src/utils/logging_config.py` -- `configure_logging(...)` helper. Stdlib `logging` + `logging.handlers.RotatingFileHandler` only; `QStandardPaths` is used when a Qt app exists, with a per-OS env-var fallback otherwise. Handlers are tagged `_photoedit=True` for idempotent re-config.
- `tests/unit/test_utils/__init__.py` -- empty package marker.
- `tests/unit/test_utils/test_logging_config.py` -- 10 unit tests covering: directory creation, INFO format and content, DEBUG suppression below default level, module-logger propagation, independent file/console levels, idempotency (handler count stays at 2 across calls), per-call dir switching, rotation backup creation, OSError fallback to stderr-only, and the `enable_console=False` toggle.

**Files modified:**

- `src/main.py` -- imports `configure_logging`, calls it after `setApplicationName/setOrganizationName` and before `MainWindow()`, then logs `"PhotoEdit starting; logs at <path>"` at INFO from the `src.main` logger.
- `src/services/export_service.py` -- module-level `logger`; `print(f"Export failed: {e}")` -> `logger.exception("Export failed for %s", output_path)`.
- `src/views/library_view.py` -- module-level `logger`; `print(f"Failed to load thumbnail for ...")` -> `logger.warning("Failed to load thumbnail for %s: %s", file_path, e)`.
- `src/controllers/image_controller.py` -- module-level `logger`; `print(f"Processing error ...")` -> `logger.error("Processing error (request %s): %s", request_id, error)`.

**Test results:**

- New logging unit tests: 10/10 pass.
- Full suite (excluding `tests/performance`): **235 passed** (was 225; +10 new tests as planned).
- No lints.
- Headless smoke: a `QApplication("PhotoEdit", "PhotoEdit") + configure_logging()` round-trip resolves to `C:\Users\<user>\AppData\Roaming\PhotoEdit\PhotoEdit\logs\photoedit.log`, creates the file, and writes a correctly formatted INFO line.
- Manual smoke (Windows, 2026-05-04, project owner): all 7 steps in section 8.3 pass -- log file created at the expected path, first line records the startup INFO, replaced `print` sites land in the file at the expected levels, rotation produces `.1` backup once `max_bytes` is exceeded.

**Decisions and notes:**

- Chose to attach the **console handler before** attempting the file handler. This means the OSError fallback message ("Could not open log file in ...; using stderr only") actually reaches stderr -- otherwise it would have been emitted while the root logger had no handlers and silently dropped. A test (`test_unwritable_dir_falls_back_to_stderr_only`) pins this behavior.
- Idempotency uses a tag attribute (`_photoedit=True`) on each handler we install, not handler-type matching. This way a re-config only removes our own handlers and leaves any handlers that pytest/`pytest-qt`/`caplog` may have added.
- The function is callable **without** a Qt application (the env-var fallback handles that), which is what makes the unit tests run cleanly without instantiating `QApplication`.
- Used `logger.exception` only at the export site (where a Python traceback is meaningful). The async-processing site already serializes its error to a string and runs in a slot, so a plain `logger.error(..., exc_info=False)` is sufficient.
- Cosmetic note: on Windows the resolved path duplicates `PhotoEdit\PhotoEdit` because we set both `organizationName` and `applicationName` to "PhotoEdit", and `QStandardPaths.AppDataLocation` is `<APPDATA>/<org>/<app>`. This matches where our `QSettings` already lives, so we left it for consistency. If we ever rename the org (e.g., to your company / handle), both will collapse cleanly.

**Follow-ups (not in this slice):**

- "Help -> Open Log Folder" menu item (one `QDesktopServices.openUrl` call once we add a logger-aware menu).
- Per-module DEBUG toggles via env var (e.g., `PHOTOEDIT_LOG=src.controllers=DEBUG`); deferred until we have a real debugging need.
- Correlation IDs / request IDs for the async pipeline -- belongs with the `ProcessingWorker` revisit slice.
- Crash reporter / Sentry / opt-in telemetry -- a separate slice.
