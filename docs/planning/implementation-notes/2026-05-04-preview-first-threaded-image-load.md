# 2026-05-04 -- Preview-first threaded image load

Slice owner: PhotoEdit team
Status: **DONE**

## 1. Problem and goal

**Problem.** Clicking a library image, especially a RAW file, can leave the
viewer blank while full-resolution demosaic/decoding runs. The decode is already
off the UI thread, but the user gets no useful visual feedback until it
finishes.

**Goal.** Keep full image loading threaded and show a fast scaled preview first,
using embedded RAW thumbnails when available. The full-resolution image replaces
the preview when decoding completes.

**Non-goals.** No RAW quality changes, no prefetch queue, no worker pool, no
cache persistence, and no adjustment math changes.

## 2. Current behavior

- Library selection calls `ImageController.load_image_async(...)`.
- `_ImageLoadWorker` decodes only the full image via `ImageService.load_image`.
- The image view is updated only after full decode succeeds.

## 3. Proposed design

- Extend `_ImageLoadWorker` with a `preview_loaded(request_id, path, image)`
  signal.
- In the worker thread, call `ImageService.load_preview_thumbnail(...)` first.
  For RAW, this uses `RawService.thumbnail_linear`, which prefers embedded
  previews and falls back to half-size postprocess.
- Show that preview in `ImageView` without committing it to `ImageModel` or the
  processing worker.
- Continue full decode in the same worker thread; when it finishes, commit the
  full image to the model, view, history reset, and processing proxy setup.

## 4. API and data contracts

- New controller signal: `image_preview_ready(str)`.
- Existing `image_load_started(str)` and `image_load_finished(str, bool)` remain.
- Preview payloads and full image payloads are both `LinearImage`.
- Preview images are display-only; only the full image becomes
  `ImageModel.original_image`.

## 5. Nuances and failure modes

- Stale previews are ignored using the same request id rule as full loads.
- Preview failure is logged but does not fail the load; full decode continues.
- Tools remain disabled until full image load completes, so users do not edit a
  display-only preview.
- Full image load still emits success or failure exactly once.

## 6. UI and reskin impact

No layout or style change. The viewer can display an early preview, and the
status bar reports that full decoding is still in progress.

## 7. Dependencies

Uses the existing async load worker, `ImageService.load_preview_thumbnail`, and
RAW thumbnail support from the RAW slice.

## 8. Test plan

- Controller unit test with a fake image service:
  - preview signal fires before full load completes,
  - preview is visible in `ImageView`,
  - model remains unloaded until full image arrives,
  - full image size is committed after completion.
- Existing async load tests should continue to pass.
- Manual smoke:
  1. Import several RAW files.
  2. Click a thumbnail.
  3. Confirm a scaled preview appears quickly.
  4. Confirm the full image replaces it and tools enable when loading finishes.
  5. Rapidly click between images and confirm stale previews do not win.

## 9. Rollout and rollback

Rollout is a focused controller/UI slice. Rollback reverts the new preview
signal and returns to full-decode-only async loading.

## 10. Acceptance criteria

- [x] Full image decode stays off the UI thread.
- [x] A display-only preview can appear before full RAW decode completes.
- [x] The model and processing worker receive only the full-resolution image.
- [x] Preview failure does not abort full loading.
- [x] A focused controller test covers preview-before-full behavior.

---

Plan approved -- implementation allowed: **Approved by user request in chat (2026-05-04)**

## 11. Implementation summary

Implemented in `src/controllers/image_controller.py` and
`src/views/main_window.py`. `_ImageLoadWorker` now emits a preview loaded from
`ImageService.load_preview_thumbnail(...)` before continuing with full decode.
`ImageController` displays that preview without mutating `ImageModel`, and
`MainWindow` shows status feedback until the full image finishes. Added a unit
test in `tests/unit/test_controllers/test_image_controller.py`.
