# 2026-05-05 -- Display-frame preview pipeline

## Problem

Performance logs showed the worker was often fast enough for interactive
exposure previews, but the UI thread still spent a frame budget converting
preview arrays to `QImage` and then scaling a new pixmap. Quality preview
presentation was worse: 1400px proxy frames commonly spent 80-100ms in the
view path.

## Implementation

- Added `DisplayFrame`, a preview payload that owns display-ready RGB888 data
  plus the processed preview `LinearImage` for current model state.
- Processing workers now convert proxy results to `DisplayFrame` before
  emitting `preview_ready`; full-resolution completion remains `LinearImage`.
- Preview display conversion uses a cached linear-to-sRGB lookup table so the
  UI thread no longer pays per-pixel `np.power` work for live previews.
- `ImageView.set_display_frame(...)` wraps the owned RGB buffer as a `QImage`
  and only creates the `QPixmap` on the GUI thread.
- The image widget now paints the pixmap scaled in `paintEvent` instead of
  allocating a freshly scaled pixmap on each preview update.
- Debounced pause updates stay on the interactive preview tier. Larger quality
  proxy presentation is reserved for slider release and is still dropped if a
  newer interactive request supersedes it.

## Expected Impact

The main-thread preview path should shift from `linear_to_qimage` conversion
plus scaled pixmap allocation to a cheap `QImage` wrapper, `QPixmap.fromImage`,
and repaint request. Worker logs now include `display_ms` so conversion cost is
visible separately from adjustment math.

## Follow-Ups

- Optimize contrast itself; full-resolution contrast is still expensive because
  the adjustment processor encodes and decodes through sRGB.
- Consider persistent display-frame caches keyed by image fingerprint,
  adjustment signature, and tier.
- Move toward tiled/visible-region rendering for zoomed views.
