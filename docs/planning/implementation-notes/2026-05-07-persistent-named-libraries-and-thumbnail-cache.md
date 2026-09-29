# 2026-05-07 -- Persistent named libraries and disk thumbnail cache

Related plan: [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) sections 4, 5.1, 6, 7 ; [PRODUCT_ROADMAP.md](../PRODUCT_ROADMAP.md) Phase A (library DAM) and Phase K (session persistence foundation)

## 1. Problem and goal

The current library panel is transient. It keeps only an in-memory list of file
paths inside `LibraryView`, so imported images disappear on restart and there is
no concept of multiple named libraries.

Goal for this slice:

- Introduce persistent, app-managed named libraries.
- Persist library membership across launches without copying original files.
- Restore the last-selected library on startup.
- Make library reopen fast by using a disk-backed thumbnail cache.
- Keep missing files visible in the library instead of silently dropping them.

Non-goals for this slice:

- File copying into managed storage.
- Folder watching or auto-sync.
- Search, sort/filter, ratings, pick/reject, keywords, or collections.
- Per-image edit-state persistence.
- Relink UI for missing files.
- Cache settings/preferences UI.

## 2. Current behavior

- `src/views/library_view.py` owns the library state directly as
  `self._image_paths: List[str]`.
- Library contents exist only for the current process; there is no on-disk
  catalog.
- Import uses a background thumbnail worker, but every restart requires the
  library to be rebuilt manually.
- `src/services/settings_service.py` persists only last open/export directories
  and window geometry; it is intentionally not a project/catalog store.
- `src/models/project_model.py` exists but only tracks a flat list of images and
  current index. It is not used as a durable multi-library catalog.

Known edge cases today:

- Duplicate imports are prevented only within the live widget session.
- Missing files vanish because the library is not persisted at all.
- Library load time scales with repeated thumbnail generation because no disk
  thumbnail cache exists.

## 3. Proposed design

Add two services and refactor the library UI so view code stays thin:

- `LibraryCatalogService`
  - Owns catalog JSON load/save.
  - Owns named-library CRUD.
  - Owns per-library entry records and missing/available status refresh.
  - Creates a default first library on first launch.
- `LibraryThumbnailCacheService`
  - Owns disk cache lookup/write/remove.
  - Stores thumbnails in app cache storage, separate from catalog JSON.
  - Validates cache entries against source file metadata.

UI/data flow:

1. Main window creates the catalog and thumbnail-cache services and injects them
   into `LibraryView`.
2. On startup, `LibraryView` asks the catalog service for all libraries and the
   current library id.
3. The sidebar is populated immediately from catalog metadata.
4. The current library grid is populated from persisted entry records.
5. Each entry first attempts to render from disk thumbnail cache.
6. Cache misses or stale entries are queued to the existing background thumbnail
   worker, which regenerates and stores fresh thumbnails.
7. Import adds entries to the currently selected library only, persists the
   updated catalog, then queues background thumbnail work.
8. Switching libraries swaps the grid contents without re-reading unrelated
   libraries.
9. Removing a library deletes only its catalog record and any thumbnail cache
   files no longer referenced by other libraries.

## 4. API and data contracts

New catalog JSON file:

- Stored under `QStandardPaths.AppDataLocation`.
- Versioned from day one with top-level `schema_version`.
- Additive compatibility rule: future readers may add fields; existing fields
  are not silently renamed.

Top-level JSON shape:

- `schema_version: int`
- `current_library_id: str`
- `libraries: list[dict]`

Library record fields:

- `id: str`
- `name: str`
- `created_at: str`
- `updated_at: str`
- `entries: list[dict]`

Entry record fields:

- `path: str`
- `filename: str`
- `added_at: str`
- `last_seen_mtime_ns: int | null`
- `last_seen_size: int | null`
- `status: "available" | "missing"`
- `thumbnail_cache_key: str | null`

New service APIs:

- `list_libraries()`
- `create_library(name: str)`
- `remove_library(library_id: str)`
- `get_current_library_id()`
- `set_current_library(library_id: str)`
- `list_entries(library_id: str)`
- `add_entries(library_id: str, paths: list[str])`
- `refresh_entry_status(library_id: str, path: str)`
- `mark_entry_missing(library_id: str, path: str)`

New/changed view signals:

- `library_selection_changed(str)`
- `create_library_requested()`
- `remove_library_requested(str)`
- `import_requested()`
- existing `image_selected(str)` remains path-based.

## 5. Nuances and failure modes

- Duplicate imports are no-op within one library, keyed by normalized path.
- The same file may appear in multiple libraries.
- Missing files are retained with `status="missing"` and a placeholder thumbnail;
  no auto-removal happens.
