# Max-performance slider + navigation behavior

## 1) Problem and goal

- **Problem:** Adjustment sliders feel laggy; zooming shifts image unexpectedly; users need direct drag/pan in view.
- **Goal:** Deliver the “max performance” interaction profile:
  - throttled live preview + debounced/final render path for smooth sliders,
  - stable zoom anchor behavior,
  - drag-to-pan interaction in the image view,
  - no unexpected auto-resize during active editing interactions.
- **Non-goals:** No new adjustment algorithms, no tool-panel redesign, no persistence/schema changes.

## 2) Current behavior

- `ImageController` uses `Debouncer(delay_ms=16)` and submits preview work after debounce, which can still feel bursty and uneven for rapid drags.
- Zoom is applied via `set_zoom_factor` without preserving cursor anchor in viewport coordinates.
- Panning is middle-button only and can feel non-standard.

## 3) Proposed design

### 3.1 Adjustment interaction (max-performance profile)

- Replace simple `Debouncer` usage with `ThrottledDebouncer`.
- On slider movement:
  - emit throttled preview updates (target ~30 fps),
  - keep only latest request visually relevant.
- On slider release / idle:
  - trigger final full-resolution processing path as today.

### 3.2 Zoom and pan behavior

- Add zoom-at-cursor behavior in `ImageView` (scrollbars adjusted after zoom so the point under cursor stays anchored).
- Add left-button drag panning while keeping middle-button drag compatibility.
- Preserve view scale when proxy/full preview swaps during processing updates.

### 3.3 Auto-resize rule

- Auto-fit applies only on initial image load.
- No additional auto-fit during slider updates or zoom/pan interaction.

## 4) API and data contracts

- No external public API changes.
- Internal controller timing behavior changes only.
- Existing signals remain compatible (`adjustments_changed`, `slider_released`, `image_loaded`, `zoom_changed`).

## 5) Nuances and failure modes

- Must avoid overwhelming worker queue on rapid slider drags.
- Cursor-anchor math must clamp scrollbar values safely at bounds.
- Left-drag panning should not interfere with future overlay tools (keep logic scoped to base image-view behavior).

## 6) UI and reskin impact

- No visual restyle; interaction semantics only.
- Keeps view thin; controller/worker still own processing logic.

## 7) Dependencies

- Builds on existing worker queue + proxy preview architecture.
- No new package dependencies.

## 8) Test plan

- Unit/UI tests:
  - image view zoom still respects min/max limits,
  - drag panning path does not crash and updates scrollbars when zoomed,
  - controller slider flow remains functional with throttled preview + final render.
- Manual smoke:
  1. Load large RAW and JPEG files.
  2. Drag sliders rapidly for 5-10 seconds and verify smooth updates.
  3. Zoom in/out at cursor and confirm focal point is stable.
  4. Drag image with left mouse button when zoomed.
  5. Confirm image does not unexpectedly re-fit while adjusting/zooming.

## 9) Rollout and rollback

- Rollout: regular merge.
- Rollback: revert this slice to restore previous debouncer/zoom-pan behavior.

## 10) Acceptance criteria

- Slider interaction visibly smoother under rapid movement.
- Zoom behavior keeps cursor target stable and avoids jumpy viewport shifts.
- Left-drag panning works reliably when zoomed.
- No unexpected auto-resize during adjustments and zoom/pan interactions.

---

Plan approved -- implementation allowed: **Approved by user in chat (2026-05-04)**
