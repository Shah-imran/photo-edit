# 2026-09-30 -- Fix: micro-freezes on image load/switch, wrong initial zoom, and a crash-on-cleanup race

Related plan: [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) sections 4, 5.1. Bug fixes, not a roadmap phase slice -- reported directly by the user across three messages: an unreproducible "freeze" when clicking during an image load/app launch, then narrowed to "sometimes ... it would come at its full size or zoomed in state" on load/switch, plus "micro freezes between loading different image or loading the software first time."

## 1. Problem and goal

Three related but distinct symptoms, all tied to the single-image load/switch path (`ImageController.load_image_async` / `_ImageLoadWorker` / `ImageView`), not the library-grid path already fixed in [2026-09-29-library-rebuild-responsiveness.md](2026-09-29-library-rebuild-responsiveness.md) (that fix's own "non-goals" section explicitly says the single-image open path was "already correctly threaded... not touched here" -- true for the *decode*, not for what happens to the result on the UI thread):

1. **Intermittent wrong initial zoom.** A freshly loaded or switched-to image sometimes opens at 100% (or a stale zoom) instead of fit-to-window.
2. **Micro-freezes on load/switch.** A short but noticeable UI hitch specifically when an image finishes loading or when switching between images, including the very first load after launching the app.
3. **A reproduced crash** (`Fatal Python error: Aborted`) surfaced while writing a regression test for (1): a still-running load thread whose Python-side `QThread`/worker wrapper gets garbage-collected while its native thread is still executing.

**Goal:** fix all three without changing the already-correct threading of the decode itself.

**Non-goals:** the library-grid thumbnail path (already fixed separately); RAW decode performance; `LibraryController.cleanup()`'s analogous `thread.wait()` calls (its worker checks a cancellation flag between items, a materially different -- and much faster -- shutdown path than an uninterruptible full-image decode, so the same fix does not obviously apply and was not touched here).

## 2. Current behavior

- **Zoom race:** `_ImageLoadWorker.run()` emits `preview_loaded` (a downscaled proxy) strictly before `loaded` (the full decode). `ImageController._on_async_image_preview_loaded` calls `ImageView.set_image(preview, emit_loaded=False)` then schedules `QTimer.singleShot(0, self._image_view.fit_to_window)`. When the full image later loads, `_apply_loaded_image` calls `self._image_view.set_image(image)` with `preserve_view_scale` defaulting to `False`, which resets `_zoom_factor` to `1.0` -- and nothing calls `fit_to_window()` again for the full-resolution swap. `MainWindow._on_image_load_finished` only restores zoom when `_pending_zoom_factor` is not `None` (a previously-saved per-image zoom); otherwise it does nothing. Whether the final displayed zoom ends up fitted or stuck at 100% depends on whether the preview stage's `singleShot(0)` happens to fire before or after the full image's `set_image()` reset -- a genuine event-queue race, matching "sometimes."
- **Micro-freeze:** `ImageView._set_array()` (reached by every `set_image()` call, including the full-resolution one in `_apply_loaded_image`) built its `QImage` via `color_pipeline.linear_to_qimage()`, which runs the exact sRGB OETF (`np.power(arr, 1/2.4)` over the whole array via `linear_to_srgb`) synchronously on the UI thread. Every other on-screen redraw in the app (every adjustment-driven preview) instead goes through `ProcessingWorker` producing a `DisplayFrame` via `linear_to_display_rgb()` -- a cached-LUT encode already written specifically "to avoid per-pixel power functions on the UI thread" (its own docstring) -- computed on the *background* processing thread. The one path that never got wired into that LUT is the direct `ImageView.set_image()` call, which is exactly what runs, on the UI thread, every time an image finishes loading or is switched (including app launch). For a full-resolution photo this is a measurable, synchronous hitch at exactly the reported moments.
- **Crash:** `ImageController.cleanup()` (called from `MainWindow.closeEvent`) did `thread.quit(); thread.wait(2000)` for every tracked load thread, then unconditionally `self._load_threads.clear(); self._load_workers.clear()`. `_ImageLoadWorker.run()` has no cancellation check -- it is a single uninterruptible decode -- so `wait(2000)` can time out while the thread is still running (a large/slow decode, or a loaded machine). The old code dropped the last Python reference to that still-running `QThread`/worker pair regardless. Reproduced directly: running the real async-load path back-to-back with other Qt-object-heavy tests produced `Fatal Python error: Aborted`, with the crashing background thread still inside `_ImageLoadWorker.run()`'s decode while the main thread was garbage-collecting during an unrelated allocation.

## 3. Proposed design

- **`ImageView._set_array()`:** replace `linear_to_qimage(arr)` with the same LUT path the worker already uses (`linear_to_display_rgb` from `display_frame.py`), building the `QImage` the same way `DisplayFrame.to_qimage()` does (wrap the returned contiguous `uint8` RGB buffer, then `.copy()` so the `QPixmap` conversion cannot outlive it). `linear_to_qimage` itself is untouched and stays used/tested for callers that need the exact (non-LUT) conversion.
- **`MainWindow._on_image_load_finished`:** when there is no `_pending_zoom_factor` to restore, explicitly defer a `fit_to_window()` call via `QTimer.singleShot(0, ...)` (same deferral idiom already used for the preview stage, needed so layout/viewport size has settled) instead of leaving the zoom wherever the last `set_image()` reset left it.
- **`ImageController.cleanup()`:** only forget a load thread whose `wait()` actually returned `True`. A thread still running after the timeout stays in `_load_threads`/`_load_workers` (so it is not garbage-collected out from under its own native thread) and is left to the `finished`-signal handlers already wired up in `load_image_async()` (`worker.deleteLater`, `thread.deleteLater`, `_on_load_thread_finished`) to tear down once the decode actually completes.

## 4. API and data contracts

None. All three changes are internal to existing methods; no signal, signature, or persisted-data shape changes.

## 5. Nuances and failure modes

- **LUT quantization:** `linear_to_display_rgb` trades imperceptible per-pixel rounding error for avoiding `np.power()` on the UI thread -- already the accepted tradeoff for every adjustment-driven redraw in the app; this change only makes the *initial* full-image display consistent with that existing tradeoff rather than introducing a new one.
- **Zoom fix ordering:** the fix intentionally does not touch the preview-stage `fit_to_window()` call (still useful for the brief window before the full image arrives); it adds a second, authoritative one after the full image lands and no saved zoom applies, so the final state no longer depends on which of the two races first.
- **Cleanup fix residual risk:** a load thread that keeps running past app-window close continues to hold a reference to `ImageService`/the file it was decoding until it finishes on its own; this is a bounded, self-resolving leak (one decode's worth of time) rather than the crash it replaces, and matches how `_ThumbnailBatchWorker`/`_OrphanCacheCleanupWorker` are already allowed to finish asynchronously elsewhere in the codebase.

## 6. UI and reskin impact

None -- no widget/layout changes, only how an existing display conversion is computed and when `fit_to_window()` is called.

## 7. Dependencies

None; reuses `linear_to_display_rgb`, already a dependency of `DisplayFrame`.

## 8. Test plan

- `tests/unit/test_views/test_image_view.py`: `set_image()` must call `linear_to_display_rgb` (patched-and-wrapped to assert it is used, not `linear_to_qimage`).
- `tests/ui/test_main_window.py`: an async load of an image much larger than the test window, with no saved per-image zoom, must end with `zoom < 1.0` (proving `fit_to_window()` ran), not stuck at the `1.0` reset value; waits for the background load thread to fully finish afterward so it cannot bleed into a later test.
- `tests/unit/test_controllers/test_image_controller.py`: `cleanup()` with a mocked thread whose `wait()` returns `False` must keep it tracked (not dropped); one whose `wait()` returns `True` must still be forgotten, unchanged from before.
- Full existing suite stays green.

## 9. Rollout and rollback

Purely internal behavior changes; rollback is a plain revert of each file. No data format changes.

## 10. Acceptance criteria

- An image with no saved zoom reliably ends up fit-to-window after both the initial load and any subsequent switch, regardless of preview/full-load timing.
- The full-resolution display conversion after a load/switch uses the same O(1)-per-pixel LUT as every other redraw, not a per-pixel `power()` pass.
- `cleanup()` no longer drops a live `QThread`/worker pair whose native thread has not actually finished.
- All new/updated tests pass; full existing suite stays green.

Plan approved -- implementation allowed: **Approved via autonomous continuation session (2026-09-30)**, fixing responsiveness/correctness bugs the user reported directly.

## 11. Implementation summary

Landed:

- `src/views/image_view.py`: `_set_array()` now builds its `QImage` via `linear_to_display_rgb` (the LUT-based encode already used by every worker-produced preview) instead of `linear_to_qimage`'s per-pixel `np.power()` path. `linear_to_qimage` itself is untouched, still used/tested elsewhere for exact conversions.
- `src/views/main_window.py`: `_on_image_load_finished` now defers an explicit `fit_to_window()` (via `QTimer.singleShot(0, ...)`) whenever there is no saved `_pending_zoom_factor` to restore, removing the race between the intermediate-preview stage's own deferred fit call and the full-image `set_image()` reset.
- `src/controllers/image_controller.py`: `cleanup()` now only untracks a load thread whose `wait(2000)` actually returned `True`; a still-running one stays referenced (and is logged) so it is not garbage-collected while its native thread is alive, relying on its already-connected `finished` handlers to clean up once it actually completes.
- **Bug reproduced directly while validating the zoom-race fix, not part of the original plan:** the first version of the new async-load regression test (using a 5000x3500 synthetic image) triggered `Fatal Python error: Aborted` when run alongside other tests -- exactly the crash described above, caused by `cleanup()`'s old unconditional-clear behavior racing a still-decoding thread against the next test's object allocation/GC. This is what motivated fix 3 above; confirmed fixed by re-running the same test combination 4x with no crash (down from a crash or unrelated-test flakiness -- `QScrollArea has been deleted`, stray `image_load_finished` deliveries -- on nearly every run beforehand). The regression test itself was also tightened (smaller image, explicit wait for the background thread to fully finish) so it cannot leak a live thread into a later test.

Verified: full suite (546 tests, up from 542) passes. The one pre-existing failure, `test_geometry_is_restored_on_next_launch`, was confirmed to fail identically on unmodified code -- it is a headless/offscreen-QPA environment limitation (window resize doesn't apply under `QT_QPA_PLATFORM=offscreen`), unrelated to this change.

Deferred: `LibraryController.cleanup()`'s structurally similar `thread.wait()` calls were left as-is (different, interruptible worker shape; out of scope per section 1).
