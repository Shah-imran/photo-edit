# 2026-09-29 -- Fix: UI freeze ("Not Responding") while loading/importing library images

Related plan: [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) sections 4, 5.1. Bug fix, not a roadmap phase slice -- reported directly by the user ("still see non responding warning when I clicked on ui while loading images").

## 1. Problem and goal

Clicking anywhere in the UI while the library is (re)populating with images
triggers the OS-level "Not Responding" warning (Windows) -- the Qt event
loop is being starved on the main/UI thread.

**Goal:** eliminate the synchronous, unbounded-cost work that currently
runs on the UI thread every time the library grid is rebuilt (on app
start, library switch, image import, library create/remove/clear), so the
UI stays responsive to clicks during that work regardless of library size.

**Non-goals:**

- The single full-resolution image *open* path (`ImageController.
  load_image_async` / `_ImageLoadWorker`) is already correctly threaded
  (background `QThread`, preview-first). Not touched here.
- Moving `LibraryCatalogService`'s per-entry `path.stat()` refresh
  (`list_entries()`) off the UI thread. A single `stat()` syscall is cheap
  (microseconds on local disk); at plausible library sizes this loop is
  not the dominant cost (see section 2) and `LibraryCatalogService` is not
  designed to be touched from more than one thread (see section 3) -- doing
  so safely would need a bigger locking change than this fix justifies.
  Flagged as a residual risk for very large libraries or network-mounted
  paths (section 5), not fixed here.

## 2. Current behavior

`LibraryController._rebuild_entries_for_current_library()` runs
synchronously on the UI thread on every one of: `initialize()`,
`select_library()`, `create_library()`, `remove_library()`,
`import_images()` (the "Add Photos" / drag-drop / File > Import path),
`clear_current_library()`. It:

