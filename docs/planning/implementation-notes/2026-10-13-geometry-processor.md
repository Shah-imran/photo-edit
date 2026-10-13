# Geometry processor -- Distortion, Vertical/Horizontal perspective, Scale, X/Y Offset

Related roadmap: Phase I ("Geometry and Crop", PDF sections 19-20),
`docs/planning/PRODUCT_ROADMAP.md`'s row 19-20. Related prior slices:
`docs/planning/implementation-notes/2026-10-12-straighten.md` (the
direct template for this slice -- the "shape-preserving, zero-is-
identity, `BORDER_REFLECT_101`" discipline this processor also follows,
and the exact pipeline position -- immediately before Mask/Crop -- this
slice slots in next to) and
`docs/planning/implementation-notes/2026-10-13-crop-processor.md` (the
pipeline-wiring checklist this slice re-threads end to end: controller
state, `ProcessingRequest`/`ProcessingQueue`, `ProcessingWorker`,
`CombinedAdjustmentCommand`, `ToolsPanel`).

## 1. Problem, goal, and non-goals

Phase I's slider-based "Geometry" half was left half-finished by the
Straighten slice: only the small-angle-rotation slider existed.
`docs/planning/PRODUCT_ROADMAP.md` row 19 lists five more sliders this
closes out: **Distortion**, **Vertical** and **Horizontal** perspective,
**Scale**, and **X/Y Offset**. All five are plain, non-interactive
sliders -- no draggable overlay, no new `ImageController` entry point
beyond the existing generic `on_adjustments_changed` flat-dict path --
making this a much smaller slice than Crop/Mask/Healing.

**Explicitly NOT built here (a real, deliberate scope cut, not an
oversight):**

- **Upright modes** (Off/Auto/Guided/Level/Vertical/Full). Lightroom's
  Auto/Level/Vertical/Full modes use vanishing-point/horizon detection
  (a computer-vision model fit to the image's own line structure) to
  *compute* vertical/horizontal/distortion/scale automatically; Guided
  mode asks the user to draw 2-4 reference lines and solves a
  homography from those. Both need substantially more machinery than a
  slider processor -- a line/edge detector and a least-squares
  homography solve for Auto/Level/Vertical/Full, and a dedicated
  click-two-points-per-line overlay UI for Guided -- and are deferred
  as a separate, much larger future slice. This mirrors the precedent
  already set in this roadmap for Masking's deferred brush masks and
  Healing's deferred per-spot editing: a real, intentional cut, called
  out explicitly in the roadmap table, not silently missing.
- **"Constrain Crop."** This is a checkbox that, when a geometry
  correction leaves transparent/reflected corners exposed, automatically
  tightens the active crop rectangle so the exported frame excludes
  them. It depends on computing the exact valid-pixel quadrilateral
  left by an arbitrary combination of this slice's five warps (and, once
  it exists, Upright) and feeding that into `CropProcessor`'s rectangle
  -- a cross-cutting feature connecting two processors' state, not a
  property of `GeometryProcessor` alone. Deferred alongside Upright.
- **The underlying math is not a camera-calibration-grade lens-profile
  correction.** Distortion uses a single-term (`k1`-only) radial model
  with no lens-profile database (unlike Lightroom's actual Profile-based
  corrections) -- this slider corrects *generic* barrel/pincushion
  curvature a user dials in by eye, exactly as the PDF spec's simple
  "Distortion" slider (not "Enable Profile Corrections") describes.

## 2. Design

### 2.1 One processor for all five sliders

Unlike Straighten (its own dedicated processor, because it is
conceptually and mathematically distinct -- a pure rigid rotation),
these five parameters are naturally one processor,
`GeometryProcessor` (`src/processors/geometry_processor.py`), the same
way Tonal already bundles Highlights/Shadows/Whites/Blacks and Color
bundles Saturation/Vibrance: they are all "fix the as-shot lens/
perspective geometry" controls that commonly get touched together (a
wide-angle shot typically needs some Distortion AND some Vertical
correction at once), and bundling them lets the four
perspective/scale/offset sliders share **one** resample pass instead of
one per slider (see 2.3).

