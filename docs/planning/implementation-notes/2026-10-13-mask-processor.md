# Mask processor (data/processing layer), slice 1 of 2

Related roadmap: Phase J ("Healing and Masking", PDF sections 21-22),
`docs/planning/PRODUCT_ROADMAP.md`'s Masking bullet: "Masking: start
with brush / linear gradient / radial + adjustment stack; AI/sky/subject
later." Related prior slices:
`docs/planning/implementation-notes/2026-10-13-crop-processor.md` and
`docs/planning/implementation-notes/2026-10-13-crop-tool-ui.md` (the
direct template for this slice's "two-slice data-layer-then-UI" split,
the `on_crop_changed`-style single programmatic entry point, and the
pipeline-wiring checklist), and
`docs/planning/implementation-notes/2026-10-13-state-aware-undo-redo.md`
(the `_capture_pending_history_state`/`AdjustmentStateCommand`/
`apply_history_state` machinery this slice integrates with unchanged).

## 1. Problem, goal, and non-goals

This is **slice 1 of 2** for the roadmap's Masking bullet. It adds the
data/processing layer only: mask geometry math (`MaskProcessor`), a
local adjustment sub-stack composed from already-built processors, full
pipeline/undo-redo/export wiring, and a programmatic (non-mouse-driven)
way to set the mask (`ImageController.on_mask_changed`).