- Corrupt or unreadable cache files are treated as cache misses and regenerated.
- If the catalog JSON is missing on first run, the service creates a default
  library and persists it immediately.
- If the catalog JSON is unreadable/corrupt, the service logs an error and falls
  back to a new default empty catalog rather than crashing the UI.
- Library removal never deletes original image files.
- Cache cleanup removes only thumbnail files no longer referenced by any library.
- Background thumbnail work must not block library switching.
- Thumbnail rebuild must use preview/decode paths only; no full image decode is
  allowed during library restore.

## 6. UI and reskin impact

- `LibraryView` gains a sidebar manager for named libraries plus create/remove
  controls.
- The existing grid stays as the entry display area for the selected library.
- Business logic remains outside the view:
  - persistence stays in services,
  - cache validity stays in services,
  - the view emits signals and renders plain data/state.
- Styling remains local to the library panel; no image-processing or disk I/O
  logic moves into widgets.

## 7. Dependencies

- Depends on the existing async thumbnail-import pattern already present in
  `LibraryView`.
- Reuses `ImageService.load_preview_thumbnail()` for cache regeneration.
- Does not depend on K0 edit-state schema; this slice persists only library
  membership/status and cache references.
- Unblocks later slices for search/filter, collections, relink UI, and session
  persistence of richer per-image metadata.

## 8. Test plan

Automated:

- Unit tests for `LibraryCatalogService`:
  - first-run default library creation,
  - persist/reload multiple libraries,
  - current library restore,
  - duplicate import no-op within one library,
  - same file allowed in different libraries,
  - missing-file retention across reload,
  - library removal leaves original files untouched.
- Unit tests for `LibraryThumbnailCacheService`:
  - cache write + read hit,
  - stale cache invalidation on source metadata change,
  - cache miss behavior,
  - missing-file skip behavior.
- Updated `LibraryView` tests:
  - sidebar manager shows libraries,
  - switching libraries swaps grid contents,
  - import applies only to current library,
  - missing entry renders placeholder state.
- Updated `MainWindow` / UI tests:
  - startup restores selected library,
  - imported images persist across relaunch,
  - removing a library updates sidebar/grid,
  - selection still loads images asynchronously.

Manual smoke:

1. Launch app with no existing app-data catalog and verify a default library is
   created.
2. Create a second library and switch between libraries.
3. Import different images into each library.
4. Restart the app and verify both libraries and entries persist.
5. Confirm cached thumbnails appear quickly on reopen.
6. Rename or disconnect one imported source file, restart, and verify the entry
   remains visible as missing.
7. Remove one library and verify source image files still exist on disk.

## 9. Rollout and rollback

- Rollout is always-on for this slice; no feature flag is added.
- Rollback path:
  - revert the catalog/cache services and library view wiring,
  - the old behavior falls back to transient in-memory libraries.
- Cache directory is disposable; deleting it only forces thumbnail regeneration.
- Catalog JSON is the durable state; if rollback is needed after users create
  libraries, the old UI simply will not surface that data until the feature
  returns.

## 10. Acceptance criteria

- A default named library exists automatically on first launch.
- Users can create, switch, and remove named libraries from the sidebar.
- Imported images persist in their library across app restarts.
- The same file can exist in multiple libraries.
- Duplicate import into the same library does not create duplicates.
- Library restore prefers disk thumbnail cache and regenerates only missing/stale
  entries in the background.
- Missing files remain visible and marked missing after restart.
- Removing a library never deletes original source files.
- Automated tests for the new services and updated UI behavior pass.

Plan approved -- implementation allowed: **Approved by user request in chat (2026-05-07)**

## 11. Implementation summary

Landed:

- Added `LibraryCatalogService` for persistent named-library JSON storage with
  schema versioning, current-library restore, duplicate suppression per library,
  and missing-file retention.
- Added `LibraryThumbnailCacheService` for disk-backed thumbnail storage under
  cache location, keyed by normalized path plus file metadata.
- Refactored `LibraryView` into a sidebar + grid layout backed by the catalog
  service instead of in-memory `self._image_paths`.
- Restored library/sidebar state on startup, cached thumbnails on reopen, and
  background thumbnail regeneration for cache misses.
- Added missing-entry placeholder rendering and guarded selection so missing
  items do not trigger image load.
- Wired `MainWindow` to inject catalog/cache services and clean up library
  thumbnail threads on close.
- Added focused unit and UI coverage for catalog persistence, cache behavior,
  library switching, restore on relaunch, and geometry persistence with the new
  service injection path.

Deferred as planned:

- Relink UI for missing files.
- Search/sort/filter, ratings, keywords, collections.
- Copying originals into app-managed storage.
- Folder watching or auto-sync.
