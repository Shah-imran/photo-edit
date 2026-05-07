# Library async load hotfix (UI freeze regression follow-up)

## 1) Problem and goal

- **Problem:** After introducing async load on library selection, some images did not load at all.
- **Goal:** Preserve non-blocking UI behavior while making library click-to-load reliable.
- **Non-goals:** No changes to RAW decode quality, no batching/prefetch, no redesign of open/import flows.

## 2) Current behavior

- Library click calls `ImageController.load_image_async(...)`.
- Controller creates `QThread` + `_ImageLoadWorker`.
- Regression observed: image sometimes never appears after click.

## 3) Proposed design

- Keep current async architecture.
- Retain strong references to both active thread and worker until thread completion.
- On thread finish, remove both from tracking lists.

Flow:
1. User clicks library item.
2. Main window calls `load_image_async`.
3. Controller appends thread+worker to active lists and starts thread.
4. Worker emits `loaded`/`failed`.
5. Controller updates model/view, emits completion signal, then cleans up references on thread finish.

## 4) API and data contracts

- No external contract changes.
- Existing signals remain:
  - `image_load_started(str)`
  - `image_load_finished(str, bool)`

## 5) Nuances and failure modes

- If worker is not strongly referenced, Python GC can collect it before completion.
- Stale request handling remains request-id based; only latest request updates UI state.

## 6) UI and reskin impact

- None. No widget/layout/style changes.

## 7) Dependencies

- Independent bugfix within current async load slice.

## 8) Test plan

- Add controller unit test:
  - `test_load_image_async_success` waits for `image_load_finished` and asserts image loaded.
- Manual smoke:
  1. Import multiple JPEG + RAW files.
  2. Click each thumbnail.
  3. Verify status bar shows loading and selected image appears.
  4. Rapidly click different thumbnails and confirm last clicked image is displayed.

## 9) Rollout and rollback

- Rollout: normal merge.
- Rollback: revert this hotfix and temporarily route library selection back to sync `load_image(...)` if needed.

## 10) Acceptance criteria

- Library click always results in either displayed image or explicit error message.
- No UI freeze during RAW load.
- Async completion signal is emitted for successful loads.

---

Plan approved -- implementation allowed: **Pending review/approval**