`GeometryProcessor.process(image, distortion=0.0, vertical=0.0,
horizontal=0.0, scale=100.0, offset_x=0.0, offset_y=0.0)` mirrors
`StraightenProcessor`'s exact shape-preservation discipline: output
`(H, W, C)` is byte-identical in shape to the input, at every parameter
combination including the extremes, and all-defaults short-circuits to
`source.copy()` with no matrix built and no `cv2` call made at all (the
same "zero-cost identity, and an exact identity test" convention
Straighten set).

### 2.2 Distortion -- single-term radial model

Distortion is implemented as its own `cv2.remap` pass (not part of the
combined homography below, since it is non-linear and a plain 3x3
matrix cannot express it):

- A synthetic camera matrix: `fx = fy = max(width, height)`, principal
  point `(cx, cy)` at the image center.
- For each OUTPUT pixel, normalize its coordinates
  (`xn = (x - cx) / fx`, `yn = (y - cy) / fy`), compute
  `radial = 1 + k1 * (xn^2 + yn^2)`, and sample the SOURCE pixel at
  `(xn * radial * fx + cx, yn * radial * fy + cy)` via
  `cv2.remap(..., borderMode=cv2.BORDER_REFLECT_101)`. This is the
  standard single-term Brown-Conrady radial model, evaluated directly
  rather than through `cv2.undistort` (which expects a *distorted*
  source and a separately-chosen output camera matrix -- evaluating the
  formula directly keeps the sign convention and the `r=0` identity
  behavior explicit).