**Explicitly NOT built here (all later slices' job):**

- **The interactive drag UI.** A draggable gradient line for linear, a
  draggable ellipse for radial, reusing `CropOverlay`'s established
  coordinate-math approach, plus a small panel of the mask's own
  Exposure/Contrast/Saturation/Clarity sliders. Slice 2 (a separate,
  later change) builds exactly this, driving the one public entry point
  this slice exposes: `ImageController.on_mask_changed(mask)`.
- **Brush masks.** Freehand painting needs a real-time paint-stroke
  canvas with per-pixel accumulation -- a persisted bitmap, not
  geometry -- which is a fundamentally different data model from the
  linear/radial gradients built here. Explicitly deferred, consistent
  with the roadmap's own "AI/sky/subject later" phasing already
  deferring the hardest mask types first.
- **A multi-mask stack.** Lightroom supports many simultaneous local
  adjustment masks with add/select/delete/reorder UI. This v1 supports
  **exactly one mask slot at a time** (state key `"mask"`, a single
  dict or `None`). A full stack is a separate, larger future slice.
- **The full ~20-parameter global adjustment set, within a mask.** Only
  4 parameters are supported per mask: Exposure, Contrast, Saturation,
  Clarity. Every other parameter -- temperature/tint, vibrance,
  texture, dehaze, vignette, grain, sharpening, luminance NR, color NR,
  remove CA, defringe, tone curve, HSL, Color Grading, straighten, crop
  -- cannot be scoped to a mask region in this slice. This is a real,
  deliberate scope cut (not an oversight): the goal was a safe, testable
  v1, not feature parity with Lightroom's masking panel.
- **AI/sky/subject selection.** Explicitly deferred by the roadmap
  bullet itself.
- **Healing** (the other half of Phase J's PDF 21-22 pairing) is
  untouched and entirely separate from this slice.

This slice's entire "UI surface" is one public, directly-callable
controller method, `ImageController.on_mask_changed(mask)`, mirroring
`on_crop_changed`'s pattern exactly (see
docs/planning/implementation-notes/2026-10-13-crop-processor.md section
4.5): a single discrete commit via
`apply_adjustments(mask_params=..., add_to_history=True)`, not a
continuous slider-style debounce/throttle dance.

## 2. Current behavior

Before this slice, there was no mask concept anywhere in the pipeline.
`ImageController` owned ~20 `_xxx_params` fields plus the non-flat
`tone_curve`/`hsl`/`color_grading`/`crop` categories. Crop was (and
remains) the pipeline's absolute last step.

## 3. Design

### 3.1 State shape

A new, non-flat key, `"mask"`, alongside `tone_curve`/`hsl`/
`color_grading`/`crop`:

```python
{
    "type": "linear" | "radial",   # or absent/None for "no mask"
    "invert": bool,                 # False = adjustments apply INSIDE the mask (default); True = outside
    # Linear-only:
    "x0": float, "y0": float,       # gradient start point, normalized [0,1] -- adjustments ramp to 0 here
    "x1": float, "y1": float,       # gradient end point -- adjustments ramp to full strength here
    # Radial-only:
    "cx": float, "cy": float,       # ellipse center, normalized [0,1]
    "rx": float, "ry": float,       # ellipse radii, normalized fractions of width/height respectively
    "feather": float,               # 0..1, fraction of the radius over which the edge softens
    # Shared:
    "exposure": float,    # -5.0 .. +5.0 (ExposureProcessor's own real range)
    "contrast": float,    # -100.0 .. +100.0 (ExposureProcessor's own real range)
    "saturation": float,  # -100.0 .. +100.0 (ColorProcessor's own real range)
    "clarity": float,     # -100.0 .. +100.0 (ClarityProcessor's own real range)
}
```

**Default/absent is `None`, not an empty dict -- a deliberate deviation
from crop's own convention.** Crop's "no crop" default is a real,
meaningful, applyable rectangle (the full frame), so it could double as
its own identity sentinel. A mask has no equivalent "neutral" geometry
-- there is no gradient or ellipse that is simultaneously valid and a
no-op. So, unlike `crop` (whose `get_adjustment_state()["crop"]` is
*always* a complete 4-key dict), `get_adjustment_state()["mask"]`
returns `None` when no mask is active, and a fully-populated dict
otherwise. This is confirmed safe for `get_adjustment_state()`'s own
JSON-serializability contract (catalog persistence, preset
export/import, Copy/Paste Edit Settings): `None` is valid JSON (`null`),
and `"mask"` is simply the first key in this dict's history whose
"no-op" value is `None` rather than a zero/identity value -- no other
key needed to represent genuine absence this way, since every other
non-flat key already has a meaningful identity value of its own
(`tone_curve`'s 2-point identity line, `hsl`/`color_grading`'s all-zero
dicts, `crop`'s full-frame rectangle).

**Internally**, `self._mask_params` still follows crop's own `{}`
falsy-sentinel convention (`{}` = "no mask", a populated dict = active)
-- this keeps every downstream processor-call guard a plain
`if self._mask_params:` check, identical to every other field in this
codebase, and keeps `apply_adjustments`'s `mask_params` kwarg guard
identical to crop's (`if mask_params is not None: self._mask_params =
mask_params`, so an explicit `{}` from `on_mask_changed(None)` can still
distinguish "clear the mask" from "caller didn't pass anything, leave
it as-is"). Only `get_adjustment_state()`'s *external* contract and
`_normalize_mask_state`'s *external* input/output use `None` -- the one
place internal and external representations differ is exactly
analogous to how crop's internal `{}` already differs from its external
always-complete-4-key-dict contract.

### 3.2 `MaskProcessor`

`src/processors/mask_processor.py`. `mask is None` (or an
unrecognized/missing `"type"`) returns an identity copy immediately,
matching every other processor's zero-cost-skip convention. Otherwise:

1. Compute an `(H, W)` float32 alpha field in `[0, 1]` from the mask's
   geometry (see 3.3/3.4 below).
2. If `invert` is `True`, use `1 - alpha`.
3. Run `ExposureProcessor` (exposure + contrast), `ColorProcessor`
   (saturation only; vibrance stays at its neutral `0.0`), and
   `ClarityProcessor` in sequence on a copy of the source image, using
   the mask's 4 stored values. These are the exact same processor
   classes (and the exact same parameter semantics/ranges) the global
   adjustment stack already uses -- no new processor math was written,
   only a blend step composing them. Instances are constructor-injected
   (defaulting to fresh ones) so tests can substitute mocks.
4. Blend: `result = image * (1 - alpha[..., None]) + local * alpha[..., None]`.

### 3.3 Linear gradient alpha -- why pixel-space projection, not raw
     normalized-fraction space

The naive approach -- project each pixel directly in raw normalized
`(x, y)` fraction space -- would make the gradient's visual angle depend
on the image's aspect ratio. A diagonal `(0,0)` to `(1,1)` gradient's
isolines (the actual visible bands, perpendicular to the line's
direction) are only genuinely perpendicular to the line *as drawn on
screen* if the projection is done in real pixel-space proportions: on a
2:1-wide image, "1 unit of x" and "1 unit of y" cover different physical
distances, so a projection computed in raw `[0,1]` fraction space would
skew the bands relative to how the line actually looks.

`MaskProcessor._linear_alpha` therefore converts `x0/y0/x1/y1` (and
every pixel's own coordinates) into real pixel units (`x * width`,
`y * height`) before projecting:

```
t = ((px - x0_px) * dx + (py - y0_px) * dy) / (dx**2 + dy**2)
alpha = clip(t, 0, 1)
```

This keeps the gradient's isolines genuinely perpendicular to the line
as drawn, regardless of image shape. No `feather` parameter exists for
linear masks -- the line's own length sets the transition width
(matching Lightroom's own linear gradient behavior: a longer dragged
line produces a softer transition), so there is nothing else to tune.

**Degenerate geometry.** A zero-length gradient (`(x0,y0) == (x1,y1)`)
would divide by zero in the projection's denominator. Guarded directly:
`length_sq < 1e-9` short-circuits to an all-`1.0` alpha field (fully
"on" everywhere) rather than computing `0/0`. Pinned by
`test_linear_gradient_zero_length_is_degenerate_but_finite`.

### 3.4 Radial gradient alpha -- the aspect-ratio-correctness property,
     confirmed against VignetteProcessor's own reasoning

`VignetteProcessor` is this codebase's existing precedent for
aspect-correct radial geometry: it normalizes `dy`/`dx` by `half_h`/
`half_w` **separately** (not by one shared scale), so a vignette's
corner-darkening shape naturally scales to the image's own aspect ratio
rather than being warped by it.

`MaskProcessor._radial_alpha` applies the exact same per-axis-independent
normalization: `rx`/`ry` are each scaled by the image's own width/height
respectively (`dx = (px - cx) / rx`, `dy = (py - cy) / ry`, both in
`[0,1]`-normalized-fraction space, `rx`/`ry` also normalized fractions
of width/height). This was verified directly and quantitatively (not
just asserted) with
`test_radial_aspect_ratio_is_preserved_relative_to_image_proportions`:
the exact same `{cx:0.5, cy:0.5, rx:0.2, ry:0.2}` geometry, applied to
both a square image and a very wide (2:1) image, produces a mask whose
pixel-space ellipse boundary sits at `0.2 * width` horizontally and
`0.2 * height` vertically in BOTH cases -- the shape scales
proportionally to each axis's own dimension, never stretched by the
image's overall aspect ratio. (A caller wanting a visually perfect
circle picks `rx`/`ry` so that `rx * width == ry * height`; the
processor's job is only to keep the SAME stored geometry behave
consistently across any image shape, which it does.)

Distance `dist = sqrt(dx**2 + dy**2)` is `0` at the center and `1` at
the ellipse boundary. The falloff over the outer `feather` fraction of
the radius reuses VignetteProcessor's own cubic smoothstep,
`t * t * (3 - 2*t)`, for consistency with this codebase's established
convention:

```
inner = max(1 - feather, 0)
t = clip((dist - inner) / max(feather, 1e-6), 0, 1)
alpha = 1 - (t * t * (3 - 2*t))
```

A `feather` near `0` produces a very narrow transition band (a near-hard
step at `dist == 1`); a `feather` near `1` softens across the whole
radius. Verified quantitatively (steepness of the alpha gradient, not
just "the images differ") by
`test_radial_feather_controls_edge_softness`.

**Degenerate geometry.** `rx`/`ry` are clamped to a minimum of `1e-4`
before use, so a stored `rx=0`/`ry=0` (or negative, from malformed
input) never divides by exactly zero. Pinned by
`test_radial_degenerate_near_zero_radii_does_not_crash`.

### 3.5 Pipeline ordering: mask-then-crop

**Decision made: mask is applied immediately after every other
adjustment (including Straighten) and strictly BEFORE Crop.**

Masking only blends pixel VALUES -- it never changes shape, unlike Crop
(the one deliberate shape-changing processor in this codebase; see
`crop_processor.py`'s own module docstring, re-confirmed as still
accurate). This means mask-then-crop and crop-then-mask are both
structurally valid orderings (neither breaks any other step's
shape-preservation invariant the way crop-before-everything-else would
have). The two options differ only in what coordinate space the mask's
own geometry is expressed in:

- **Mask-then-crop (chosen):** the mask's `x0/y0/x1/y1`/`cx/cy/rx/ry`
  are normalized fractions of the FULL, pre-crop frame. The mask never
  needs to know about, or recompute against, a separate,
  edit-time-dependent crop rectangle -- its geometry is always relative
  to the one fixed "original" frame, exactly like crop's own rectangle
  already is (see `crop_processor.md` section 4.1: crop coordinates are
  resolution-relative, not resolution-absolute, but always relative to
  *whatever full frame* the pipeline is currently processing -- full-res
  original or a smaller proxy -- never to an already-cropped
  intermediate result).
- **Crop-then-mask (rejected, but a reasonable alternative):** the
  mask's geometry would be normalized to the CROPPED frame's own
  coordinates. This is not wrong, but it adds a real complication this
  v1 doesn't need: if a user sets a mask, then changes the crop
  rectangle, the mask's own meaning would silently shift (the same
  stored `{cx: 0.5, cy: 0.5, ...}` would now center on a different
  physical region of the original image). Mask-then-crop avoids this
  entirely -- the mask's geometry is stable and independent of
  whatever crop rectangle is or isn't active.

Chosen for being the simpler, lower-risk design: one fewer interaction
to reason about between two independently-settable pipeline steps, and
it matches the natural mental model of "the mask describes a region of
the photo," not "a region of the current crop."

Pipeline order in every integration point:

```
... every existing global adjustment (Exposure through Straighten) ...
-> Mask (new, this slice)
-> Crop (unchanged, still strictly last)
```

### 3.6 Pipeline wiring

`mask_params` (the kwargs-style `{"mask": ...}` payload, or rather the
single dict `MaskProcessor.process` takes as its `mask=` argument)
threads through every site `crop_params` already goes through:
`ImageController` (`_mask_processor`/`_mask_params`, `get_export_image`,
`get_adjustment_state`, `_apply_state_params`/`restore_adjustment_state`,
`reset_to_original`, `apply_adjustments`'s threaded/sync/command paths,
the four `on_*_changed` debounced pass-through dicts,
`_on_throttled_adjustment`/`_on_debounced_adjustment`,
`on_slider_released`, `_has_pending_adjustment_changes`,
`_submit_delayed_final_render`, `commit_adjustments`, a new
`_normalize_mask_state`/`_safe_float` pair, and the new
`on_mask_changed` public API), `ProcessingRequest`/`ProcessingQueue`,
`ProcessingWorker` (processor, submit/apply/cache-key/signature, perf
logging), and `CombinedAdjustmentCommand`'s synchronous fallback.

**One intentional, pre-existing-pattern omission.** `apply_adjustments`'s
own synchronous, non-`add_to_history` "live preview" fallback branch
(used only when `use_threading=False` and no history commit is
requested) does not call `CropProcessor` either -- this was already
true before this slice (crop is simply absent from that one branch's
processor chain). Mask mirrors this exactly: it is not called in that
one branch either, matching the established (if slightly inconsistent)
footprint rather than introducing new behavior beyond this slice's
scope. `get_export_image()` (always correct, recomputes from the
original) and the threaded/command paths (the ones actually exercised
by real usage) both apply mask correctly; this one synchronous-fallback
branch's pre-existing gap is unaffected either way.

### 3.7 `on_mask_changed`

```python
def on_mask_changed(self, mask: Optional[Dict[str, Any]]) -> None:
    """Set (or clear, with None) the single active local-adjustment mask.
    ...
    """
    if not self.has_image():
        return
    self._capture_pending_history_state()
    normalized = self._normalize_mask_state(mask)
    self.apply_adjustments(mask_params=normalized, add_to_history=True)
```

Mirrors `on_crop_changed`'s pattern exactly (see
`crop-processor.md` section 4.5): captures the pre-gesture state,
normalizes/validates the incoming dict defensively (never trusting the
caller -- the dict may come from an old catalog entry, a malformed
imported preset, or interactive UI input in the later slice), and
commits via `apply_adjustments(..., add_to_history=True)` as a single
discrete step, participating fully in the state-aware undo/redo system.

### 3.8 `_normalize_mask_state`

Returns `{}` (the internal "no mask" sentinel) directly for `None`,
non-dict input, or a `"type"` that isn't exactly `"linear"`/`"radial"`
-- unlike crop, there is no separate "collapse to identity" step, since
an unrecognized/missing type IS the identity signal here. Otherwise
builds a fully-populated dict: `type`/`invert` plus the 4
type-appropriate geometry keys (clamped to `[0,1]` for
`x0/y0/x1/y1`/`cx/cy`, clamped to `[1e-4, 1]` for `rx/ry`, clamped to
`[0,1]` for `feather`) plus the 4 shared adjustment keys (clamped to
each underlying processor's own real valid range -- confirmed directly
from each processor's source rather than guessed: `ExposureProcessor`'s
exposure is `-5.0..5.0` stops and contrast is `-100.0..100.0`;
`ColorProcessor`'s saturation is `-100.0..100.0`; `ClarityProcessor`'s
clarity is `-100.0..100.0`).

## 4. Contracts

- State key: `"mask"`, either `None` ("no mask", the default) or a dict
  shaped per section 3.1. Unlike every other non-flat key
  (`tone_curve`/`hsl`/`color_grading`/`crop`), its absence is `None`,
  not an empty/identity dict -- see section 3.1 for why.
- `MaskProcessor.process(image, mask=None) -> LinearImage`: `mask is
  None` (or an unrecognized/missing `"type"`) returns an identity copy;
  otherwise returns a same-shape, same-dtype array with the local
  adjustment sub-stack blended through the computed alpha field.
- Pipeline position: immediately after every other adjustment
  (including Straighten), strictly BEFORE Crop, in every integration
  point.
- `ImageController.on_mask_changed(mask: Optional[Dict[str, Any]]) ->
  None`: public, directly-callable API. `None` clears the active mask.
  Defensively normalizes/clamps non-`None` input, stores it, and commits
  it to history in one discrete step (`add_to_history=True`). Not wired
  to any UI control in this slice.
- Older payloads that omit `"mask"` entirely restore as `None` (no
  schema-version bump needed -- additive, defaulted key, same as every
  prior non-flat-key addition).
- `ImageController._normalize_mask_state(raw) -> Dict[str, Any]`: pure
  bookkeeping, returns the *internal* `{}`-or-populated-dict shape
  (not the external `None`-or-populated-dict shape) -- see section 3.1.

## 5. Nuances and failure modes

**`None` vs. `{}` -- two different sentinels at two different layers,
by design, not an inconsistency.** See section 3.1 in full. Internally
`{}` (matching crop's own convention, keeping every processor-call guard
a plain `if self._mask_params:` check); externally `None` (per this
slice's own explicit spec, and because there is no meaningful "neutral"
mask geometry to use as an internal-style falsy-but-complete sentinel).

**Mask-then-crop means a committed mask's geometry survives a later
crop change unmodified -- by design.** Setting a mask, then changing the
crop rectangle, does not alter the mask's stored `x0/y0/...`/`cx/cy/...`
values at all; both are independent, pre-/post-crop-frame-relative
specifications applied in a fixed order. See section 3.5.

**Vibrance is deliberately left at `0.0` inside a mask, even though
`ColorProcessor.process` also accepts a `vibrance` parameter.** The task
spec's 4-parameter subset is Exposure/Contrast/Saturation/Clarity only;
vibrance (like temperature/tint, texture, dehaze, vignette, grain,
sharpening, both NR sliders, remove CA, defringe, tone curve, HSL, and
Color Grading) is an explicit future-slice gap, not a silently-dropped
parameter -- see section 1's non-goals.

**A mask applied to a flat/constant-color test image with an extreme
adjustment value can legitimately produce a result close to, but not
exactly equal to, a hand-computed "fully boosted" reference value near
the gradient's nominal endpoint**, because the alpha field at a pixel
one unit inset from the exact `(x1,y1)` point is not EXACTLY `1.0` (the
projection is continuous, and pixel centers are offset by `0.5px`).
Tests account for this with a small numerical tolerance rather than
exact equality at the very edge pixels, while still asserting
monotonicity and near-full-strength behavior quantitatively.

## 6. Test plan

- `tests/unit/test_processors/test_mask_processor.py` (new, 20 tests):
  `mask=None` and an unrecognized/missing `"type"` are exact identity
  copies; a quantitative linear-gradient ramp test (flat-color image,
  strong exposure boost, asserts near-start ≈ unchanged, near-end ≈
  fully-boosted, and a genuinely monotonic intermediate progression, not
  just "it's different somewhere"); linear zero-length-gradient
  degenerate geometry does not crash; linear `invert` flips which side
  is affected; radial gradient concentrates the effect near `(cx,cy)`
  and fades to the unmasked value at/beyond the ellipse boundary; radial
  `invert` flips which region is affected; radial `feather` controls
  edge softness, verified quantitatively via the alpha field's own
  steepness (not just "the images differ"); radial near-zero-radii
  degenerate geometry does not crash; **the aspect-ratio-correctness
  test** -- the same radial geometry applied to a square image and a
  very wide (2:1) image produces a mask whose boundary sits at the
  geometrically-correct, axis-proportional pixel position in both cases
  (the single most important correctness property `VignetteProcessor`
  itself had to get right, confirmed here too); dtype/shape/headroom
  preserved (never changes shape, preserves out-of-gamut values);
  determinism; saturation/clarity legs of the sub-stack actually run
  (not just exposure/contrast).
- `tests/unit/test_processing/test_processing_queue.py`: `mask_params`
  threads through `create_request`; defaults to `{}`.
- `tests/unit/test_processing/test_processing_worker.py`
  (`TestProcessingWorkerMask`): mask params reach the processor; an
  empty mask dict skips the processor entirely; the worker's real
  end-to-end pipeline (not a mocked processor) produces a genuinely
  different, but same-shape, result for a real mask; two different mask
  dicts produce different cache keys; a mask alongside a crop still
  produces the cropped shape (pipeline-order regression).
- `tests/unit/test_commands/test_adjustment_commands.py`
  (`TestCombinedAdjustmentCommand`): mask-only execute/undo (shape
  preserved, pixels changed, undo restores the pre-mask image by
  identity); mask applied after Straighten and before Crop (confirmed
  by asserting the final shape is the *cropped* shape).
- `tests/unit/test_controllers/test_image_controller.py`
  (`TestImageControllerMask`): default state is `None`;
  `restore_adjustment_state` round-trips both a linear and a radial
  mask; a payload missing `"mask"` entirely defaults cleanly to `None`
  (the backward-compatibility pattern mirroring every prior non-flat-key
  addition); malformed/out-of-range input (bad type, non-dict, clamped
  geometry/adjustment values) is tolerated; a real mask reaches
  `get_export_image()` and genuinely changes it (same shape, different
  pixels); `on_mask_changed` round-trips through `get_adjustment_state()`
  and adds to history; `on_mask_changed(None)` clears a previously-set
  mask; `on_mask_changed` normalizes/clamps defensively; the core
  state-aware-undo-redo regression pattern (mask A, then mask B, undo,
  assert the state equals A, not B); `reset_to_original` and loading a
  different image both clear the mask back to `None`; a mask alongside a
  crop still produces the correctly-shaped, finite export (pipeline-order
  regression at the controller level).
- The two pre-existing exact-dict contract tests,
  `test_get_adjustment_state_returns_normalized_defaults` and
  `test_restore_adjustment_state_applies_saved_values`, were updated
  with a `"mask": None` entry, the same mechanical update every prior
  processor slice has needed.

## 7. Rollout

Additive and `None`-defaulted. A plain revert removes it; older builds
ignore the extra persisted `"mask"` key. No UI control calls
`on_mask_changed` yet, so this slice changes no visible behavior for any
existing user flow -- it is reachable only by direct API calls (tests
today, slice 2's UI tomorrow). Acceptance requires the full vertical
data-layer path (processor, pipeline wiring at every integration point,
undo/redo, export) with no UI-thread image math, backward-compatible
restore, and passing targeted/full tests.

## 8. Implementation summary

Implemented `MaskProcessor` (`src/processors/mask_processor.py`):
linear-gradient and radial-gradient alpha-field geometry (pixel-space
projection for linear; per-axis-independent, aspect-ratio-correct
elliptical falloff with VignetteProcessor's own cubic smoothstep for
radial), composing the existing `ExposureProcessor`/`ColorProcessor`/
`ClarityProcessor` instances for a small, fixed 4-parameter local
adjustment sub-stack, blended through the alpha field. Applied
immediately after every other adjustment (including Straighten) and
strictly BEFORE Crop in every pipeline integration point (see section
3.5 for the mask-then-crop ordering decision and rationale).

Wired it through every point `crop_params` touches: `ImageController`
(`_mask_processor`/`_mask_params`, `_MASK_LINEAR_DEFAULTS`/
`_MASK_RADIAL_DEFAULTS`/`_MASK_ADJUSTMENT_RANGES`/`_MASK_TYPES`,
`get_export_image`, `get_adjustment_state`,
`_apply_state_params`/`restore_adjustment_state`, `reset_to_original`,
`apply_adjustments`'s threaded/sync/command paths, the four
`on_*_changed` debounced pass-through dicts,
`_on_throttled_adjustment`/`_on_debounced_adjustment`,
`on_slider_released`, `_has_pending_adjustment_changes`,
`_submit_delayed_final_render`, `commit_adjustments`, a new
`_normalize_mask_state`/`_safe_float` pair, and the new
`on_mask_changed` public API), `ProcessingRequest`/`ProcessingQueue`,
`ProcessingWorker` (processor, submit/apply/cache-key/signature, perf
logging), and `CombinedAdjustmentCommand`'s synchronous fallback.

**The `None`-vs-`{}` sentinel split (the one real design decision in
this slice, beyond the geometry math itself).** See sections 3.1 and
5 for the full reasoning: externally `None` (per this slice's own
explicit spec, since there is no neutral mask geometry), internally
`{}` (mirroring crop's own established falsy-sentinel convention, so
every downstream guard stays a plain truthy check).

**Pipeline-ordering decision (mask-then-crop).** Documented in full in
section 3.5, including the rejected alternative (crop-then-mask) and
why mask-then-crop was chosen as the simpler, lower-risk default: the
mask's geometry is always relative to the one fixed pre-crop frame,
never needing to account for a separate, edit-time-dependent crop
rectangle.

**Programmatic API, not UI.** `ImageController.on_mask_changed(mask)` is
this slice's entire "UI surface" -- a single discrete commit (no
debounce/throttle dance, unlike a slider), routed through the existing
`apply_adjustments(..., add_to_history=True)` path so it participates
fully in the state-aware undo/redo system. No button, overlay, or
slider was wired to it.

**Deviation notes.**

1. The task's suggested `MaskProcessor.__init__` signature (constructor-
   injectable processor instances, defaulting to fresh ones) was kept
   exactly as specified, enabling the mocked-processor tests in
   `TestProcessingWorkerMask`/`TestCombinedAdjustmentCommand` to assert
   call-through without needing real pixel math.
2. One intentional non-fix: `apply_adjustments`'s synchronous,
   non-`add_to_history` "live preview" fallback branch does not call
   mask (mirroring crop's own pre-existing omission from that same
   branch) -- see section 3.6's "one intentional, pre-existing-pattern
   omission" callout. This is a deliberate choice to match established
   behavior exactly, not an oversight, and does not affect any real
   usage path (`get_export_image()` and the threaded/command paths both
   apply mask correctly).
3. No other deviation of substance from the task's design spec for the
   processor math, state shape, or pipeline-ordering contract.

**Verification.** New/changed test files: `tests/unit/test_processors/
test_mask_processor.py` (20 tests), `tests/unit/test_processing/
test_processing_queue.py` (+2 tests), `tests/unit/test_processing/
test_processing_worker.py` (`TestProcessingWorkerMask`, 5 tests),
`tests/unit/test_commands/test_adjustment_commands.py` (+2 tests),
`tests/unit/test_controllers/test_image_controller.py`
(`TestImageControllerMask`, 17 tests) -- all passing in file-scoped
runs. Full suite run per the task's verification command; see the
calling session's own run for the final authoritative pass count, since
this slice's own local run observed only the same pre-existing,
documented `test_geometry_is_restored_on_next_launch` offscreen-platform
flake already noted in every prior implementation note (deselected, not
fixed, per the task's own instructions), and no other regressions in any
test that assumed the prior fixed pipeline order, a complete
`get_adjustment_state()` dict shape, or a constant `"mask"`-free
`_apply_adjustments`/`apply_adjustments` signature.
