# Mask tool UI (interactive overlay), slice 2 of 2

Related roadmap: Phase J ("Healing and Masking", PDF sections 21-22),
`docs/planning/PRODUCT_ROADMAP.md`'s Masking bullet. Related prior
slice: `docs/planning/implementation-notes/2026-10-13-mask-processor.md`,
which built the entire data/processing layer this slice drives through
its one public entry point, `ImageController.on_mask_changed(mask)`.
Direct architectural template: `docs/planning/implementation-notes/
2026-10-13-crop-tool-ui.md` and its `CropOverlay`/`CropToolbar`/
`ImageView.enter_crop_mode`/`MainWindow._enter_crop_mode` -- reused as
heavily as possible rather than re-derived from scratch (see section 3.1).

## 1. Problem, goal, and non-goals

This is **slice 2 of 2**. Slice 1 built `MaskProcessor`, full
pipeline/undo-redo/export wiring, and a programmatic
`ImageController.on_mask_changed(mask: Optional[dict])` API, but
explicitly left unbuilt: the interactive drag UI (a draggable gradient
line for linear, a draggable ellipse for radial) and a small panel of
the mask's own Exposure/Contrast/Saturation/Clarity sliders, plus the
disabled "Mask" placeholder in `EditingToolStrip`. This slice builds
exactly that -- two new widgets plus the `ImageView`/`EditingToolStrip`/
`MainWindow` wiring to drive `on_mask_changed` -- and touches no
processor code, and only one small, additive controller change
(`get_export_image`'s new `mask_override` parameter, plus a new
`preview_mask` method -- see section 3.5).

**Non-goals (explicitly out of scope for this slice, mirroring the
crop-tool-ui note's own precedent for stating v1 limitations plainly):**

- **No brush/freehand painting UI.** Slice 1's data model doesn't
  support it either (geometry, not a persisted bitmap) -- a fundamentally
  separate future slice.
- **No multi-mask stack / no list-add-select-delete UI.** Entering mask
  mode always edits THE one mask slot (state key `"mask"`), starting a
  new one with sensible defaults if none exists yet. "Remove Mask"
  clears it entirely (`on_mask_changed(None)`).
- **No radial rotation.** The v1 ellipse is axis-aligned only (`rx`/`ry`
  independently resizable via 4 edge-midpoint handles, no rotation
  handle) -- a reasonable, explicitly-noted future enhancement, matching
  slice 1's own `MaskProcessor` geometry (which never had a rotation
  parameter to begin with).
- **No "start a new shape from an outside click" gesture.** Clicking
  outside the current line/ellipse, not on a handle, is a simple no-op
  -- mirrors `CropOverlay`'s own documented v1 choice exactly (see the
  crop-tool-ui note's section 1 and `test_click_outside_shape_is_a_no_op`
  here).
- **No optimization of mask-mode entry's image fetch.** Unlike crop
  mode, entering mask mode does NOT need a fresh
  `get_export_image(apply_crop=False)` call at all -- see section 3.4 --
  so this slice has no equivalent cost to flag here.
