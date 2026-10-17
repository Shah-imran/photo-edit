# Responsiveness overhaul: off-UI-thread rendering and settings-based undo

Related: [PERFORMANCE_OVERHAUL.md](../PERFORMANCE_OVERHAUL.md) Phases 1, 2
and part of 4. Supersedes the image-buffer parts of
[2026-10-13-state-aware-undo-redo.md](2026-10-13-state-aware-undo-redo.md).

## 1. Problem

Measured on a 24 MP CR3 before this change:

- `ImageView.set_image` converted 24 MP floats to RGB on the UI thread
  (~330 ms) on every photo open, undo, redo, mask/heal preview and crop
  entry.
- Mask and heal previews, crop entry/cancel, and `restore_adjustment_state`
  (photo switch, paste, presets) ran a full-resolution render
  synchronously on the UI thread: seconds per mouse move while dragging a
  mask.
- Undo history held two full-resolution float buffers per step (up to
  ~14 GB for 50 steps) and a step only existed after a delayed 24 MP render
  finished.
- `ProcessingWorker.set_image` was invoked through a queued signal whose
  receiver thread never spins an event loop, so it actually ran on the UI
  thread, and a render requested in the same call could reach the worker
  first ("No image available").
- The canvas scaled the whole pixmap on every repaint (~290 ms when
  zoomed in).
- Zoom was relative to whichever preview was on screen, so "100%" after
  an edit showed the 1400 px preview at 1:1, not the photo.
- The crop overlay cleared its "hole" with `CompositionMode_Clear`, which
  erased the photo to black inside the crop box.

## 2. Design

- **History stores settings.** `_commit_pending_history()` pushes an
  `AdjustmentStateCommand` with `previous_image=new_image=None` at the end
  of a gesture (slider release, Apply). Undo/redo restore the state and
  `refresh_view()` asks the worker for a quality frame; the worker's
  preview cache makes recent states instant. The synchronous
  (`use_threading=False`) path is unchanged.
- **One async render entry point.** `_render_kwargs()` / `_request_render()`
  replace the repeated 22-argument submit calls. `refresh_view()` in
  threaded mode requests a quality render instead of converting floats.
- **Tool previews** (`preview_mask`, `preview_heal_spots`,
  `preview_uncropped`) submit display-only requests: interactive frames
  while dragging, one quality frame 120 ms after input stops. Display-only
  frames never replace `image_model.current_image`.
- **Full resolution only for detail.** The delayed full render runs only
  when `_view_needs_detail()` (the view magnifies a preview that has fewer
  pixels than the output). Its RGB conversion happens in the worker
  (`final_frame_ready`).
- **Photo open** builds the display frame on the load thread
  (`LoadedImage`), and `ProcessingWorker.set_image` hands the image to the
  worker thread, which installs it before serving any later request.
- **True zoom.** `DisplayFrame.source_size` records the full-resolution
  size a frame represents; `ImageView` measures zoom against it.
- **Canvas** paints only the exposed region.
- **Histogram** is computed from a ~0.25 MP subsample.

## 3. Results (24 MP CR3, real MainWindow, `app_smoke.py`)

| Action | UI-thread time before | After |
|---|---|---|
| Slider drag tick | ~0.1 ms (render async already) | ~0.1 ms |
| Slider release | small, then 24 MP render + 330 ms repaint on undo | 0.6 ms |
| Undo / redo | ~330 ms+ | 0.6-0.7 ms |
| Mask drag tick | full 24 MP render (seconds) | 0.1 ms |
| Enter crop | full 24 MP render + 330 ms | 0.6 ms |
| UI stalls > 50 ms across open, drag, release, undo, redo, zoom, mask, crop | many | none (outside test screenshots) |

## 4. Tests

- `tests/integration/test_responsiveness.py`: real workers, 24 MP image;
  drag/release/undo/redo/restore/mask stay under 50 ms on the UI thread
  and frames arrive.
- `tests/unit/test_views/test_image_view_zoom.py`: source-relative zoom.
- Controller tests updated for settings-only history and detail renders.