- **Sign convention, verified empirically** (not assumed -- the same
  "verify first" discipline Straighten's own sign convention and Remove
  CA/Color NR/Defringe's tiny-image behavior used): the internal
  `k1 = -(distortion / 100.0) * 0.35`. The negated relationship was
  chosen so the USER-FACING slider matches the spec's required
  convention ("negative corrects barrel, pulling edges in; positive
  corrects pincushion, pushing edges out"), which was checked directly
  by rendering two full-height vertical lines through the processor and
  measuring their spacing at the image's top edge vs. its vertical
  center (`tests/unit/test_processors/test_geometry_processor.py`'s
  `test_negative_distortion_pulls_edge_content_inward`/
  `test_positive_distortion_pushes_edge_content_outward`). A lone
  hot-pixel marker was tried first and rejected: bilinear interpolation
  of a single pixel under a non-linear remap spreads/dims it
  asymmetrically, making its post-warp peak position too noisy to
  assert on reliably -- full lines (gradients across many pixels) give
  a stable, unambiguous measurement, the same lesson Straighten's own
  marker-pixel tests didn't need to learn (a pure rotation doesn't blur
  a marker the way a space-varying radial remap does).
- **Constant tuning** (`_DISTORTION_K = 0.35`): chosen so the slider's
  extremes (`+/-100`) produce a clearly visible but bounded warp. On a
  101x101 reference image, a corner pixel at `(99, 99)` under
  `distortion=-100` moves by roughly 8-9 px (about 8-9% of the
  half-diagonal) -- visible, not absurd. Verified directly in
  `test_distortion_extreme_displacement_is_sane_not_absurd` (bounds
  `1.0 <= displacement <= 25.0` px on a 101px-wide image).
- At the extreme `|distortion| = 100` on a 1-pixel-wide/tall image, the
  formula is still well-defined (`cx = cy = 0`, `fx = fy = 1`, and the
  single pixel's `r = 0` maps to itself exactly) -- no special case
  needed, matching Straighten's own "verify, don't special-case" tiny-
  image precedent.

### 2.3 Vertical/Horizontal perspective, Scale, Offset -- one combined homography

These four are each expressed as their own 3x3 matrix, over the image's
own corners/center, and then COMPOSED into a single matrix via plain
matrix multiplication before ONE `cv2.warpPerspective` call -- rather
than resampling once per active slider, which would compound
interpolation softening every time more than one of these four is
touched (a very common case: a wide shot typically needs both Vertical
and some Scale/Offset reframing together).

- **Vertical** (`_vertical_matrix`): a keystone/perspective correction
  via `cv2.getPerspectiveTransform`, mapping the image's own 4 corners
  to a quadrilateral where the top edge's two corners shift horizontally
  toward each other (or apart) and the bottom edge's shift the opposite
  way, by `shift = (vertical / 100) * 0.4 * (width / 2)`. **Verified
  sign convention** (same line-based measurement technique as
  Distortion, `tests/.../test_geometry_processor.py`'s
  `test_positive_vertical_narrows_top_widens_bottom` /
  `test_negative_vertical_widens_top_narrows_bottom`): positive
  `vertical` narrows the top edge and widens the bottom (adds/
  exaggerates the "camera tilted up at a tall subject" convergence
  look); negative widens the top and narrows the bottom (the common
  real-world correction direction -- pulling converging verticals back
  toward parallel).
- **Horizontal** (`_horizontal_matrix`): the exact same construction,
  rotated 90 degrees -- tilts the left/right edges' heights in opposite
  directions instead of the top/bottom edges' widths.
- The `0.4` maximum-shift fraction (`_PERSPECTIVE_MAX_FRACTION`) keeps
  the mapped quadrilateral from ever self-intersecting (a corner
  crossing the image's own center line), even at the slider's `+/-100`
  extreme, and is skipped entirely (treated as identity) for a
  1-pixel-wide or 1-pixel-tall image, where `width - 1 == 0` or
  `height - 1 == 0` makes two of the four source corners coincide --
  `cv2.getPerspectiveTransform`'s 4-point solve is singular there and
  returns a NaN-filled matrix (verified directly, then guarded, rather
  than assumed). A 1xN/Nx1 image has no meaningful "top/bottom" or
  "left/right" edge to tilt in the first place, so skipping rather than
  special-casing a fallback matrix is both correct and simpler.
- **Scale** (`_scale_matrix`): `cv2.getRotationMatrix2D(center, 0,
  scale / 100)` -- a zero-rotation call used purely for its "scale
  around an arbitrary center" affine construction, extended to a 3x3
  homography by appending `[0, 0, 1]`. Verified directly (not assumed)
  that `cv2.warpPerspective` with this matrix behaves as the intuitive
  "forward" mapping: a point at a given distance from center moves
  FURTHER from center under `scale > 100` and CLOSER under
  `scale < 100` -- i.e. `scale=150` genuinely zooms in, `scale=50`
  zooms out, matching the spec directly with no sign inversion needed
  (unlike Distortion/Vertical/Horizontal, which all needed an empirical
  check to pin down).
- **Offset** (`_offset_matrix`): a plain pixel-space translation matrix,
  `tx = (offset_x / 100) * width`, `ty = (offset_y / 100) * height`.
  Verified the same way: positive `offset_x`/`offset_y` shift image
  content right/down.
- **Composition order**: `offset @ scale @ vertical @ horizontal`
  (applied to a point in that order: horizontal first, then vertical,
  then scale, then offset) -- perspective corrections first (closer to
  "undo the as-shot lens/viewpoint geometry"), framing adjustments
  (scale/offset, closer to "now reframe the corrected result") last.
  This is a reasoned default, not a spec-mandated order; any other
  ordering of these four is an equally valid design choice, and this
  slice does not claim Lightroom's own internal composition order is
  identical.
- Every one of the four border-fills any newly exposed area with
  `cv2.BORDER_REFLECT_101` -- the same convention every geometric
  processor in this codebase already uses (Straighten, Remove CA).

### 2.4 Pipeline position: immediately before Straighten

`GeometryProcessor` runs immediately BEFORE `StraightenProcessor` in
every one of the five places `StraightenProcessor.process` was already
being called (`ImageController.get_export_image`,
`ImageController.restore_adjustment_state`'s recompute chain, both
branches of `ImageController.apply_adjustments` --
`CombinedAdjustmentCommand.execute()` for the history/threaded path and
the inline synchronous-fallback chain -- and
`ProcessingWorker._apply_adjustments`). The rationale, extending the
comment already present above Straighten's own call sites: Geometry
corrects as-shot lens/perspective distortion, a property of the
original capture; Straighten is the user's own final small-angle
rotation tweak, conceptually applied AFTER the frame has already been
rectified by Geometry, not before. Geometry (like Straighten) runs
after Healing and every color/tonal/effects/detail/optics adjustment,
and before Mask and Crop -- so a mask's geometry and the crop rectangle
are always expressed in the same post-Geometry, pre-mask/crop frame
Straighten already established.

## 3. Controller/pipeline wiring

Threaded through every spot `dehaze_params`/`straighten_params` already
flow through, with its own `geometry_params` dict (all 6 keys together,
since this is one processor with one params dict -- not split per-key
the way `tonal_params` bundles 4 keys for one `TonalProcessor`):

- `ImageController._ADJUSTMENT_DEFAULTS`: `distortion`/`vertical`/
  `horizontal`/`offset_x`/`offset_y` default to `0.0`; `scale` defaults
  to `100.0` (its own identity value, not `0.0`). A new
  `_GEOMETRY_DEFAULTS` dict (mirroring `_CROP_DEFAULTS`'s existing
  "pull the identity subset out" precedent) is used everywhere code
  needs to ask "is Geometry at its identity" without assuming every key
  defaults to zero -- `restore_adjustment_state`'s `has_changes` check
  and `_has_pending_adjustment_changes` both needed this fix (see 3.1).
- `self._geometry_processor` / `self._geometry_params: Dict[str,
  float] = {}` -- same shape as `_dehaze_params`, reset everywhere the
  other `_xxx_params` fields are reset (`_apply_loaded_image`,
  `reset_to_original`).
- `get_export_image`, `restore_adjustment_state`'s recompute chain,
  `apply_adjustments`'s synchronous-fallback branch, and
  `CombinedAdjustmentCommand.execute()` (in
  `src/commands/adjustment_commands.py`) all call
  `self._geometry_processor.process(result, **self._geometry_params)`
  immediately before the existing Straighten call.
- `apply_adjustments(..., geometry_params=None, ...)`,
  `ProcessingRequest.geometry_params`,
  `ProcessingQueue.create_request(..., geometry_params=None, ...)`,
  and `ProcessingWorker.submit_request`/`submit_preview_request`/
  `submit_final_request`/`_apply_adjustments`/`_cache_key`/
  `_adjustment_signature` all gained a `geometry_params` parameter/field
  in exactly the same position (immediately after `defringe_params`,
  before `straighten_params`) Dehaze/Straighten's own kwargs already
  occupy, so the worker's non-identity skip-check
  (`geometry_params and (any of the 6 keys != its own default)`),
  cache key, and signature all cover it the same way every other
  adjustment already is.

### 3.1 A real bug class this slice had to account for: `scale`'s non-zero identity

Every existing flat key in `_ADJUSTMENT_DEFAULTS` defaults to `0.0`,
so two existing checks took a shortcut: `any(value != 0.0 for value in
normalized.values())` (in `restore_adjustment_state`) and
`any(v != 0 for v in self._xxx_params.values())` (the equivalent
per-field check inside `_has_pending_adjustment_changes`). Geometry's
`scale` defaults to `100.0`, not `0.0` -- so a geometry state sitting
exactly at its own identity (`scale=100`, every other key `0`) would
have been incorrectly flagged as "has changes" by the bare `!= 0.0`
check, the same way a straight port of Crop's own non-zero-identity
rectangle would have broken that pattern had it not already gotten its
own dedicated `_is_identity_crop` helper. Both checks are now compared
against each key's own default (`_ADJUSTMENT_DEFAULTS`/
`_GEOMETRY_DEFAULTS` respectively) instead of a bare literal `0.0`.
`test_geometry_scale_identity_alone_is_not_a_pending_change` in
`tests/unit/test_controllers/test_image_controller.py` exercises this
exact bug class directly.

## 4. UI wiring

`src/views/tools_panel.py`'s existing "Geometry" section (previously
holding only the Straighten slider) gained 5 more `AdjustmentSlider`s,
in the order Distortion, Vertical, Horizontal, Scale, X Offset,
Y Offset (placed after Straighten, since Geometry's corrections are
conceptually a pre-step the user dials in before the final Straighten
tweak, even though the pipeline itself runs Geometry first -- the UI
ordering here is about editing workflow, not the processing order).
Every one of the 5 new sliders is wired through the exact same plumbing
Straighten's own slider already uses (grepped and replicated at each of
Straighten's 5 own call sites): `AdjustmentSlider` construction +
`content_layout.addWidget`, the "Reset Geometry" button (now resetting
all 7 Geometry sliders, not just Straighten), `value_changed`/
`slider_released` signal connections, `_adjustments` dict defaults,
`set_adjustments`'s merge-and-restore (including `set_value` on
restore), and `set_enabled`.

