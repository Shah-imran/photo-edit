# 2026-05-04 -- Threaded adjustment cancellation and history commit

Slice owner: PhotoEdit team
Status: **DONE**

## 1. Problem and goal

**Problem.** Slider preview requests are cancellable, but slider release still
committed through `CombinedAdjustmentCommand`, which re-ran processors
synchronously on the UI thread. Large images could therefore appear to pause
after release before the final adjustment landed.

**Goal.** Keep adjustment rendering off the UI thread, ignore stale worker
results, and record undo/redo history without recalculating pixels on the UI
thread.

**Non-goals.** No GPU work, no tile renderer, no new adjustment controls, and no
processor math changes.

## 2. Current behavior

- Drag previews are throttled and use worker proxy requests.
- On slider release, `submit_final_request(...)` starts a full-resolution worker
  render.
- Immediately after that, `commit_adjustments()` executes a
  `CombinedAdjustmentCommand`, which processes the same adjustment again on the
  UI thread.

## 3. Proposed design

- Capture the image state at the start of a drag gesture.
- On slider release, start an idle timer and return immediately. Submit the
  full-resolution request only if the user does not move the slider again for
  long enough to make a real "editing pause" likely.
- If a new slider movement arrives before the idle timer fires, cancel the
  pending full render so previews are not stuck behind avoidable full-res work.
- In threaded mode, route direct `apply_adjustments(...)` calls to worker preview
  or final requests instead of running local processors.
- Use a dedicated preview worker for interactive/quality preview requests and a
  separate full-resolution worker for background final renders.
- Add process-level performance logging for adjustment scheduling, worker source
  fetch/cache/process/emit, and UI array-to-pixmap presentation.
- In `_on_processing_complete`, ignore results that are no longer the worker's
  latest request.
- When the latest full-resolution release render completes, commit an
  `ImageStateChangeCommand` containing the already-rendered before/after images.
- Do not repaint the viewer with the full-resolution render on normal release
  completion. The screen already has the latest proxy preview; converting a
  full RAW-sized array to `QPixmap` is UI-thread work and causes the next drag
  to hitch.

## 4. API and data contracts

- New command: `ImageStateChangeCommand(image_model, previous_image, new_image)`.
- No public UI signal changes.
- Existing synchronous fallback remains for non-threaded callers/tests.

## 5. Nuances and failure modes

- If another slider movement submits a newer preview while an older full render
  is running, the older full render is ignored when it finishes.
- Running full-res renders cannot currently be interrupted mid-NumPy/OpenCV call,
  so the main mitigation is to avoid starting them too eagerly on release.
- Live previews use a smaller interactive proxy so each adjustment frame is
  cheaper to process and cheaper to present.
- Drag previews must use the small interactive tier; pause/release previews must
  use the larger quality tier.
- Preview renders have a small in-memory cache keyed by tier, image shape, and
  adjustment parameters. Full-resolution renders are deliberately not cached to
  avoid holding large duplicate arrays.
- History must not re-run processors during threaded commits.
- Capturing the previous image should not copy a full-resolution buffer on the
  UI thread. The pipeline treats `LinearImage` arrays as immutable, so a
  reference is sufficient.
- Preview images may temporarily appear in the view, but the stored history
  previous state is captured at the start of the gesture.

## 6. UI and reskin impact

No layout or style changes. The visible behavior should be less blocking after
slider release.

## 7. Dependencies

Builds on the existing `ProcessingWorker` request id / latest-request behavior.

## 8. Test plan

- Controller unit test: stale processing completion does not overwrite current
  image.
- Controller unit test: full render completion commits undo history without
  calling processors on the UI thread.
- Controller unit tests: threaded `apply_adjustments(...)` schedules preview and
  final worker requests without touching local processors.
- Controller unit tests: slider release delays the final full-res render until
  idle, and renewed slider movement cancels the pending full render.
- Controller unit tests: drag uses the interactive tier, pause uses the quality
  tier.
- Processing-worker tests: preview renders reuse cache; full-resolution renders
  bypass it.
- Existing adjustment and UI tests should remain green.

## 9. Rollout and rollback

Rollout is a focused controller/command change. Rollback restores immediate
synchronous `CombinedAdjustmentCommand` commits after slider release.

## 10. Acceptance criteria

- [x] Slider release does not synchronously process full-resolution pixels in
  the threaded app path.
- [x] Stale worker results are ignored.
- [x] Undo/redo history records completed worker renders without reprocessing.
- [x] Threaded direct adjustment calls schedule worker requests rather than
  processing locally.
- [x] Slider release waits for an idle window before queuing full-res render.
- [x] New slider movement cancels a pending full-res render.
- [x] Background full-res completion updates model/history without repainting a
  full-resolution pixmap into the viewer.
- [x] Preview and full-resolution work use separate workers.
- [x] Preview render cache avoids recomputing repeated states.
- [x] Performance timing logs are emitted under `logs/photoedit.log` when the
  app is run from the project.
- [x] Focused tests cover stale completion, non-processing history commit, and
  direct threaded adjustment scheduling.

---

Plan approved -- implementation allowed: **Approved by user request in chat (2026-05-04)**

## 11. Implementation summary

Added `ImageStateChangeCommand` in `src/commands/adjustment_commands.py`.
`ImageController` now captures the pre-gesture image by reference, submits full
renders after a longer idle delay, cancels that pending final render when the
user moves a slider again, ignores stale completions, and commits the latest
worker-rendered image state to history without repainting the full-resolution
array into the viewer. Preview and full-resolution renders are split across
separate workers so full renders do not block interactive feedback. Threaded
`apply_adjustments(...)` now schedules worker preview/final requests rather than
running local processors. `ProcessingWorker` now caches small preview results,
but not full-resolution results. The app now logs project-local timing traces to
`logs/photoedit.log`, including controller scheduling, worker processing, cache,
and view presentation timings. Added regression tests in
`tests/unit/test_controllers/test_image_controller.py` and
`tests/unit/test_processing/test_processing_worker.py`.
