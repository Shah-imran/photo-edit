# Library load and slider performance tuning

## 1) Problem and goal

- **Problem:** After selecting an image, first display feels slow; slider interaction feels laggy; newly loaded images appear too zoomed in.
- **Goal:** Improve perceived and actual responsiveness for load + live adjustments, and default to fit-to-view on initial image load.
- **Non-goals:** No change to processor math, no RAW quality algorithm change, no new UI controls.

## 2) Current behavior

- Image load path updates model/view, then immediately calls processing worker image setup.
- Worker image setup generates proxy copies/resizes and was being called directly.
- Live slider preview path upscaled proxy back to full resolution each preview frame.
- Initial image zoom remained previous/default zoom unless user manually chose fit.

## 3) Proposed design

1. Route worker image setup through a queued Qt signal so proxy generation happens on worker thread, not UI thread.
2. During slider drags, display proxy-resolution preview directly (no per-frame upscaling to original).
3. On `image_loaded`, call fit-to-window automatically.

## 4) API/data contracts

- No external API changes.
- Internal controller signal added for queued worker setup: `_worker_image_set_requested(object)`.

## 5) Nuances and failure modes

- Must use `Qt.QueuedConnection` to guarantee worker-thread execution.
- Preview quality during drag is intentionally lower; final full-quality render still occurs on slider release.
- Fit-to-window must happen after pixmap is set.

## 6) UI/reskin impact

- No style/layout change; only interaction behavior.

## 7) Dependencies

- Uses existing processing worker/proxy architecture.

## 8) Test plan

- Existing controller and UI tests.
- Manual:
  1. Import and click large RAW/JPEG images.
  2. Verify first display appears without long UI stall.
  3. Drag exposure/contrast rapidly and confirm smoother updates.
  4. Confirm each newly loaded image starts fitted to viewport.

## 9) Rollout/rollback

- Rollout: normal merge.
- Rollback: revert this slice; behavior returns to prior full-res live preview and direct worker calls.

## 10) Acceptance criteria

- Image selection no longer stalls UI due to proxy setup.
- Slider drag latency is visibly reduced.
- Newly loaded images open fitted to current viewport.

---

Plan approved -- implementation allowed: **Pending review/approval**