**No `on_geometry_changed` controller method, and no `MainWindow`
changes, were needed.** Unlike Crop/Mask/Healing (which each got their
own `on_X_changed` entry point because they are driven by a discrete,
non-continuous interactive gesture -- a drag-release, a click-to-place),
Straighten and these 5 new sliders are *plain global sliders*, exactly
like Dehaze/Texture/Clarity. Tracing Straighten's own signal path
end to end confirmed it never got (or needed) a dedicated
`on_straighten_changed`: `ToolsPanel`'s generic `adjustments_changed`
signal already carries the whole flat adjustments dict (keyed by
slider name) straight to `MainWindow._on_adjustments_changed`, which
forwards it unchanged to `ImageController.on_adjustments_changed`,
which builds each processor's own params sub-dict (including, now,
`geometry_params`) from that one shared dict. `on_adjustments_changed`
already implements the live-preview-while-dragging + commit-on-release
pattern (route through the throttled/debounced worker while dragging;
`ToolsPanel.slider_released` -> `MainWindow._on_slider_released` ->
`ImageController.on_slider_released` triggers the full-resolution
commit, pushing an `AdjustmentStateCommand` onto undo/redo) for every
key already in that dict -- adding 6 more keys to it, and reading them
back out in `on_adjustments_changed`/`_on_throttled_adjustment`/
`_on_debounced_adjustment`/`on_slider_released`/
`_submit_delayed_final_render`/`_has_pending_adjustment_changes`/
`commit_adjustments` the same way `straighten` already is, was
sufficient. No new signal, no new `MainWindow` slot, and no bespoke
preview/commit split were written for this slice, because the existing
generic plain-slider path already did everything a `geometry` key
needed.

