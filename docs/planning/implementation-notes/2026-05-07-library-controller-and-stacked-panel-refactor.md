# 2026-05-07 -- Library controller and stacked library panel refactor

Related plan: [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) sections 4, 5.1, 7 ; [ARCHITECTURE.md](../../ARCHITECTURE.md) MVC with service layer ; follow-up to [2026-05-07-persistent-named-libraries-and-thumbnail-cache.md](2026-05-07-persistent-named-libraries-and-thumbnail-cache.md)

## 1. Problem and goal

The first persistent-library slice landed the functional behavior, but two
problems remain:

- `LibraryView` still owns too much orchestration and talks directly to
  persistence/cache services, which is not the intended thin-view MVC shape.
- The library UI uses a side-by-side "library list + grid" layout inside the
  left dock, which feels like a second explorer running in parallel with the
  main library panel.

Goal for this slice:

- Introduce `LibraryController` as the orchestration layer between
  `LibraryView` and the catalog/cache services.
- Refactor `LibraryView` into one vertically stacked library dock with a
  collapsible "Libraries" section above the existing image grid.
- Preserve the existing persistent-library behavior and tests.

Non-goals:

- No change to catalog JSON schema.
- No new end-user features beyond layout and architecture cleanup.
- No relink workflow, search/filter, or metadata management.

## 2. Current behavior

- `src/views/library_view.py` owns startup restore, library CRUD orchestration,
  entry loading, cache lookup, placeholder creation, and thumbnail-thread
  lifecycle.
- `src/views/main_window.py` injects services directly into `LibraryView`.
- The left dock contains a `QSplitter` with a sidebar list of libraries next to
  the image grid.
- There is no `src/controllers/library_controller.py` yet even though the
  architecture doc anticipates it.

## 3. Proposed design

- Add `LibraryController` as a `QObject` that owns:
  - current library selection,
  - library CRUD orchestration,
  - entry loading/refresh,
  - thumbnail-cache lookup,
  - background thumbnail worker lifecycle,
  - cleanup on shutdown.
- Keep `LibraryCatalogService` and `LibraryThumbnailCacheService` unchanged as
  the storage layer.
- Refactor `LibraryView` so it only:
  - renders the library list and image grid,
  - emits user-intent signals,
  - updates item visuals from controller-provided data,
  - owns presentation-only collapsible section state.
- Replace the side-by-side splitter with one vertical layout:
  - header row with import button,
  - collapsible "Libraries" section,
  - image grid,
  - info label.

## 4. API and data contracts

New `LibraryController` public methods:

- `initialize()`
- `select_library(library_id: str)`
- `create_library(name: str)`
- `remove_library(library_id: str)`
- `import_images(paths: list[str])`
- `add_image(path: str)`
- `clear_current_library()`
- `cleanup()`

New `LibraryController` signals:

- `libraries_changed(object, str)` where object is a list of simple library
  payload dicts or records suitable for the view.
- `entries_rebuilt(str, object)` where object is the entry list for the current
  grid render.
- `entry_thumbnail_updated(str, object)` for a single entry thumbnail refresh.
- `thumbnail_batch_started(int)`
- `thumbnail_batch_progress(int, int)`
- `thumbnail_batch_finished()`

New `LibraryView` user-intent signals:

- `library_selected(str)`
- `create_library_requested(str)`
- `remove_library_requested(str)`
- `import_requested()`

Existing `image_selected(str)` remains and still emits only available-file paths.

## 5. Nuances and failure modes

- Controller cleanup must stop thumbnail workers so view teardown and app close
  do not hang.
- View collapse state is presentation only and need not be persisted in this
  slice.
- The controller must ignore thumbnail completions for a library that is no
  longer current when updating the visible grid.
- The grid must keep rendering missing-entry placeholders exactly as before.
- `MainWindow` should inject services into `LibraryController`, not directly into
  `LibraryView`.

## 6. UI and reskin impact

- The left dock remains a single dock named "Library".
- The "Libraries" manager becomes a stacked section inside that dock instead of
  a parallel sidebar.
- The section should visually read like the existing panel sections in
  `ToolsPanel`, but be collapsible via a header toggle.
- Business logic moves further out of the view, improving future reskin safety
  per workflow section 5.1.

## 7. Dependencies

- Depends on the already-landed persistent library services.
- Does not require migration of existing catalog files.
- Unblocks future library UI work because the controller boundary will exist.

## 8. Test plan

Automated:

- New controller unit tests for:
  - startup library restore,
  - select/create/remove library flow,
  - import flow updating catalog and entries,
  - cleanup stopping worker thread.
- Updated library view tests:
  - stacked section exists,
  - section toggles visibility,
  - view renders controller-provided libraries and entries,
  - user-intent signals emit correct payloads.
- Updated main-window/UI tests:
  - library switching still updates the grid,
  - startup still restores current library,
  - import and selection continue to work with controller wiring.

Manual smoke:

1. Open the app and confirm the library dock has one stacked panel, not a
   side-by-side explorer.
2. Collapse and expand the "Libraries" section.
3. Create/remove/switch libraries.
4. Import images and restart the app.
5. Confirm thumbnail progress, missing-file placeholders, and selection still
   work.

## 9. Rollout and rollback

- Rollout is immediate and always-on.
- Rollback reverts the controller + view layout refactor only; the persistent
  catalog/cache services can remain if needed.
- No data migration is required, so rollback risk is primarily UI/runtime
  behavior rather than stored-state compatibility.

## 10. Acceptance criteria

- `LibraryController` exists and owns library orchestration instead of
  `LibraryView`.
- `LibraryView` no longer talks directly to catalog/cache services.
- The library dock uses one stacked layout with a collapsible libraries section.
- Existing persistent-library behavior remains intact.
- Focused tests for controller, view, and main-window wiring pass.

Plan approved -- implementation allowed: **Approved by user request in chat (2026-05-07)**

## 11. Implementation summary

Landed:

- Added `LibraryController` as the orchestration layer for library selection,
  CRUD, entry rebuilds, thumbnail-cache lookup, and worker cleanup.
- Refactored `LibraryView` into a thin presentation widget with:
  - one stacked library dock layout,
  - a collapsible `Libraries` section,
  - a separate photo grid below it,
  - user-intent signals instead of direct service calls.
- Moved dialog prompts for create/remove library into `MainWindow`, keeping
  controller logic UI-agnostic and view logic thin.
- Rewired `MainWindow` to inject services into `LibraryController` and connect
  controller output signals back into the view/status bar.
- Added focused controller tests and updated view/UI tests for the new
  controller boundary and stacked panel layout.

Deferred as planned:

- Persisting the collapsed/expanded state of the `Libraries` section.
- Reusing the collapsible section widget in `ToolsPanel` itself.
