# 2026-05-07 -- Dock state and image adjustment persistence

Related plan: [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) sections 4, 5.1, 6 ; [PRODUCT_ROADMAP.md](../PRODUCT_ROADMAP.md) app-level persistence and Phase K session-persistence foundation

## 1. Problem and goal

Two persistence gaps are still visible in daily use:

- The left and right dock panels do not reopen with the same widths and
  visibility state from the previous session.
- Per-image edits are lost after closing and reopening the app.

The goal of this slice is to persist the professional-shell layout state and a
small durable adjustment payload per library image, then restore both on the
next launch.

Non-goals:

- Full project files, batch edit copy/paste, crash recovery, or undo-history
  persistence.
- Persisting edits for files that were never added to the persistent library.
- Adding new adjustment controls beyond the existing light/color sliders.

## 2. Current behavior

- `SettingsService` persists only last open dir, last export dir, and main
  window geometry.
- `MainWindow` restores geometry but not `QMainWindow.saveState()`, so dock
  sizes and visibility return to defaults each launch.
- `LibraryCatalogService` persists library entries and thumbnail metadata, but
  not edit payloads.
- `ImageController` resets its adjustment params whenever a new image loads.
- `MainWindow._on_image_loaded()` currently resets the tools panel on load,
  which would wipe any restored adjustment state.

## 3. Proposed design

- Extend `SettingsService` with a typed `window/state` blob and a lightweight
  `session/current_image_path` value for the last successfully opened image.
- Give `library_dock` and `tools_dock` stable `objectName`s so
  `QMainWindow.saveState()` can round-trip widths and visibility.
- Add an additive `adjustment_state` payload to each `LibraryEntry`. The payload
  will be a small versioned dict containing the current slider values.
- Extend `LibraryCatalogService` with explicit getter/setter methods for entry
  adjustment state.
- Extend `LibraryController` with thin methods for retrieving and persisting the
  current image's adjustment payload through the catalog service.
- Extend `ToolsPanel` with a programmatic `set_adjustments()` path that can
  update sliders without echoing transient signals unless explicitly requested.
- Extend `ImageController` with helpers to normalize, expose, and restore
  adjustment state without adding it to undo history.
- Update `MainWindow` so image-load restore flow is:
  1. capture pending adjustment payload for the file being opened,
  2. load the image,
  3. enable tools,
  4. apply the saved slider state to the panel,
  5. ask `ImageController` to restore the saved adjustments onto the image,
  6. persist the current image path for the next launch.
- Add a small idle timer in `MainWindow` so frequent slider drags coalesce into
  fewer catalog writes, with a final flush on close.
- On startup, restore the saved dock state and, if the last image path still
  exists, reopen that image and restore its persisted adjustments.

## 4. API and data contracts

- New `SettingsService` keys:
  - `window/state`
  - `session/current_image_path`
- `LibraryEntry` gains optional `adjustment_state`.
- `adjustment_state` format:
  - `version: 1`
  - `values: {exposure, contrast, brightness, saturation, vibrance}`
- Backward compatibility:
  - missing `adjustment_state` means all-zero adjustments;
  - unknown future fields are ignored;
  - existing catalog files load without migration.

## 5. Nuances and failure modes

- `QMainWindow.saveState()` only works reliably when dock widgets have stable
  `objectName`s.
- Restoring edits must not re-add undo history from a previous session.
- Restoring a zeroed adjustment payload should show the original image and keep
  the sliders at zero.
- A missing last-opened image path should fail quietly and not block startup.
- Frequent slider movement must not write the catalog JSON on every tick.
- The same file can exist in multiple libraries, so adjustment persistence must
  be stored per entry in the owning library, not globally by file path.

## 6. UI and reskin impact

- No visual redesign.
- The only user-visible UI changes are that dock sizes/visibility now restore
  and edited images reopen with their previous slider values.
- Business logic stays in controllers/services; views only expose plain state
  setters/signals.

## 7. Dependencies

- Builds on the existing `SettingsService`, persistent library catalog, and
  library controller flow.
- Introduces the first small K0-style adjustment payload without attempting a
  full project-file system.

## 8. Test plan

- Settings-service tests for window-state and current-image-path round-trips.
- Library-catalog tests for persisting/reloading entry adjustment state.
- Image-controller tests for normalizing and restoring saved adjustment state.
- Main-window UI tests for:
  - dock layout restore across reopen,
  - reopening the last image with saved slider values.
- Keep existing library and main-window persistence tests green.

## 9. Rollout and rollback

- Immediate rollout; additive persistence only.
- Rollback can ignore the new settings key and adjustment payload field without
  corrupting existing catalogs.

## 10. Acceptance criteria

- Left/right dock widths and visibility restore after close and reopen.
- Saved slider values for a library image are restored after reopen.
- Reopened edited images display their restored adjustments, not the original.
- Existing catalogs and settings files continue to load safely.
- Focused service/controller/UI tests pass.

Plan approved -- implementation allowed: **Approved by user request in chat (2026-05-07)**

## 11. Implementation summary

Landed:

- Extended `SettingsService` with typed persistence for `QMainWindow.saveState()`
  and the last-opened image path.
- Added stable dock `objectName`s and full dock-state restore/save in
  `MainWindow`, so left/right panel widths and visibility now reopen correctly.
- Added additive per-entry `adjustment_state` payload support to the persistent
  library catalog.
- Added programmatic adjustment-state restore paths in `ToolsPanel`,
  `ImageController`, `LibraryController`, and `MainWindow`.
- Replaced the old unconditional slider reset on image load with a restore-aware
  flow that reapplies saved slider values and image adjustments after load.
- Added coalesced adjustment-state persistence while editing and a final flush
  on close.
- Added focused service, controller, and UI regression tests for dock-state and
  session-adjustment persistence.