## 5. Test plan

- `tests/unit/test_processors/test_geometry_processor.py`: all-defaults
  identity (both implicit and with every default passed explicitly),
  shape preservation at every parameter (including every extreme, both
  individually and combined) and on tiny (1x1/2x2/non-square-tiny)
  images, dtype/determinism, per-parameter sign-convention tests for
  all 5 sliders (line-based for Distortion/Vertical/Horizontal, marker-
  based for Scale/Offset, per 2.2/2.3's own reasoning for why), range
  clamping for all 5, border-fill-not-black checks for Scale-down and
  Offset, a headroom/no-clipping check for Distortion, and combined-
  parameter tests confirming the composed result differs from any
  single parameter applied alone.
- `tests/unit/test_controllers/test_image_controller.py`
  (`TestImageControllerGeometry`): state round-trip through
  `get_adjustment_state()`/`restore_adjustment_state` for all 6 keys,
  identity defaults when Geometry is absent from a restored state, an
  undo-restores-previous-image check, the `scale`-identity-is-not-a-
  pending-change regression from 3.1, and a pipeline-ordering
  regression (Geometry alone vs. Geometry+Straighten combined both
  differ from a plain unmodified export, mirroring this file's existing
  Healing-vs-Exposure/Healing-vs-Crop ordering-regression tests' style).
- `tests/unit/test_views/test_tools_panel.py`
  (`TestToolsPanelGeometry`, extended): parametrized range/default/
  signal and restore-without-emitting checks across all 5 new sliders
  plus Straighten, a reset-check confirming all 6 Geometry sliders (and
  only those) reset together, and a `set_enabled(False)` check.
- Full existing suite re-run end to end (`pytest`, offscreen Qt
  platform) to confirm no regression in Crop/Mask/Healing/Straighten's
  own pipeline-ordering and state-persistence tests, which this slice's
  pipeline-position and `_ADJUSTMENT_DEFAULTS` changes touch directly.

## 6. Rollout

Additive and backward-compatible: a persisted adjustment-state dict (an
old catalog entry, an exported preset) that has no `distortion`/
`vertical`/`horizontal`/`scale`/`offset_x`/`offset_y` keys at all
restores every one of them to its own identity value via
`_normalize_floats`' existing missing-key-falls-back-to-default
behavior, so old saved edits render identically to before this slice.

## 7. Summary

`GeometryProcessor` fills in the remaining slider-based half of Phase
I's "Geometry" row: Distortion (a single-term radial `cv2.remap`),
Vertical/Horizontal perspective and Scale/Offset (one composed 3x3
homography per `cv2.warpPerspective` call), threaded through every
existing pipeline/undo-redo/export/UI wiring point Dehaze and Straighten
already establish, running immediately before Straighten and after
every other adjustment. Upright modes and "Constrain Crop" remain an
explicit, documented gap -- both need vanishing-point detection or a
dedicated guided-line UI, substantially larger efforts reserved for a
future slice.