- **Healing** (the other half of Phase J's PDF 21-22 pairing) is
  untouched and entirely separate from this slice, exactly as slice 1
  also noted.

## 2. Current behavior

Before this slice, `ImageController.on_mask_changed` was callable only
from tests/scripts -- `EditingToolStrip`'s "Mask" button was a disabled
placeholder identical to Heal/Transform, and no widget existed to let a
user see or drag a mask's geometry, or adjust its local Exposure/
Contrast/Saturation/Clarity values interactively.

## 3. Design

### 3.1 Reusing `CropOverlay`'s coordinate-math property, directly

`MaskOverlay` is, deliberately, structured as closely as possible to
`CropOverlay`: a `QWidget` with `WA_TranslucentBackground`, a direct
child of `ImageView._image_canvas`, resized/positioned to exactly match
it on every `_update_display()` call. The same property that made
`CropOverlay` tractable applies identically here (see the crop-tool-ui
note's section 3.1 for the full derivation): the canvas's own
`(0, 0)`-to-`(width, height)` local rect IS the displayed, zoomed
pixmap's screen rect at any zoom level, so a pixel position inside the
overlay maps directly to a normalized image fraction via a single
division, with no scroll-offset or zoom correction needed. This is the
entire reason `MaskOverlay`'s `_hit_test`/`_apply_drag` helpers (kept
small and independently unit-tested, exactly mirroring `CropOverlay`'s
own split) can work purely in local pixel space.

### 3.2 `MaskOverlay` (`src/views/widgets/mask_overlay.py`)

A single widget handling BOTH shapes via a `mask_type` property
(`"linear"`/`"radial"`). State is kept for BOTH shapes independently at
all times (`self._x0/_y0/_x1/_y1` for linear, `self._cx/_cy/_rx/_ry/
_feather` for radial, plus a shared `self._invert`), so `set_mask_type`
never discards the other shape's last-known geometry -- switching the
toolbar's combo back and forth (linear -> radial -> linear) always
restores exactly where the user left each one
(`TestTypeSwitchPreservesEachShapesOwnGeometry`).

**Public API**: `set_mask_type`/`set_linear_geometry`/
`set_radial_geometry`/`set_invert` (programmatic, never emit), and
`get_geometry() -> dict`, which returns the CURRENT type's geometry in
exactly the shape `MaskProcessor`/`on_mask_changed` expect
(`"type"`/`"invert"` plus that type's geometry keys) -- deliberately
excluding the 4 adjustment values, which live in `MaskToolbar` and are
merged in by the caller (`MainWindow`) at Apply/preview time. This
mirrors the spec's own separation of concerns: the overlay owns
geometry, the toolbar owns the adjustment sliders.

**Rendering**: Linear draws the 2px line plus 2 circular endpoint
handles, plus a few short, faint perpendicular guide segments at 25%/
50%/75% along the line to hint at the gradient ramp -- a cheap,
optional visual touch (documented as skippable per the spec; kept here
since it added negligible risk). Radial draws the 2px ellipse boundary
plus 4 square edge-midpoint handles (top/bottom/left/right) and one
smaller circular center handle, with explicitly NO rotation handle.

**The radial ellipse's pixel-space math, and why it matches
`MaskProcessor` exactly (the single most important correctness property
in this slice).** `MaskOverlay._ellipse_rect_px()` computes the on-screen
ellipse as `QRectF(cx*w - rx*w, cy*h - ry*h, 2*rx*w, 2*ry*h)`, where `w`/
`h` are THIS WIDGET's own current pixel width/height. This is derived
directly from `MaskProcessor._radial_alpha`'s own normalization: that
processor computes `dx = (px - cx) / rx`, `dy = (py - cy) / ry` in
normalized-fraction space (`px`/`cx` both already fractions of the real
image's width, `py`/`cy` fractions of height), so the ellipse boundary
(`dist == 1`) in PIXEL space sits at `rx * image_width` horizontally and
`ry * image_height` vertically from the center -- exactly the same
per-axis-independent scaling `VignetteProcessor` established and
`MaskProcessor` explicitly reuses (see the mask-processor note's section
3.4). Since this widget's own pixel size always has the same aspect
ratio as the displayed image (the property from section 3.1), scaling
`rx`/`ry` by the WIDGET's width/height is mathematically identical to
scaling them by the IMAGE's width/height -- just expressed against two
differently-sized-but-same-aspect-ratio canvases.

This was not just asserted but verified directly and quantitatively:
`test_mask_overlay.py::TestRadialOverlayMatchesProcessorMath` constructs
the SAME `{cx, cy, rx, ry, feather}` geometry against three different
canvas sizes (square, very wide 2:1, very tall), computes the overlay's
own `_ellipse_rect_px()` bounds, asserts them algebraically equal to
`(cx∓rx)*width`/`(cy∓ry)*height`, and THEN cross-checks against
`MaskProcessor._compute_alpha`'s actual alpha field at that same image
size: a point just inside the overlay's computed horizontal boundary has
alpha `> 0.9` and a point just outside has alpha `< 0.1` (tests `rx` vs.
`width`), and the same check along the vertical axis independently
(tests `ry` vs. `height`). This proves the two per-axis scalings are
checked INDEPENDENTLY, not just "the overall shape looks about right" --
a diagonal-only check could pass even if `rx` and `ry` were silently
swapped or scaled by the wrong dimension.

**Interaction**: mirrors `CropOverlay`'s `_hit_test`/`_apply_drag` split
exactly.
- Linear: `_hit_test` checks the 2 endpoint handles (fixed 10px hit
  radius, matching `CropOverlay`'s own `_HANDLE_HIT_RADIUS_PX`) first,
  then a genuine point-to-segment distance check (`
  _point_segment_distance`, clamping the projection parameter to `[0,1]`
  so a click far past either endpoint, but still "near the infinite
  line," correctly misses) within an 8px tolerance for "click the line
  itself" -> `"move"`, else `None`. Dragging `"start"`/`"end"` moves one
  endpoint; `"move"` translates both endpoints by the same delta
  (anchored at drag-start, exactly like `CropOverlay`'s own move-drag).
  A degenerate (near-zero-length) result is pushed back out to a
  documented minimum floor, `_MIN_LINE_LENGTH_FRACTION = 0.02` (same
  normalized-fraction-space simplification `CropOverlay`'s own
  `_MIN_RECT_SIZE_FRACTION` uses -- not pixel-aspect-corrected, but
  sufficient to guarantee a non-degenerate result; `MaskProcessor`'s own
  zero-length guard, see the mask-processor note's section 3.3, is a
  separate, additional safety net underneath this UI-level floor).
- Radial: `_hit_test` checks the 4 edge handles, then the center handle,
  then "inside the ellipse" (using the same per-axis-scaled check as
  `_ellipse_rect_px`) -> `"move"`, else `None`. Dragging an edge handle
  (`"top"`/`"bottom"`/`"left"`/`"right"`) adjusts only `ry` or `rx`
  respectively, anchored at the fixed center -- e.g. dragging `"right"`
  sets `rx = drag_x_fraction - cx`, leaving `cx`/`cy`/`ry` untouched.
  `"move"` translates `cx`/`cy` by the drag delta, leaving `rx`/`ry`
  untouched. A degenerate (near-zero) radius is clamped to a documented
  floor, `_MIN_RADIUS_FRACTION = 0.02`.

### 3.3 `MaskToolbar` (`src/views/widgets/mask_toolbar.py`)

Mirrors `CropToolbar`'s `QFrame` structure/styling. Contains a type combo
(`"Linear"`/`"Radial"`), an `"Invert"` checkbox, the 4
`AdjustmentSlider` instances (reusing the existing widget class exactly
as `ToolsPanel` already constructs its own sliders, with ranges
confirmed directly from `ImageController._MASK_ADJUSTMENT_RANGES`/the
mask-processor note's section 3.8 -- Exposure `-5.0..5.0`, Contrast/
Saturation/Clarity each `-100.0..100.0`), and Remove Mask/Cancel/Apply
buttons.

`set_values(mask_type, invert, exposure, contrast, saturation, clarity)`
is the programmatic, non-emitting init (mask-mode entry), using a
`self._suppress_signals` flag checked inside each control's own change
handler -- the exact same pattern `ToolsPanel.set_adjustments` already
establishes with its own `_suppress_adjustment_signal` flag (not inside
`AdjustmentSlider` itself, which has no native "set without emit" mode --
confirmed by reading `AdjustmentSlider.set_value`, which always routes
through the spin box and therefore always re-triggers `value_changed`
unless the caller suppresses it one level up, exactly as `ToolsPanel`
already does).

### 3.4 `ImageView` additions

`enter_mask_mode(initial_type, initial_geometry)`/`exit_mask_mode()`/
`is_in_mask_mode()`/`get_mask_overlay()` mirror `enter_crop_mode`/
`exit_crop_mode`/`is_in_crop_mode`/`get_crop_overlay` exactly (lazy
single-instance creation, shown/hidden rather than recreated,
resized/positioned to match the canvas, kept in sync on every
`_update_display()` call while visible). The one deliberate difference
from crop mode: **`enter_mask_mode` does not require (and
`MainWindow._enter_mask_mode` does not perform) any image swap.** Crop
mode needed to show the full UNCROPPED frame under the drag handles
(`get_export_image(apply_crop=False)`) because a previously committed
crop would otherwise hide part of the frame the user needs to see to
re-adjust it. Masking has no equivalent problem: the mask's own effect
is exactly what should be visible while editing it (see section 3.5's
live-preview design), and the canvas already shows the correct, fully-
adjusted image before mask mode is even entered -- so there is nothing
to swap in advance.

### 3.5 The live-preview-vs-commit design decision (the trickiest part of
     this slice)

**The question.** `on_mask_changed`'s own docstring and slice 1's
implementation note are explicit: it is a single, discrete,
`add_to_history=True` commit, "not meant for live-drag spam" (see the
task brief and the mask-processor note's section 1: "a single discrete
commit ... not a continuous slider-style debounce/throttle dance").
Calling it on every drag frame or slider tick would flood the undo
stack with one history entry per mouse-move event -- clearly wrong. So
how does the user SEE the mask's effect while still dragging its
geometry or nudging its sliders, before clicking Apply?

**Investigating the two candidate mechanisms.**

1. **Reuse the existing slider-drag debounce/preview path**
   (`on_adjustments_changed` -> `ThrottledDebouncer` ->
   `_on_throttled_adjustment`/`_on_debounced_adjustment` ->
   `ProcessingWorker.submit_preview_request(..., interactive_preview=
   True)`, which updates `self._image_model.current_image` and presents
   a `DisplayFrame` WITHOUT calling `history_service.execute_command` --
   history only lands later, on `on_slider_released` -> the delayed
   full-resolution commit path). This is the real mechanism every other
   slider in this app already uses for exactly this kind of "live
   preview, commit later" behavior, so it was the first thing
   investigated.

   **Rejected**, for two concrete, code-verified reasons:
   - `apply_adjustments`'s own synchronous, non-threaded
     (`use_threading=False`) fallback branch -- the one actually
     exercised by every unit test that constructs `ImageController`
     without a running `ProcessingWorker` -- **does not call
     `MaskProcessor` at all**. This is explicitly documented as a
     pre-existing, intentional gap in the mask-processor note's section
     3.6 ("one intentional, pre-existing-pattern omission," mirroring
     Crop's own identical gap in that same branch). Reusing this path
     for mask live-preview would make the feature silently do nothing
     under `use_threading=False` -- exactly the test configuration most
     of this codebase's non-UI tests use -- which is both a real
     functional gap and something that would be very easy to ship
     without noticing until someone tried it in that mode.
   - Even setting that aside, every call into `apply_adjustments`/
     `on_adjustments_changed`-style methods PERMANENTLY mutates
     `self._mask_params` (`apply_adjustments` stores `mask_params`
     unconditionally whenever it is not `None`, regardless of
     `add_to_history` -- see `apply_adjustments`'s own code). Using this
     path for a live, in-progress, UNCOMMITTED mask candidate would mean
     the controller's internal "current mask" field tracks the
     candidate, not the last real commit, for the whole duration of the
     editing session. Cancelling would then need to carefully restore
     `self._mask_params` back to its pre-edit value by hand (there is no
     existing "undo a non-historied apply" primitive) -- a second,
     separate source of risk on top of the first.

2. **A genuinely separate, lighter-weight, display-only preview path**
   that never touches `self._mask_params`, `self._image_model
   .current_image`, or history at all. **Chosen.**

**The chosen design.** `ImageController.get_export_image` gained one new
optional parameter, `mask_override` (defaulting to a private `_UNSET`
sentinel, distinct from both `None` and `{}` -- both of which are
legitimate override VALUES a caller might want). When passed, it is used
IN PLACE OF `self._mask_params` for that one recompute only;
`self._mask_params` itself is never read-modified. `get_export_image`
was already, by its own pre-existing docstring, "always correct"
precisely because it recomputes the ENTIRE pipeline directly from the
true original image on every call, synchronously, regardless of
`self._use_threading` -- this is the same property that already made it
the right tool for crop mode's own full-frame preview need. A new,
tiny, public method, `ImageController.preview_mask(mask)`, wraps this:
normalize/clamp the candidate (reusing `_normalize_mask_state`, so a
mid-drag value momentarily outside `[0, 1]` can never reach the
processor un-clamped), call
`get_export_image(mask_override=normalized)`, and hand the result
straight to `ImageView.set_image(..., emit_loaded=False,
preserve_view_scale=True)` -- the exact same call `_enter_crop_mode`
already uses to show a "not the currently-committed state" preview
image.

`MainWindow._on_mask_editing_changed` (wired to the overlay's
`geometry_changed` signal and the toolbar's `mask_type_changed`/
`invert_changed`/`adjustments_changed` signals -- every source of an
in-progress change) assembles the current candidate (`overlay
.get_geometry()` merged with `toolbar.get_adjustments()`) and calls
`preview_mask(candidate)`. This can be called any number of times --
every drag frame, every slider tick -- with zero accumulating cost
beyond the one recompute itself, and zero risk of ever being mistaken
for, or leaving a stray trace in, a real edit.

**Why this resolves `_cancel_mask` trivially, too.** Because
`preview_mask` never touches `self._mask_params` or
`self._image_model.current_image`, there is NOTHING to roll back on
cancel beyond hiding the overlay/toolbar. `_cancel_mask` simply calls
`ImageController.refresh_view()` (an existing, already-public method
that re-displays whatever `self._image_model.current_image` currently
holds) -- which is still exactly the pre-edit image, because nothing
ever changed it. This is simpler, and strictly safer, than crop mode's
own `_cancel_crop`, which must perform a second real
`get_export_image()` recompute specifically because `_enter_crop_mode`
HAD swapped in a different (uncropped) display image that needs
explicit reverting. `TestCancelMaskNoNetChange` in
`tests/ui/test_main_window_mask.py` verifies this directly: it commits a
real mask via `on_mask_changed`, enters mask mode, simulates in-progress
editing (a slider tweak AND a geometry drag's programmatic equivalent),
cancels, and asserts `get_adjustment_state()["mask"]` is byte-for-byte
identical before and after -- not merely "close enough."

`_apply_mask` is the one place `on_mask_changed` is still called, exactly
once, with the final assembled candidate -- the single real, committed,
undoable edit the task brief asks for. `TestApplyMask` asserts
`on_mask_changed` is called exactly once (via `assert_called_once()`),
with the exact assembled dict.

### 3.6 `EditingToolStrip` / `ToolsPanel` -- enabling the "Mask" button

`EditingToolStrip` gained a `mask_tool_requested` signal, emitted by the
now-enabled Mask button (Heal/Transform remain untouched, disabled
placeholders) -- mirrors exactly how `crop_tool_requested` was added in
the prior slice. `ToolsPanel` forwards it outward as its own
`mask_tool_requested`, the same direct re-emit pattern already used for
`crop_tool_requested`.

### 3.7 `MainWindow` wiring

`_enter_mask_mode`: bails with a status-bar message if no image is
loaded. Otherwise, if Crop mode happens to be active, cancels it first
(`_cancel_crop()`) -- see section 5's mutual-exclusivity discussion.
Reads `get_adjustment_state()["mask"]`; if a mask already exists, its
type/invert/geometry/adjustments seed the overlay and toolbar; if not,
sensible defaults are used (a linear gradient roughly across the middle
third of the frame, `x0=0.3,y0=0.5,x1=0.7,y1=0.5`, or if the toolbar's
last-selected type were radial, `cx=cy=0.5, rx=ry=0.25, feather=0.5` --
both are `MaskOverlay`'s own built-in constructor defaults, so
`MainWindow` only needs to pass through whatever `get_adjustment_state`
gives it, falsy-or-not). The overlay's `geometry_changed` signal is
connected to `_on_mask_editing_changed` lazily, once, the first time the
(lazily-created) overlay instance exists -- guarded by
`self._mask_overlay_signal_connected` so re-entering mask mode never
double-connects the same persistent overlay instance.

`_apply_mask`/`_cancel_mask`/`_remove_mask`/`_on_mask_editing_changed`:
see section 3.5. `_on_mask_type_changed`/`_on_mask_invert_changed`
additionally forward the toolbar's combo/checkbox changes onto the
overlay itself (`overlay.set_mask_type`/`set_invert`) before triggering
a live-preview refresh, so switching the combo immediately redraws the
overlay in its new shape AND updates the live preview to match.

## 4. Contracts

- `MaskOverlay.set_mask_type(mask_type)`/`set_linear_geometry(x0,y0,x1,
  y1)`/`set_radial_geometry(cx,cy,rx,ry,feather)`/`set_invert(invert)`:
  programmatic setters, never emit `geometry_changed`.
- `MaskOverlay.get_geometry() -> dict`: the CURRENT type's geometry
  only (`"type"`/`"invert"` + that type's keys) -- never the 4
  adjustment values.
- `MaskOverlay.geometry_changed = pyqtSignal(dict)`: emitted continuously
  during a user drag, with the same shape as `get_geometry()`.
- `MaskToolbar.set_values(mask_type, invert, exposure, contrast,
  saturation, clarity)`: programmatic init, no signal emission.
- `MaskToolbar.get_adjustments() -> dict`:
  `{"exposure","contrast","saturation","clarity"}`.
- `MaskToolbar.mask_type_changed`/`invert_changed`/
  `adjustments_changed`/`remove_requested`/`apply_requested`/
  `cancel_requested`: see section 3.3/the module docstring.
- `ImageView.enter_mask_mode(initial_type, initial_geometry)`/
  `exit_mask_mode()`/`is_in_mask_mode() -> bool`/`get_mask_overlay() ->
  Optional[MaskOverlay]`.
- `ImageController.get_export_image(apply_crop=True, mask_override=
  _UNSET)`: new optional parameter, a private sentinel default so every
  existing call site (which never passes it) is completely unaffected.
  When passed (even explicitly `{}`/`None`), used instead of
  `self._mask_params` for that one recompute, which is never itself
  mutated.
- `ImageController.preview_mask(mask: Optional[dict]) -> None`: new
  public, display-only, non-historied, non-mutating live-preview entry
  point. Safe to call any number of times in a row.
- `EditingToolStrip.mask_tool_requested`/`ToolsPanel.mask_tool_requested`:
  forwarded, no payload.

## 5. Nuances and failure modes

**Crop/Mask mutual exclusivity.** The two interactive modes can never be
simultaneously active. `MainWindow._enter_mask_mode` calls
`self._cancel_crop()` first if `self._image_view.is_in_crop_mode()`;
symmetrically, `_enter_crop_mode` now calls `self._cancel_mask()` first
if `self._image_view.is_in_mask_mode()`. Neither commits the mode being
exited -- entering one tool while mid-edit on the other always discards
that other edit, exactly like clicking its own Cancel button would.
Verified directly in `tests/ui/test_main_window_mask.py::
TestCropMaskMutualExclusivity`, asserting `is_in_crop_mode()`/
`is_in_mask_mode()` are never simultaneously `True` in either entry
direction.

**The radial overlay's ellipse math must track `MaskProcessor`'s own
scaling EXACTLY, or the user would be dragging a shape that doesn't
match what gets rendered.** See section 3.2's extended discussion;
verified with a dedicated, parametrized (3 very different aspect
ratios), numerically-cross-checked-against-the-real-processor test, not
a visual check.

**The chosen live-preview mechanism recomputes the FULL image on every
call**, exactly like `get_export_image` always has for crop mode and
export -- there is no incremental/partial-recompute optimization here.
For a very large source image, dragging a mask handle could feel less
smooth than the global slider's own throttled/debounced worker-thread
path. This is an accepted, documented v1 cost (the same category of
cost crop mode's own full-frame fetch already accepted) -- a future
optimization could route mask-mode live preview through the
`ProcessingWorker`'s own interactive-preview tier instead, once that
worker's `apply_adjustments`-sync-fallback gap (section 3.5's first
rejected-mechanism finding) is separately closed.

**`_normalize_mask_state` is reused, not reinvented, for live-preview
clamping.** `preview_mask` calls the exact same private normalizer
`on_mask_changed` already uses, so a mid-drag geometry value's clamping
behavior is identical between the live preview and the final committed
result -- there is no separate, possibly-inconsistent "preview-only"
clamping path.

**Re-entering mask mode after a prior session's Apply/Cancel/Remove
always reflects the CURRENT real state**, since `_enter_mask_mode`
always re-reads `get_adjustment_state()["mask"]` fresh on every entry
(no stale cached geometry carried across sessions, the same principle
`_enter_crop_mode`'s own aspect-lock reset already established for
Crop).

## 6. Test plan

- `tests/unit/test_views/test_mask_overlay.py` (32 tests): geometry get/
  set round-trips for both types without emitting; type-switch preserves
  each shape's own independent last geometry; simulated full mouse drags
  (press/move/release) for a linear endpoint handle, a linear line-click
  move-drag (both endpoints translate by the same delta), a radial edge
  handle (resizes one radius only, center/other radius unchanged), a
  radial move-drag (center translates, radii unchanged); degenerate-drag
  clamping for both shapes (cannot collapse to zero length/zero radius);
  an outside-click-not-on-a-handle no-op; and
  **`TestRadialOverlayMatchesProcessorMath`**, the single most important
  correctness test in this slice (see section 3.2), parametrized across
  3 very different image aspect ratios and cross-checked directly
  against `MaskProcessor._compute_alpha`'s real alpha field.
- `tests/unit/test_views/test_mask_toolbar.py` (23 tests): slider
  construction/ranges match `ImageController._MASK_ADJUSTMENT_RANGES`
  exactly; `set_values` round-trips without emitting; each control
  change emits the right signal with the right payload; Apply/Cancel/
  Remove emit their signals via `QTest.mouseClick`.
- `tests/ui/test_main_window_mask.py` (9 tests): `_enter_mask_mode` with
  no image shows the right status message and never touches
  `ImageView`; with an image, initializes the overlay+toolbar from
  current state (and separately, from sensible defaults when no mask
  exists); `_apply_mask` commits exactly once via `on_mask_changed` with
  the assembled geometry+adjustments and exits mask mode; `_remove_mask`
  commits `None` and exits; crop/mask mutual exclusivity in both
  directions (asserted directly via `is_in_crop_mode()`/
  `is_in_mask_mode()`, never both `True`); `_cancel_mask` after
  real in-progress editing leaves the real, committed
  `get_adjustment_state()["mask"]` byte-for-byte unchanged; and the
  live-preview mechanism's "realness" is proven, not assumed --
  `TestLivePreviewWhileEditing` loads a real image through a real,
  default-threaded `ImageController`, tweaks the Exposure slider while
  in mask mode with no mask ever committed, and asserts the displayed
  `QImage` genuinely changed while `get_adjustment_state()["mask"]`
  stayed `None` throughout.

## 7. Rollout

Purely additive UI, plus one small, fully backward-compatible
`ImageController` addition: a new optional `get_export_image` parameter
(default preserves every existing call site's behavior exactly) and a
new `preview_mask` method (never called by any pre-existing code path).
No state-shape or pipeline change -- the `"mask"` state key and
`on_mask_changed`'s own contract are completely unchanged from slice 1.
A plain revert removes the two new widgets, the `ImageView`/
`EditingToolStrip`/`ToolsPanel`/`MainWindow` wiring, and the
`get_export_image`/`preview_mask` additions, leaving `on_mask_changed`
exactly as reachable (by tests only) as it was before this slice.

## 8. Implementation summary

Built `MaskOverlay` (`src/views/widgets/mask_overlay.py`) and
`MaskToolbar` (`src/views/widgets/mask_toolbar.py`), wired into
`ImageView` (`enter_mask_mode`/`exit_mask_mode`/`is_in_mask_mode`/
`get_mask_overlay`, plus overlay-resize-on-display-update),
`EditingToolStrip`/`ToolsPanel` (enabled Mask button, forwarded
`mask_tool_requested` signal), and `MainWindow` (`_enter_mask_mode`/
`_apply_mask`/`_cancel_mask`/`_remove_mask`/`_on_mask_editing_changed`/
`_on_mask_type_changed`/`_on_mask_invert_changed`, the `MaskToolbar`
instance swapped in for `ImageToolBar`, and the Crop/Mask mutual-
exclusivity checks in both `_enter_crop_mode` and `_enter_mask_mode`).
Added `ImageController.get_export_image`'s new `mask_override` parameter
and the new `ImageController.preview_mask` method (section 3.5).

**Deviation notes.**

1. The live-preview mechanism (section 3.5) is a genuine, deliberate
   departure from "just reuse the slider debounce path" -- justified in
   depth above, with two concrete, code-verified reasons for rejecting
   that reuse (the non-threaded sync-fallback's mask-skip gap, and the
   unconditional `self._mask_params` mutation every `apply_adjustments`
   call makes regardless of `add_to_history`). This was explicitly
   flagged by the task brief as "a real design decision ... not a minor
   detail," and resolved by introducing a new, narrowly-scoped,
   side-effect-free preview primitive rather than extending the existing
   slider-preview machinery to cover a case it wasn't built for.
2. The linear overlay's "faint parallel guide lines" visual touch was
   kept (not skipped) -- it was cheap and low-risk once the line's own
   direction vector was already being computed for hit-testing, so there
   was no meaningful extra complexity to avoid.
3. `MaskOverlay`'s drag math is split into `_hit_test`/`_apply_linear_
   drag`/`_apply_radial_drag`/`_point_segment_distance`/
   `_ellipse_rect_px`, each independently unit-tested, per the task's
   explicit instruction (mirroring `CropOverlay`'s own
   `_hit_test`/`_apply_drag`/`_apply_aspect_lock` split).
4. No other deviation of substance from the task's design spec for the
   widget APIs, signal shapes, or `MainWindow` wiring.

**Verification.** New/changed test files: `tests/unit/test_views/
test_mask_overlay.py` (32 passed), `tests/unit/test_views/
test_mask_toolbar.py` (23 passed), `tests/ui/test_main_window_mask.py`
(9 passed) -- all passing in isolated, file-scoped runs, including the
radial-overlay-vs-processor cross-check (parametrized across 3 image
aspect ratios) and the real-controller live-preview/no-net-change-on-
cancel tests. Also reran the full prior crop-tool-ui test files
(`test_crop_overlay.py`, `test_crop_toolbar.py`,
`test_main_window_crop.py`) plus `test_image_controller.py` and all of
`tests/unit/test_views/` together (395 passed) to confirm no regression
from the `get_export_image` signature change or the new Crop/Mask
mutual-exclusivity checks. Full-suite pass count: see the calling
session's own run for the final authoritative number (per this task's
own instruction), since this slice's own local run observed only the
same pre-existing, documented `test_geometry_is_restored_on_next_launch`
offscreen-platform flake already noted in every prior implementation
note (deselected, not fixed, per the task's own verification command),
and no other regressions in any test that assumed a constant
`EditingToolStrip`/`get_export_image` signature, `MainWindow` toolbar-
visibility behavior, or `ImageController` internal state shape.