1. Calls `catalog_service.list_entries(...)`, which `stat()`s every entry
   (cheap per-call, see section 1's non-goal).
2. For every entry, calls `_entry_payload()`, which -- for any entry that
   already has a valid cached thumbnail -- calls
   `LibraryThumbnailCacheService.load_qimage()`. That function does a
   **synchronous disk read and PNG decode** (`QImage(str(path))`) per
   entry, in a tight Python loop with **no Qt event-loop yield between
   iterations**. For a library of a few hundred images this alone is
   enough to block the UI thread for multiple seconds.
3. Calls `thumbnail_cache_service.remove_orphaned_cache(valid_keys)`,
   which does `self._cache_dir.rglob("*.png")` -- **a full recursive walk
   of the entire thumbnail cache directory** (not scoped to the current
   library; it grows across every library ever populated) plus
   `unlink()` calls for anything orphaned. This is a single long
   synchronous call with nothing to yield mid-way through.

Only the *generation* of thumbnails that are not yet cached was already
threaded (`_ThumbnailBatchWorker` on a `QThread`, wired through
`thumbnail_ready` -> `entry_thumbnail_updated`, each signal delivery
naturally interleaving with the Qt event loop). The freeze is specifically
in the **cache-hit path and the orphan-cleanup path**, both of which ran
synchronously believing they were "just reading a small file" -- true for
one file, false in a loop over an entire library plus a directory walk
over the whole cache.

## 3. Proposed design

- **Stop decoding cached thumbnails synchronously in `_entry_payload()`.**
  Replace the `load_qimage()` call with a cheap `path_for_key(cache_key).
  exists()` check (a single `stat()`, not a decode). Every entry with a
  thumbnail -- cached or not -- now returns `payload["thumbnail"] = None,
  payload["placeholder"] = "loading"` immediately, plus a `_ThumbnailTask`
  for the background worker. `LibraryView._apply_entry_payload()` already
  renders `thumbnail=None` as a generic "Loading" placeholder pixmap and
  `entry_thumbnail_updated` already patches it in later -- this mechanism
  was already generic, just never used for the cache-hit case.
- **Give `_ThumbnailTask` a `cached: bool` flag.** In
  `_ThumbnailBatchWorker.run()`, a `cached=True` task skips
  `ImageService.load_preview_thumbnail()`/`write_thumbnail()` entirely (the
  PNG already exists) and goes straight to emitting `thumbnail_ready`.
  `_on_thumbnail_ready()` (already, unchanged) re-reads the PNG via
  `QImage(path_for_key(cache_key))` on the UI thread -- but as **one
  decode per queued signal delivery**, which the Qt event loop interleaves
  with input/paint processing between each one, not as N decodes back to
  back with no yield. That interleaving is the actual fix; the tight
  synchronous loop is what a single long block looked like.
- **Move `remove_orphaned_cache()` off the UI thread.** New
  `_OrphanCacheCleanupWorker(QObject)` + a short-lived `QThread`, following
  the exact same lifecycle pattern `_ThumbnailBatchWorker` already
  establishes (`moveToThread`, `started.connect(run)`, `finished` tears
  the thread down). Fire-and-forget from the controller's perspective --
  it only deletes files, touches no shared mutable state
  (`LibraryThumbnailCacheService` holds just a `Path`), and does not
  write back into `LibraryCatalogService`, so it needs no synchronization
  with the UI thread beyond the `valid_keys` set already computed
  cheaply (in-memory) before dispatch.
- **Why not also move `list_entries()`'s stat loop off-thread:**
  `LibraryCatalogService` is an in-memory dict backed by a JSON file with
  no locking; today it is only ever touched from the UI thread. Moving its
  stat-refresh to a worker thread would mean a second thread mutating
  `LibraryEntry` objects and triggering `_save_catalog()` concurrently
  with UI-thread reads (e.g. `get_entry_adjustment_state` while an image
  is mid-edit) -- a real correctness risk for a fix whose actual measured
  cost (a `stat()` per file) is much smaller than the PNG-decode loop and
  the directory walk this fix removes. Left as a documented residual risk
  rather than solved partially and riskily in the same change.

## 4. API and data contracts

- `_ThumbnailTask` gains `cached: bool = False`. Internal dataclass, no
  external contract.
- `LibraryController.entries_rebuilt` payload shape is unchanged
  (`path`/`filename`/`status`/`text`/`tooltip`/`thumbnail`/`placeholder`);
  only the *values* change for previously-cached entries (`thumbnail`
  starts `None`/`placeholder="loading"` instead of an immediately-decoded
  `QImage`, filled in shortly after via the existing
  `entry_thumbnail_updated` signal).
- No persisted-data/schema changes.

## 5. Nuances and failure modes

- **Visible behavior change:** switching to a library whose thumbnails are
  all already cached now shows a brief "Loading" flash across the whole
  grid instead of an instant full render. This is the correct trade for
  removing a multi-second full-UI freeze; documented here so it isn't
  mistaken for a regression.
- **TOCTOU on the cached-file existence check:** `_entry_payload()` checks
  `path_for_key(cache_key).exists()` at rebuild time; if that file is
  deleted before the worker thread later reads it (external interference,
  extremely unlikely in this single-user desktop app), `_on_thumbnail_ready`
  already tolerates a null `QImage` the same way `load_qimage()` always
  has (no crash, just a missing thumbnail visually).
- **Residual risk (documented, not fixed):** a very large library or one
  on slow/network storage still pays a synchronous `stat()`-per-entry cost
  in `list_entries()`. Out of scope per section 1/3; flagged for a future
  slice if it proves to matter in practice.
- **Orphan-cleanup thread lifecycle:** tracked in a list on the controller
  so `LibraryController.cleanup()` can `quit()`/`wait()` any still-running
  cleanup thread on app shutdown, matching how the thumbnail-batch thread
  is already joined.

## 6. UI and reskin impact

- No new widgets. `LibraryView` needed no changes -- its "Loading"
  placeholder path already existed and was already generic; this fix
  routes more entries through it.

## 7. Dependencies

- None; reuses the existing `_ThumbnailBatchWorker`/`QThread` pattern.

## 8. Test plan

- `tests/unit/test_controllers/test_library_controller.py`: a library with
  several already-cached thumbnails, verify `entries_rebuilt`'s payload
  has `thumbnail=None`/`placeholder="loading"` for every entry
  immediately (i.e. the rebuild call itself does not decode anything), and
  that `entry_thumbnail_updated` later delivers the real `QImage` for a
  cached entry without regenerating it (patch `ImageService.
  load_preview_thumbnail` and assert it is never called for a
  pre-cached entry).
- A benchmark-style regression test: populate N (e.g. 200) already-cached
  entries, call `_rebuild_entries_for_current_library()` directly, and
  assert it returns in well under a second (bounds the fix, not just
  proves the mechanism).
- Orphan cleanup: assert `remove_orphaned_cache` is invoked on a worker
  thread (not synchronously inline) and that `cleanup()` waits for it.
- Full existing suite stays green (no behavior change to the tests already
  passing, per section 4).

## 9. Rollout and rollback

- Purely a background-threading change to existing code paths; no data
  format change. Rollback is a plain revert.

## 10. Acceptance criteria

- `_rebuild_entries_for_current_library()` performs no PNG decode and no
  full directory walk synchronously on the calling thread.
- A library with many already-cached thumbnails renders its grid (with
  "Loading" placeholders, progressively filled) without a multi-second
  UI-thread block.
- All existing and new tests pass.

Plan approved -- implementation allowed: **Approved via autonomous continuation session (2026-09-29)**, fixing a responsiveness bug the user reported directly.

## 11. Implementation summary

Landed:

- `_entry_payload()` no longer calls `LibraryThumbnailCacheService.
  load_qimage()` (a synchronous PNG decode) for cache-hit entries. It now
  does a cheap `path_for_key(cache_key).exists()` check and always defers
  the actual load/generation to the background thumbnail worker, so every
  entry (cached or not) goes through the same async
  `entry_thumbnail_updated` delivery path.
- `_ThumbnailTask` gained a `cached: bool` flag; `_ThumbnailBatchWorker`
  skips regeneration for cached entries and just signals readiness --
  `_on_thumbnail_ready`'s existing per-item UI-thread decode (already
  naturally interleaved with the Qt event loop via queued signal delivery)
  handles the rest, unchanged.
