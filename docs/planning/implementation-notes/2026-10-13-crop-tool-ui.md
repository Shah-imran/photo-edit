# Crop tool UI (interactive overlay), slice 2 of 2

Related roadmap: Phase I ("Geometry and Crop", PDF sections 19-20),
`docs/planning/PRODUCT_ROADMAP.md`'s Crop tool bullet. Related prior
slice: `docs/planning/implementation-notes/2026-10-13-crop-processor.md`,
which built the entire data/processing layer this slice drives through
its one public entry point, `ImageController.on_crop_changed(crop)`.

## 1. Problem, goal, and non-goals

This is **slice 2 of 2**. Slice 1 built `CropProcessor`, full
pipeline/undo-redo/export wiring, and a programmatic
`ImageController.on_crop_changed(crop: dict)` API, but explicitly left
unbuilt: the interactive drag-handle overlay, aspect-ratio presets, and
the disabled "Crop" placeholder in `EditingToolStrip`. This slice builds
exactly that -- a new widget plus the UI chrome to drive
`on_crop_changed` -- and touches no processor or pipeline code.

**Non-goals (explicitly out of scope for this slice):**

- A "start a new rectangle from an outside click" gesture. **Decision
  made:** clicking outside the current crop rect, not on a handle, is a
  simple no-op (see section 4.2's hit-testing design and the
  `test_outside_click_not_on_handle_is_a_no_op` test). The user must
  drag an existing handle or move the existing rect; there is no
  draw-a-fresh-rectangle-from-scratch interaction in this v1.
- Rotate/flip-within-crop controls (Lightroom's crop panel also exposes
  a rotate dial and flip buttons; neither exists here).
- Any overlay style beyond the rule-of-thirds grid (no golden ratio, no
  diagonal guides, no grid toggle).
- Optimizing the full-resolution image fetch on crop-mode entry (see
  section 6) -- `_enter_crop_mode` calls
  `get_export_image(apply_crop=False)` on every entry, which
  reprocesses the entire original at full resolution synchronously on
  the UI thread. Accepted as a known v1 cost; a future optimization
  could use a smaller proxy for the crop-mode preview specifically.
