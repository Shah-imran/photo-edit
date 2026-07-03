# 2026-05-07 -- Zoom persistence, edited preview cache, and loading spinner

Related plan: [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) sections 4, 5.1 ; follow-up to the 2026-05-07 adjustment/session persistence slices

## 1. Problem and goal

Navigation now restores saved adjustments, but two pieces of image state are
still missing from that experience:

- the previous zoom level for each image is not restored;
- there is no persisted edited preview to show while a new image is loading;
- transitions have no explicit loading affordance.

The goal is to persist per-image zoom, persist a disk-cached edited preview for
that image state, use it during navigation/startup restore when available, and
show a spinner overlay while a transition is in flight.

Non-goals:

- Persisting pan position / scroll offsets.
- Full-resolution rendered cache of the entire edit stack.
- Replacing the existing RAW/non-RAW preview decode path for normal first-time
  image loads.

## 2. Current behavior

- `adjustment_state` currently stores slider values only.
- `MainWindow` always fits newly loaded images unless an adjustment restore path
  reapplies state afterward.
- `ImageController` always shows its intermediate original-image preview during
  async loads.
- `ImageView` has no loading overlay/spinner.

## 3. Proposed design

- Add a new `LibraryImagePreviewCacheService` under `src/services/` for
  read/write/remove of edited preview images on disk.
- Extend the existing per-entry `adjustment_state` payload additively with:
  - `zoom_factor`
  - `preview_cache_key`
- Persist current image state from `MainWindow` as:
  - adjustment values,
  - current zoom factor,
  - preview cache key plus disk preview image.
- Use the current rendered image (`ImageController.get_current_image()`) as the
  source for the edited preview cache, downscaled before writing to disk.
- Before async image load, if a cached edited preview exists:
  - show it immediately in `ImageView`,
  - restore its zoom,
  - suppress the controller’s intermediate original-image preview for that
    request so the cached edited preview stays visible until the full image
    arrives.
- Add a loading spinner overlay to `ImageView` and toggle it from `MainWindow`
  on load start/finish.
- Keep final adjustment restore on full image load so the cached preview is only
  a transition aid, not the durable source of truth.

## 4. API and data contracts

- New service: `LibraryImagePreviewCacheService`
- Additive `adjustment_state` payload fields:
  - `zoom_factor: float`
  - `preview_cache_key: str | null`
- No breaking signal changes. `ImageController.load_image_async(...)` may gain an
  optional flag for suppressing the intermediate preview.

## 5. Nuances and failure modes

- Zoom restore must not be overwritten by unconditional fit-to-window logic.
- Cached edited previews may be stale after source-file metadata changes, so the
  preview cache key must include file metadata plus adjustment signature.
- If the cached preview cannot be read, the app should fall back to the normal
  async preview/full-load path.
- Spinner overlay must not block normal paint or zoom behavior after loading
  completes.

## 6. UI and reskin impact

- Adds a lightweight loading spinner overlay to the image area during
  transitions.
- No other layout changes.
- Business logic remains in controller/service/main-window orchestration; the
  view only exposes loading/preview presentation methods.

## 7. Dependencies

- Builds on the current per-image adjustment persistence flow and library-entry
  payload storage.

## 8. Test plan

- Unit tests for the new preview-cache service.
- Image-view tests for loading overlay state.
- Main-window UI tests for:
  - zoom persistence across reopen,
  - zoom restoration when navigating back to an image,
  - cached preview file creation for a persisted image state.
- Re-run focused persistence/navigation suites.

## 9. Rollout and rollback

- Immediate additive rollout.
- Rollback can ignore the new payload fields and remove the preview cache
  service without breaking catalog compatibility.

## 10. Acceptance criteria

- Returning to an image restores its saved zoom factor.
- Persisted image state writes a cached edited preview to disk.
- Cached edited preview can be shown before full image decode on navigation when
  available.
- Image transitions show a loading spinner while work is in flight.
- Focused unit/UI tests pass.

Plan approved -- implementation allowed: **Approved by user request in chat (2026-05-07)**