- New `_OrphanCacheCleanupWorker` + `_cleanup_orphaned_cache_async()` move
  the full thumbnail-cache-directory walk (`remove_orphaned_cache`, a
  single long synchronous call with no yield point) off the UI thread,
  fire-and-forget, following the exact lifecycle pattern
  `_ThumbnailBatchWorker` already established.
- **Bug found and fixed while writing tests, not part of the original
  plan:** the first version of `_cleanup_orphaned_cache_async()` never
  stored a reference to the new `_OrphanCacheCleanupWorker` instance
  (unlike `_thumbnail_worker`, which `_start_thumbnail_batch` does store).
  Nothing kept it alive, so it was garbage-collected before the queued
  `thread.started -> worker.run` connection could ever deliver -- the
  cleanup thread showed `isRunning() == True` forever but its `run()`
  method silently never executed. Fixed by tracking workers in a
  `_orphan_cleanup_workers` list alongside `_orphan_cleanup_threads`,
  mirroring the already-correct `_thumbnail_worker` pattern. Caught only
  because the new regression test actually waited for and asserted the
  cleanup's side effect, rather than just asserting the call returned.
- `remove_library`'s and `clear_current_library`'s separate, redundant
  synchronous `remove_orphaned_cache` calls were folded into the same
  async dispatch (`clear_current_library`'s was a pre-existing duplicate
  of the one `_rebuild_entries_for_current_library` already issues;
  removed rather than converted).

Verified: full suite (503 tests, up from 498) passes, including 5 new
tests in `TestLibraryRebuildResponsiveness` covering the no-synchronous-
decode property, cached-thumbnail delivery without regeneration, the
cleanup call not blocking the calling thread (timing-based, avoids a
race with `initialize()`'s own concurrent cleanup dispatch), `cleanup()`
waiting for an in-flight cleanup thread, and a 200-entry rebuild
completing in well under a second. Re-ran the affected test file 5x to
confirm no flakiness from the threading involved.