- Upright modes, Distortion/Scale/Offset (still a separate, larger
  future undertaking per the roadmap's own Phase I scoping note).

## 2. Current behavior

Before this slice, `ImageController.on_crop_changed` was callable only
from tests/scripts -- `EditingToolStrip`'s "Crop" button was a disabled
placeholder identical to Heal/Mask/Transform, and no widget existed to
let a user see or drag a crop rectangle.

## 3. Design

### 3.1 The coordinate-math property that makes this tractable

`_ImageCanvas.set_pixmap` resizes the canvas widget to exactly
`pixmap_size * zoom_factor` and paints the pixmap filling its own
`rect()` with no internal margin or centering. That means the canvas's
own `(0, 0)`-to-`(width, height)` local rect IS the displayed, zoomed
pixmap's screen rect, at any zoom level. `CropOverlay` is a child of
`_image_canvas`, resized to `_image_canvas.size()` and moved to `(0,
0)` every time the canvas resizes (`ImageView._update_display` now also
keeps the overlay in sync on every zoom/pixmap change). Given that, a
pixel position `(local_x, local_y)` inside the overlay maps directly to
a normalized image fraction via `local_x / self.width()` and
`local_y / self.height()` -- no scroll-offset correction, no zoom
correction, nothing extra. This is the entire reason the widget's
interaction code (`_hit_test`/`_apply_drag`) can work purely in its own
local pixel space and convert to/from fractions with a single division.

### 3.2 `CropOverlay` (`src/views/widgets/crop_overlay.py`)

A `QWidget` with `WA_TranslucentBackground` set, painted with a
semi-transparent dark fill (`rgba(0,0,0,150)`) over the whole widget,
then a transparent "hole" punched for the crop rectangle via
`QPainter.CompositionMode.CompositionMode_Clear` (verified visually to
actually clear to transparent rather than merely fill black -- the
simplest correct technique available, versus manually computing four
surrounding rects). A `#0078d4` 2px border outlines the crop rect, a
rule-of-thirds grid (`rgba(255,255,255,80)`, two lines each direction)
is drawn inside it, and 8 white ~9px square handles mark the 4 corners
and 4 edge midpoints.

State is `self._x0, self._y0, self._x1, self._y1` (normalized
fractions) plus `self._locked_aspect: Optional[float]`.

**Hit-testing (`_hit_test`)**: returns one of the 8 handle names
(`"top_left"`, `"top"`, etc.), `"move"` (click inside the rect, not
near any handle), or `None` (click outside the rect, not near any
handle -- a documented no-op, see section 1's non-goals). Handle
proximity uses a fixed 10px screen-pixel radius, independent of zoom
(correct, since the overlay's own pixel space already reflects the
current zoom via the canvas-matching resize).

**Drag application (`_apply_drag`)**: a corner handle updates both its
x and y coordinate; an edge-midpoint handle updates only x or only y; a
move-drag translates the whole rect by the press-to-current-position
delta, clamped so the rect cannot leave `[0, 1]` on either axis. Every
case clamps the result through `_clamp_rect` (which also guarantees
`x1 > x0`/`y1 > y0` and a minimum rect size, so no drag combination can
degenerate the rect to zero area or invert it), then updates state,
repaints, and emits `rect_changed`.

**Aspect lock (`_apply_aspect_lock`)**: when `self._locked_aspect` is
set, after a handle moves one or two of the four coordinates, the
*other* dimension is recomputed from the ratio, anchored at whichever
edge/corner the handle does NOT touch (so dragging the bottom-right
corner under a locked aspect keeps the top-left corner fixed and grows
width+height together from the drag; dragging the right edge keeps the
vertical center fixed and grows/shrinks height symmetrically around
it). The recomputed rect is then clamped into `[0, 1]` the same way an
unlocked drag is, so an aspect-locked drag that would overflow the
canvas simply stops growing at the boundary rather than producing an
out-of-bounds or inverted rectangle.

`set_rect`/`get_rect` are the programmatic set/read pair; `set_rect`
never emits `rect_changed` (mirrors `AdjustmentSlider.set_value`'s
"set without signaling" convention already established elsewhere in
this codebase, e.g. `CurveEditor.set_points`).

### 3.3 `CropToolbar` (`src/views/widgets/crop_toolbar.py`)

A `QFrame` mirroring `ImageToolBar`'s dark-chrome styling (`#202020`
background, `#343434` top/bottom border) and swapped into the same
layout slot `ImageToolBar` already occupies (directly below the
canvas), shown only while crop mode is active. Contains a `QComboBox`
with `Free`/`Original`/7 fixed ratio presets (`1:1`, `16:9`, `9:16`,
`4:3`, `3:4`, `5:4`, `4:5`), and `Apply`/`Cancel` buttons. `Original`'s
actual ratio is resolved via `set_original_ratio(ratio)`, called once
by `MainWindow._enter_crop_mode` from the just-fetched uncropped
image's own `shape` -- the toolbar itself never computes or stores
image dimensions. Selecting a named ratio (including re-selecting
`Original` after a fresh `set_original_ratio` call) emits
`aspect_ratio_changed(ratio_or_None)`; `Apply`/`Cancel` emit their own
plain signals.

### 3.4 `ImageView` additions

`enter_crop_mode(initial_rect)` lazily creates a single `CropOverlay`
child of `_image_canvas` (created once, then shown/hidden on
subsequent entries rather than recreated, avoiding repeated
construction), resizes/positions it to match the canvas, calls
`set_rect(**initial_rect)`, shows it, and raises it to the top of the
stacking order. `exit_crop_mode()` only hides it. `_update_display()`
(already called on every zoom/pixmap change) now also keeps the
overlay's size matched to the canvas whenever it is visible, so zooming
while in crop mode keeps the drag handles aligned with the image.
`ImageView` itself has no opinion about adjustment state -- entering
crop mode does not change what image is displayed; the caller
(`MainWindow`) is responsible for having already shown the correct
(uncropped) image first.

### 3.5 `MainWindow` wiring

`EditingToolStrip` gained a `crop_tool_requested` signal, emitted by
the now-enabled Crop button (Heal/Mask/Transform remain untouched,
disabled placeholders). `ToolsPanel` keeps a reference to its
`EditingToolStrip` instance (previously discarded after construction)
and forwards the signal outward as its own `crop_tool_requested`,
mirroring the existing direct-re-emit pattern already used for
`self._hsl_mixer_panel.slider_released.connect(self.slider_released)`.

`MainWindow._enter_crop_mode`: bails with a status-bar message if no
image is loaded; otherwise reads the current `"crop"` adjustment state
as the overlay's initial rectangle, fetches
`get_export_image(apply_crop=False)` (the full, uncropped,
otherwise-fully-adjusted image -- see section 1's non-goals for the
accepted performance cost), displays it via `ImageView.set_image(...,
emit_loaded=False, preserve_view_scale=True)`, calls
`ImageView.enter_crop_mode(crop)`, resolves the "Original" aspect ratio
from the uncropped image's own shape, resets the aspect combo to
"Free" and clears any stale `locked_aspect` on the overlay (so a
previous crop session's aspect choice never silently carries into a
new one), and swaps `CropToolbar` in for `ImageToolBar`.

`MainWindow._apply_crop`: reads `CropOverlay.get_rect()`, calls
`ImageController.on_crop_changed(rect)` (already routes through the
full undo/redo-integrated commit path from slice 1 -- no explicit
`refresh_view()` call is needed here, since `on_crop_changed` ->
`apply_adjustments(add_to_history=True)` already repaints via its own
existing path), exits crop mode, and swaps the toolbars back.

`MainWindow._cancel_crop`: exits crop mode without calling
`on_crop_changed`, then explicitly re-fetches
`get_export_image()` (default `apply_crop=True`, so any previously
committed crop is honored again) and re-displays it, since simply
hiding the overlay does not by itself revert the canvas back from the
uncropped preview image `_enter_crop_mode` had put there.

**The status-bar dimensions fix.** Slice 1 flagged that
`_dimensions_label` was set once at image load and never refreshed
after a later shape-changing edit (only Crop can cause one).
`_on_adjustment_state_restored` -- already connected to
`ImageController.adjustment_state_restored`, which fires on every
commit including a crop commit -- now also reads
`ImageController.image_model.get_current_image()`'s shape and updates
both `_dimensions_label` and `_megapixels_label`. This works because
`apply_history_state` (the sole emitter of `adjustment_state_restored`)
already assigns the newly rendered (and, for a crop, newly smaller)
image to `current_image` before emitting, so the read is always
current.

## 4. Contracts

- `ImageController.get_export_image(apply_crop: bool = True)`: new
  optional parameter, default `True` (every existing call site
  unaffected). `False` skips the final `CropProcessor` call.
- `CropOverlay.set_rect(x0, y0, x1, y1)`/`get_rect() -> dict`:
  programmatic set/read; `set_rect` never emits `rect_changed`.
- `CropOverlay.set_locked_aspect(ratio: Optional[float])`: affects only
  the *next* drag-resize, not existing state.
- `CropOverlay.rect_changed = pyqtSignal(dict)`: emitted continuously
  during a user drag (press through each move through release), never
  by `set_rect`.
- `CropToolbar.aspect_ratio_changed = pyqtSignal(object)`: a `float`
  ratio or `None` ("Free").
- `ImageView.enter_crop_mode(initial_rect)`/`exit_crop_mode()`/
  `is_in_crop_mode() -> bool`/`get_crop_overlay() -> Optional[CropOverlay]`.
- `EditingToolStrip.crop_tool_requested`/`ToolsPanel.crop_tool_requested`:
  forwarded, no payload.

## 5. Nuances and failure modes

**Clicking outside the rect, not on a handle, does nothing.** See
section 1; this is a deliberate, documented v1 simplification rather
than an oversight.

**Re-entering crop mode after an earlier aspect-lock choice.**
`_enter_crop_mode` explicitly resets the toolbar's combo to "Free" and
clears the overlay's `locked_aspect` on every entry, so a stale lock
from a previous session (Apply or Cancel) never silently carries
forward.

**`_cancel_crop`'s re-display is a real re-fetch, not a cached
revert.** Simply hiding the overlay would leave the canvas showing the
uncropped preview image `_enter_crop_mode` swapped in; `_cancel_crop`
must call `get_export_image()` again (with the default `apply_crop=True`)
and `set_image` it back, which is a second full-resolution reprocess --
the same accepted v1 cost as crop-mode entry itself.

**Aspect-lock anchoring is "keep the fixed opposite edge, don't
overthink exotic edge cases."** The implementation anchors at the
edge/corner the dragged handle does not touch and clamps into `[0,
1]` afterward; it does not attempt to re-anchor at a different corner
if the naive anchor would overflow the canvas (it simply stops
growing at the boundary instead, which is simple, bounded, and never
produces a degenerate or out-of-range rect, per
`test_drag_outside_bounds_stays_clamped_and_non_degenerate` and
`test_aspect_lock_forces_square`).

**The full-resolution fetch on every crop-mode entry/cancel is a known
v1 cost**, not fixed here -- see section 1's non-goals.

## 6. Test plan

- `tests/unit/test_views/test_crop_overlay.py` (18 tests): `set_rect`/
  `get_rect` round-trip and non-emission; clamp/swap on malformed
  input; all 8 handles individually hit-tested at their exact pixel
  positions; an inside-not-on-a-handle click resolves to `"move"`; an
  outside-not-on-a-handle click resolves to `None`; a full simulated
  corner-handle drag (`QMouseEvent` press/move/release, mirroring
  `CurveEditor`'s own test helpers) produces the expected new
  fractions and emits `rect_changed`; a full simulated move-drag
  translates the rect without changing its width/height; an
  aspect-locked corner drag produces a square result; a drag that
  would push a handle outside the widget stays clamped and
  non-degenerate; an outside-click-not-on-a-handle drag sequence is a
  verified no-op (no state change, no signal).
- `tests/unit/test_views/test_crop_toolbar.py` (14 tests): combo
  population and order; each named ratio (including `Free`/`Original`)
  emits the correct value; `set_original_ratio` resolves `Original`
  both when selected afterward and when already selected;
  Apply/Cancel buttons emit their signals via `QTest.mouseClick`.
- `tests/ui/test_main_window_crop.py` (6 tests): `_enter_crop_mode`
  with no image shows the status message and never touches
  `ImageView`; with an image, calls `get_export_image(apply_crop=False)`,
  enters crop mode with the current crop state as the initial rect,
  and swaps the toolbars; `_apply_crop` calls `on_crop_changed` with
  the overlay's current rect and exits crop mode; `_cancel_crop` exits
  crop mode without calling `on_crop_changed`; the status-bar
  dimensions label updates after a real crop is applied through
  `ImageController.on_crop_changed` on a real (threaded) controller,
  confirmed via `qtbot.waitSignal(adjustment_state_restored)`.

## 7. Rollout

Purely additive UI: no processor, pipeline, or state-shape change (the
`"crop"` state key and its defaults are unchanged from slice 1). A
plain revert removes the new widgets and the `EditingToolStrip`/
`ToolsPanel`/`ImageView`/`MainWindow` wiring, leaving
`on_crop_changed` exactly as reachable (by tests only) as it was before
this slice. The one behavior-affecting change outside the new widgets
is `get_export_image`'s new optional `apply_crop` parameter, which
defaults to the prior behavior and is additive to every existing call
site.

## 8. Implementation summary

Built `CropOverlay` (`src/views/widgets/crop_overlay.py`) and
`CropToolbar` (`src/views/widgets/crop_toolbar.py`), wired into
`ImageView` (`enter_crop_mode`/`exit_crop_mode`/`is_in_crop_mode`/
`get_crop_overlay`, plus overlay-resize-on-display-update),
`EditingToolStrip`/`ToolsPanel` (enabled Crop button, forwarded
`crop_tool_requested` signal), and `MainWindow` (`_enter_crop_mode`/
`_apply_crop`/`_cancel_crop`/`_on_crop_aspect_ratio_changed`, the
`CropToolbar` instance swapped in for `ImageToolBar`, and the
status-bar dimensions-label live-refresh fix flagged by slice 1).
Added `ImageController.get_export_image(apply_crop: bool = True)`.

**Deviation notes.** (1) The "click outside the rect, not on a handle"
behavior was specified as either a no-op or starting a new rectangle,
"your call" -- the no-op was chosen as the simpler, safer v1 behavior
(see section 1). (2) The task's illustrative `_enter_crop_mode`/
`_apply_crop` sketches were followed essentially as given; the one
addition beyond the sketch is resetting the aspect-lock combo/overlay
state to "Free" on every crop-mode entry, added after noticing a stale
lock would otherwise silently carry over between sessions. (3)
`CropOverlay`'s drag math is split into `_hit_test`/`_apply_drag`/
`_apply_aspect_lock`, each independently unit-tested, per the task's
explicit instruction to keep the drag math in small, named,
independently-testable helpers rather than one large
`mouseMoveEvent`.

**Verification.** New/changed test files: `tests/unit/test_views/
test_crop_overlay.py` (18 passed), `tests/unit/test_views/
test_crop_toolbar.py` (14 passed), `tests/ui/test_main_window_crop.py`
(6 passed) -- all passing in isolated, file-scoped runs, including the
full simulated-drag tests (corner-resize, move, aspect-lock, and
out-of-bounds clamping), which prove the overlay's drag math produces
correct fractions from real `QMouseEvent` press/move/release sequences,
not just from calling its private helpers directly. Full-suite pass
count: see the calling session's own run for the final authoritative
number (per this task's own instruction), since this slice's local run
observed only the pre-existing, documented
`test_geometry_is_restored_on_next_launch` offscreen-platform flake,
deselected per the task's verification command, and no other
regressions in any test that assumed a constant `EditingToolStrip`/
`ImageToolBar`/dimensions-label behavior.
