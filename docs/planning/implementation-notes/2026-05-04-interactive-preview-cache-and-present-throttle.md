# Interactive preview cache and UI present throttle

## 1) Problem and goal

- **Problem:** Even after debounce/throttle tuning, slider interactions still feel laggy on larger images due to heavy preview processing + frequent UI frame commits.
- **Goal:** Improve perceived responsiveness by reducing both compute cost and display commit frequency during drags.
- **Non-goals:** No processor math changes, no GPU migration, no new tools or panel UI.

## 2) Current behavior

- Preview path processes a single proxy tier.
- Every preview completion can trigger a full view refresh, including array->QImage->QPixmap conversion.
- Queue cancellation avoids stale compute, but UI can still receive too many frames to paint smoothly.

## 3) Proposed design

1. **Dual preview caches in `ProxyManager`:**
   - quality proxy (existing behavior baseline),
   - interactive proxy (smaller max side) used for drag previews.
2. **Preview-tier selection in worker requests:**
   - throttled/debounced slider previews use interactive tier,
   - slider release still submits full-resolution final request.
3. **UI present coalescing in `ImageController`:**
   - preview-ready signals are buffered,
   - only latest preview frame is presented at capped cadence (~30 fps),
   - final full-resolution completion bypasses buffer and is shown immediately.

## 4) API and data contracts

- Internal request contract extended with interactive-preview flag.
- No external API changes for views/tools panel.
- Existing signals remain unchanged.

## 5) Nuances and failure modes

- Must avoid presenting stale previews after a newer request or final render.
- Coalescing timer must not delay final full-res completion.
- Interactive tier must preserve aspect ratio and valid float32 shape.

## 6) UI and reskin impact

- No visual redesign; interaction smoothness changes only.

## 7) Dependencies

- Builds on existing processing queue and worker threading model.

## 8) Test plan

- Unit tests:
  - proxy manager returns both quality and interactive proxies correctly.
  - processing worker request wiring handles interactive tier flag.
- Regression tests:
  - existing controller/view tests still pass.
- Manual:
  1. Load large RAW/JPEG.
  2. Drag sliders rapidly and observe reduced stutter.
  3. Release slider and confirm full-quality image appears.

## 9) Rollout and rollback

- Rollout: merge as one focused slice.
- Rollback: revert this slice to previous single-tier preview path.

## 10) Acceptance criteria

- During rapid slider movement, UI updates remain smooth and responsive.
- Preview image updates are visibly more immediate than prior build.
- Full-resolution output still appears on slider release.

---

Plan approved -- implementation allowed: **Approved by user in chat (2026-05-04)**
