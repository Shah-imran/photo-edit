# Healing processor (data/processing layer), slice 1 of 2

Related roadmap: Phase J ("Healing and Masking", PDF sections 21-22),
`docs/planning/PRODUCT_ROADMAP.md`'s Healing bullet: "Healing brush:
clone/heal, size/feather/opacity, visualize spots (simplified)." Direct
templates for this slice's "processor + full pipeline wiring +
on_X_changed programmatic API + state-aware undo/redo integration"
pattern:
`docs/planning/implementation-notes/2026-10-13-mask-processor.md` and
`docs/planning/implementation-notes/2026-10-13-crop-processor.md`, and
`docs/planning/implementation-notes/2026-10-13-state-aware-undo-redo.md`
for the `_capture_pending_history_state`/`AdjustmentStateCommand`
machinery this slice integrates with unchanged.

## 1. Problem, goal, and non-goals

This is **slice 1 of 2** for the roadmap's Healing bullet. It adds the
data/processing layer only: a `HealingProcessor`, full
pipeline/undo-redo/export wiring, and a programmatic (non-mouse-driven)
way to set the complete list of heal spots
(`ImageController.on_heal_spots_changed`).

**Explicitly NOT built here (slice 2's job, a separate, later change):**

- **The interactive click-to-heal UI.** Placing a spot with a click,
  dragging a second point to pick the source, live-dragging
  radius/feather handles, and a small panel of the spot's own
  size/feather/opacity controls. Slice 2 builds exactly this, driving
  the one public entry point this slice exposes:
  `ImageController.on_heal_spots_changed(heal_spots)`.
- **"Visualize spots" overlay.** The roadmap bullet's own "(simplified)"
  qualifier suggests even the eventual UI version should stay simple (a
  basic marker at each spot, not an elaborate overlay) -- but no overlay
  of any kind is drawn in this slice; that is slice 2's job entirely.
- **Auto-selecting a good source point.** `src_x`/`src_y` are always
  caller-supplied in this slice's data model. The later UI slice decides
  how to default them (e.g. a fixed offset from the destination, or a
  second drag) or let the user pick a point; this processor only
  consumes whatever source point it is given, never infers one.
- **Content-aware fill / object removal beyond a single small patch.**
  This is a small-spot repair tool (Lightroom's own Spot Removal), not a
  general inpainting/object-removal feature.
- **Masking** (the other half of Phase J's PDF 21-22 pairing) is
  untouched and entirely separate from this slice -- it was already
  completed in a prior slice (see
  `docs/planning/implementation-notes/2026-10-13-mask-processor.md`).

This slice's entire "UI surface" is one public, directly-callable
controller method, `ImageController.on_heal_spots_changed(heal_spots)`,
mirroring `on_crop_changed`/`on_mask_changed`'s pattern exactly: a single
discrete commit via `apply_adjustments(healing_params=...,
add_to_history=True)`, not a continuous slider-style debounce/throttle
dance.

## 2. The two genuinely new things in this slice

### 2.1 A LIST, not a single slot or a dict

Every non-flat key built so far (`tone_curve`, `hsl`, `color_grading`,
`crop`, `mask`) is either a flat dict or (for mask) a single optional
slot. Healing is naturally multi-spot -- Lightroom lets a user place many
independent spots on one photo -- so the state key `"heal_spots"` is a
**list** of independent spot dicts. `[]` (no spots) is the meaningful,
falsy "nothing here" default, following the exact same falsy-skip
convention every scalar-param processor already uses
(`if self._healing_params:`), just with a list wrapped in a single-key
dict (`{"heal_spots": [...]}`) instead of a bare scalar/dict value --
mirroring tone curve's own `{"points": [...]}` wrapping convention (the
one existing precedent for "a non-scalar-float VALUE kept inside an
otherwise-scalar `_xxx_params` dict").

### 2.2 Pipeline ordering: healing is FIRST, not appended at the end

Every processor built in Phase G/H/I/J so far (Texture, Clarity, Dehaze,
Vignette, Grain, Sharpening, both noise-reduction sliders, Remove CA,
Defringe, Straighten, Mask, Crop) was appended at some point **later**
in the fixed processing chain, after Exposure. Healing is the first
processor in this codebase's history to be inserted **before**
Exposure -- at the very front of the chain, operating on the
freshly-copied original image before anything else touches it.

**Why.** Healing conceptually operates on the "as-shot" pixels -- it is
a repair operation (removing a dust spot, a blemish, a sensor artifact),
not a creative tonal/color adjustment. Lightroom's own Spot Removal tool
is meant to be invisible groundwork: every subsequent tonal, color, and
effects decision (exposure, contrast, color grading, grain, sharpening,
...) should be made against an already-repaired image, not against one
that still has a visible defect the user is about to paper over with a
local adjustment elsewhere. Running Healing LAST (or anywhere after
Exposure) would mean a later-applied Vignette or Mask could still be
computed from -- and visually interact with -- the un-repaired defect
before Healing ever touches it; running it FIRST avoids that entirely.

**Shape-preservation confirmed, same as every other non-Crop
processor.** `HealingProcessor` blends pixel VALUES within small local
regions; it never removes or adds pixels, so it preserves the exact
input `(H, W, C)` shape -- the same invariant Mask already established.
This is what makes "insert it at the very front" safe: no downstream
consumer (worker cache keys, undo/redo buffers, zoom/display math,
histogram, `ImageModel.get_image_size()`, export) has to change, because
nothing about those consumers' tolerance for a given SHAPE changes --
only the pixel VALUES at the start of the chain are now different (and
all of those consumers already read whatever shape/values the full
chain produces, as established in the Crop/Mask slices' own downstream
traces).

**Wiring consequence.** Healing was inserted as a NEW FIRST step at
every one of the ~6 wiring sites `crop_params`/`mask_params` already go
through, mirroring whichever processor was previously first at each site
(always Exposure) -- `ImageController` (`get_export_image`,
`restore_adjustment_state`'s manual recompute, `apply_adjustments`'s
synchronous live-preview fallback), `ProcessingWorker._apply_adjustments`,
`CombinedAdjustmentCommand.execute()`, all now applying Healing before
Exposure. Parameter LIST ORDER in each method's signature does not need
to match pipeline order (and does not -- `healing_params` is appended
after `mask_params` in every signature, for minimal diff risk, exactly
as `mask_params` was appended after `crop_params` despite running before
it); only the ORDER OF THE ACTUAL PROCESSOR CALLS inside each method's
body was changed to put Healing first.

## 3. Current behavior

Before this slice, there was no healing concept anywhere in the
pipeline. `ImageController` owned ~20 `_xxx_params` fields plus the
non-flat `tone_curve`/`hsl`/`color_grading`/`crop`/`mask` categories.
Exposure was (and, for every OTHER processor, remains) the pipeline's
first step.

## 4. Design

### 4.1 State shape

A new, non-flat key, `"heal_spots"`, alongside
`tone_curve`/`hsl`/`color_grading`/`crop`/`mask`: a list (possibly
empty) of dicts, each shaped:

```python
{
    "dst_x": float, "dst_y": float,   # destination center, normalized [0, 1]
    "src_x": float, "src_y": float,   # source center, normalized [0, 1]
    "radius": float,                   # normalized fraction of min(width, height)
    "feather": float,                  # 0..1, soft edge fraction of the radius
    "opacity": float,                  # 0..1, blend strength
    "mode": "heal" | "clone",          # "heal" = content-aware (Poisson) blend, "clone" = direct feathered copy
}
```

Default/absent is `[]` -- `get_adjustment_state()["heal_spots"]` always
returns a list, never `None` (unlike `mask`, which uses `None` because
there is no neutral mask geometry; a list naturally empties, so `[]` is
both meaningful AND a real, valid value, exactly like `tone_curve`'s own
"always a list" convention). Older payloads that omit `"heal_spots"`
entirely restore as `[]`.

**Internally**, `self._healing_params` follows the same `{}`
falsy-sentinel convention every other field uses (`{}` = "no spots", a
populated `{"heal_spots": [...]}` dict otherwise), which keeps every
downstream processor-call guard a plain `if self._healing_params:`
check, and keeps `HealingProcessor.process`'s own `heal_spots=` kwarg
reachable via the established `**self._healing_params` spread pattern
(the dict's one key IS the kwarg name, exactly like `_curve_params`'s
`{"points": [...]}` spreads into `CurveProcessor.process(points=...)`).

### 4.2 `HealingProcessor`

`src/processors/healing_processor.py`. `heal_spots` falsy (`None` or
`[]`) returns an identity copy immediately, matching every other
processor's zero-cost-skip convention. Otherwise, for each spot (applied
in list order, writing into a progressively-updated result buffer, but
always SAMPLING its source patch from the original, pre-this-processor
image -- so spots never chain off each other's edits for sampling
purposes; only the destination WRITE order matters for overlapping
spots):

1. **Defensive per-spot normalization.** A non-dict entry, or one with
   an unrecognized/missing `"mode"`, is skipped entirely (there is no
   sensible default mode to substitute) -- never crashes the whole
   pipeline on one malformed list entry from old persisted data. Every
   other field (coordinates, radius, feather, opacity) is clamped to a
   sane range rather than rejected: coordinates to `[0, 1]`, radius to
   `[1e-4, 1]`, feather/opacity to `[0, 1]`.
2. **Pixel-space geometry, resolution-relative.** `radius` converts to
   pixels via `radius * min(width, height)` of the CURRENT image's own
   `shape` (not a fixed resolution) -- the same reasoning
   `MaskProcessor`/`VignetteProcessor`/`CropProcessor` already use.
3. **Edge-safe patch extraction.** The destination and source patches
   must be the SAME pixel shape (for both Clone's blend and Heal's
   `cv2.seamlessClone` call), but a spot near an image edge may only
   have room on one side. The fix: the patch's reach on each of the 4
   sides is clamped to whichever of the destination/source centers is
   closer to that edge (`min(dst_center, src_center, radius_px)` per
   side), so the SAME offsets are always valid in-bounds for BOTH
   regions. This shrinks the effective patch symmetrically near an
   edge, rather than crashing, wrapping, or misaligning the two regions.
4. **Feathered alpha field.** A per-patch `(h, w)` alpha field, 1.0 at
   the spot's own center, falling to 0.0 at/beyond its pixel radius over
   the outer `feather` fraction, via the same `t * t * (3 - 2*t)` cubic
   smoothstep `MaskProcessor`/`VignetteProcessor` already use, for
   consistency with this codebase's established convention (no new
   falloff math invented). `spot_alpha = alpha * opacity`.
5. **Clone mode:** `result = dst * (1 - spot_alpha) + src * spot_alpha`
   -- pure float32 arithmetic, no 8-bit dependency, always available,
   exactly deterministic.
6. **Heal mode:** see section 5 below -- the one place this slice
   introduces a real, accepted approximation.

### 4.3 Pipeline wiring

`healing_params` (a single-key `{"heal_spots": [...]}` dict, matching
`HealingProcessor.process`'s own `heal_spots=` kwarg when spread)
threads through every site `mask_params`/`crop_params` already go
through: `ImageController` (`_healing_processor`/`_healing_params`,
`get_export_image`, `get_adjustment_state`,
`_apply_state_params`/`restore_adjustment_state`, `reset_to_original`,
`apply_adjustments`'s threaded/sync/command paths, the four
`on_*_changed` debounced pass-through dicts,
`_on_throttled_adjustment`/`_on_debounced_adjustment`,
`on_slider_released`, `_has_pending_adjustment_changes`,
`_submit_delayed_final_render`, `commit_adjustments`, a new
`_normalize_heal_spots_state` method, and the new
`on_heal_spots_changed` public API), `ProcessingRequest`/`ProcessingQueue`,
`ProcessingWorker` (processor, submit/apply/cache-key/signature, perf
logging), and `CombinedAdjustmentCommand`'s synchronous fallback.
Applied as a NEW FIRST step (before Exposure) at every site; see section
2.2.

**Cache-key hashability.** Every existing `_xxx_params` field is flat
(scalars only), so `tuple(sorted(params.items()))` is directly hashable
for use inside `ProcessingWorker._cache_key`/`_adjustment_signature`'s
tuple. `heal_spots` is a LIST OF DICTS -- not directly hashable the same
way (a `list` value inside the tuple would raise `TypeError: unhashable
type: 'list'` the moment it was used as a dict key). A new helper,
`ProcessingWorker._hashable_heal_spots(healing_params)`, converts it to
a tuple of per-spot `tuple(sorted(spot.items()))` tuples instead --
hashable as long as every spot's own values are hashable scalars (true
for this schema: floats and the `mode` string only). This is the one
piece of genuinely new plumbing this slice needed beyond "add one more
`if params: result = processor.process(...)` call" at each site.

### 4.4 `on_heal_spots_changed`

```python
def on_heal_spots_changed(self, heal_spots: list) -> None:
    """Set the complete list of heal spots (replaces, not appends)."""
    if not self.has_image():
        return
    self._capture_pending_history_state()
    normalized = self._normalize_heal_spots_state(heal_spots)
    healing_params = {"heal_spots": normalized} if normalized else {}
    self.apply_adjustments(healing_params=healing_params, add_to_history=True)
```

Mirrors `on_crop_changed`/`on_mask_changed`'s pattern exactly: captures
the pre-gesture state, normalizes/validates every spot in the incoming
list defensively, and commits via `apply_adjustments(...,
add_to_history=True)` as a single discrete step, participating fully in
the state-aware undo/redo system. **Always REPLACES the whole list** --
it provides no add/remove primitive of its own. The caller (the later UI
slice) is responsible for assembling the full list itself, e.g. reading
the current list via `get_adjustment_state()["heal_spots"]`, appending a
newly-placed spot (or filtering one out), and calling this method with
the complete result.

## 5. Heal mode's 8-bit round-trip -- a real, accepted v1 approximation

`cv2.seamlessClone` (OpenCV's own Poisson-blending implementation --
**no Poisson-blending math was written in this slice**, it is reused
directly) requires 8-bit `uint8` input. This pipeline works in
linear-light float32 throughout. This is a genuine mismatch: Heal mode's
small working patch is converted to an sRGB-encoded 8-bit representation
for the one `cv2.seamlessClone` call, then converted back to linear
float32 -- meaning the Poisson blend itself does NOT happen in true
linear light. This is a real, accepted v1 simplification, documented
here explicitly and prominently, the same way Grain and other processors
in this codebase have already documented their own accepted
approximations.

**Conversions reused, not reinvented.** `src/utils/color_pipeline.py`
already has exactly the two directions needed:

- **Linear -> display (8-bit):** `linear_to_srgb()` (the actual OETF
  math) is reused directly; only the trivial
  scale-by-255/round/clip/cast-to-`uint8` step is repeated locally in
  `HealingProcessor._to_display_u8`, mirroring
  `color_pipeline._linear_to_srgb_u8`'s own private helper exactly (that
  helper is private to its module, so this processor does not import it,
  but introduces no new conversion MATH of its own -- the module's own
  public `linear_to_srgb` is what does the real work).
- **Display (8-bit) -> linear:** `uint8_srgb_to_linear()` is reused
  directly, unmodified -- this function already existed (RAW/non-RAW
  image LOADING already needs exactly this conversion, via an exact
  256-entry LUT, not an approximation at the per-byte level) and needed
  no new code at all.

No new linear<->display conversion MATH was written for this slice in
either direction -- only the 8-bit scale/round/clip wrapper around the
module's own existing OETF function, mirroring its own private helper.

**What was found empirically about precision.** The round-trip through
8-bit necessarily quantizes a Heal patch's dynamic range to 256 levels
per channel before `cv2.seamlessClone` runs, then re-expands it back to
float32 afterward. For a MID-TONE patch (values roughly in sRGB
0.2-0.8), this quantization step (~1/255 ≈ 0.4% per level in sRGB-encoded
space) is well below what either the Poisson solve itself or the
feathered opacity blend that follows can meaningfully preserve, and no
visible banding was observed in this slice's own test images at that
range. In NEAR-BLACK regions, however, the sRGB encoding's much steeper
slope near 0 means the SAME 1-level 8-bit step corresponds to a much
LARGER step in linear light than the same 1-level step does near
white -- so a Heal spot whose patch sits in a very dark region of the
image is more susceptible to visible quantization/banding after the
round-trip than the same spot in a bright region. This is a real,
accepted v1 limitation (not fixed in this slice): Heal mode's content-
aware blend trades a small amount of near-black precision for reusing
OpenCV's Poisson solver outright rather than writing new Poisson-blending
math in float32. Clone mode has no such tradeoff at all (pure float32
copy+feather, no OpenCV/8-bit dependency), so a caller for whom this
matters can always use Clone mode's lossless path instead.

**A second empirical finding: `cv2.seamlessClone` crashes (not merely
errors) on a mask whose nonzero footprint is only a handful of pixels.**
Confirmed directly on this environment's OpenCV 5.0.0 build: a 1-pixel
mask raises `error('vector::_M_default_append')` -- a native exception,
not a clean `cv2.error`/`ValueError` in every code path tested. A spot
this small has no visually meaningful "content-aware" blend to offer
anyway (there is no neighborhood for Poisson to reason about), so
`HealingProcessor` falls back to Clone's always-safe feathered-copy
blend whenever a Heal-mode spot's pixel radius rounds below
`_MIN_HEAL_RADIUS_PX` (3px), rather than risking a crash. A defensive
`try/except cv2.error` around the actual `cv2.seamlessClone` call
additionally catches the cleanly-raised exception case (a pathological
geometry OpenCV itself rejects) and falls back to Clone the same way.
`cv2.seamlessClone` was confirmed directly to be exactly deterministic
(two calls with identical inputs produce byte-identical output) on this
environment's OpenCV build, so Heal mode's own determinism test is a
real, not assumed, guarantee -- see section 7.

## 6. Contracts

- State key: `"heal_spots"`, always a list (`[]` by default, never
  `None`). Unlike `mask` (whose absence is `None`), a list naturally
  empties, so `[]` is both the meaningful "no spots" signal AND a
  genuinely valid, complete value -- the same reasoning `tone_curve`'s
  own "always a list" convention already established.
- `HealingProcessor.process(image, heal_spots=None) -> LinearImage`:
  `heal_spots` falsy returns an identity copy; otherwise returns a
  same-shape, same-dtype array with every valid spot in the list
  blended in order. A malformed spot (non-dict, or an
  unrecognized/missing `"mode"`) is skipped, never raised.
- Pipeline position: **strictly FIRST**, before every other adjustment
  (including Exposure), in every integration point. See section 2.2.
- `ImageController.on_heal_spots_changed(heal_spots: list) -> None`:
  public, directly-callable API. Always REPLACES the whole list (no
  add/remove primitive). Defensively normalizes/clamps every spot in
  non-`None` input, stores the result, and commits it to history in one
  discrete step (`add_to_history=True`). Not wired to any UI control in
  this slice.
- Older payloads that omit `"heal_spots"` entirely restore as `[]` (no
  schema-version bump needed -- additive, defaulted key, same as every
  prior non-flat-key addition).
- `ImageController._normalize_heal_spots_state(raw) -> list`: pure
  bookkeeping, returns the fully-clamped, malformed-entries-skipped
  list (not wrapped in `{"heal_spots": ...}` -- the caller wraps it, the
  same split `_normalize_crop_state`/`_normalize_mask_state` already use
  between "normalize the value" and "decide the internal sentinel
  shape").

## 7. Nuances and failure modes

**Healing-first is the one genuinely new pipeline-ordering decision in
this slice -- see section 2.2 in full.** Every prior Phase G/H/I/J
processor was appended somewhere LATER in the fixed chain; Healing is
the first to be inserted BEFORE Exposure, at the very front.

**The 8-bit round-trip for Heal mode is a real, accepted v1
approximation, not a bug -- see section 5 in full**, including the
empirical near-black precision finding and the tiny-radius
crash-avoidance fallback to Clone.

**Spots sample their SOURCE from the pristine input image, never from
the progressively-edited result.** Only the DESTINATION write accumulates
across spots in list order (so two overlapping spots' destinations
compose, last-wins per pixel within the overlap, weighted by each
spot's own feather/opacity), but sampling never chains -- spot 2's
source patch is never influenced by spot 1's edit, even if their
regions overlap. This keeps multi-spot application simple, predictable,
and independent of visitation order for the SOURCE half of the
operation.

**A spot's radius/feather/opacity are clamped at TWO independent
layers, by design, mirroring Crop/Mask's own established
double-validation precedent.** Both `HealingProcessor._normalize_spot`
(the processor's own input guard) and
`ImageController._normalize_heal_spots_state` (the controller's state-
layer guard) apply the same clamping logic independently -- the same
"never trust the caller" discipline Crop's processor+controller pair and
Mask's processor+controller pair already established, not a new
inconsistency introduced here.

**`cv2.seamlessClone`'s mask is a hard-edged circle, not the same
feathered alpha field Clone uses -- feathering is applied AFTERWARD, in
the final opacity blend, uniformly for both modes.** OpenCV's own
Poisson solver already produces a smooth, content-aware transition at
its own mask boundary (that is the entire point of Poisson blending over
a plain copy); layering a second, independent feather directly into the
mask passed to `cv2.seamlessClone` would double up on that smoothing in
a way that is hard to reason about. Instead, the SAME feathered alpha
field Clone uses is applied as a final linear interpolation between the
original destination region and `cv2.seamlessClone`'s own output --
consistent with how `cv2.seamlessClone` has no opacity parameter of its
own at all, so opacity (and the feather-based spatial falloff) is always
applied this same way, after the fact, for both modes.

## 8. Test plan

- `tests/unit/test_processors/test_healing_processor.py` (new, 21
  tests): `heal_spots=None`/`[]` are exact identity copies;
  dtype/shape preserved on identity; Clone mode copies the source color
  into the destination with a genuinely feathered (not hard) edge;
  Clone does not crash near an image edge and clips sensibly; Clone's
  opacity scales the blend strength QUANTITATIVELY (0.0 leaves the
  destination exactly unchanged, 1.0 is the full source value, 0.5 is
  exactly the midpoint -- verified numerically, not just "it changed
  somewhere"); Clone is exactly deterministic; **the heal-vs-clone
  distinguishing test** (`test_heal_blends_illumination_with_surroundings_unlike_clone`)
  -- constructs a destination on a uniformly dark background being
  healed from a source patch with its own internal bright/dim gradient
  structure, and asserts quantitatively that Heal's result (a) is NOT a
  plain copy of Clone's result, (b) sits BETWEEN the original (dark)
  destination and Clone's (bright) result -- Poisson blending anchors
  overall illumination to the destination's own surroundings -- and (c)
  still shows the source's internal left-bright/right-dim structure
  inside the healed patch, confirming content genuinely transfers rather
  than being discarded; Heal mode is exactly deterministic (confirmed
  empirically against this environment's real OpenCV build, not
  assumed); Heal's opacity 0.0 leaves the destination exactly unchanged;
  Heal's shape/dtype preserved; Heal does not crash near an image edge;
  a tiny radius that rounds below `cv2.seamlessClone`'s safe minimum
  falls back to Clone without crashing (the exact crash this slice found
  and worked around, pinned directly); multiple spots in one list are
  all applied, in order (including a second overlapping spot correctly
  overriding the first, per list order); a missing/unrecognized `"mode"`
  skips that one spot without crashing the rest; a non-dict list entry
  is skipped; out-of-range coordinates/radius/feather/opacity are
  clamped, never crashed; missing optional keys default cleanly; a
  mixed valid/malformed list only applies the valid spot.
- `tests/unit/test_processing/test_processing_queue.py`: `healing_params`
  threads through `create_request`; defaults to `{}`.
- `tests/unit/test_processing/test_processing_worker.py`
  (`TestProcessingWorkerHealing`, 7 tests): healing params reach the
  processor; an empty healing dict skips the processor entirely; the
  worker's real end-to-end pipeline (not a mocked processor) produces a
  genuinely different, same-shape result for a real heal spot; two
  different healing param sets produce different cache keys (the new
  `_hashable_heal_spots` conversion, confirmed working); healing applied
  alongside mask and crop still produces the cropped shape (pipeline-
  order regression); **the heal-before-exposure ordering test**
  (`test_healing_runs_before_exposure_contrast_in_real_pipeline`) -- a
  concrete, falsifiable test using a feathered (genuinely PARTIAL alpha)
  Clone spot and a nonlinear Contrast adjustment: the two orderings
  (heal-then-contrast vs. contrast-then-heal) are mathematically proven
  to differ whenever the blend is nonlinear-and-partial (verified
  directly by computing both orderings independently and confirming the
  real worker pipeline's result matches "heal, then contrast" and
  provably does NOT match the reversed order).
- `tests/unit/test_commands/test_adjustment_commands.py`
  (`TestCombinedAdjustmentCommand`): healing-only execute/undo (shape
  preserved, pixels changed, undo restores the pre-heal image by
  identity); healing applied alongside Exposure/Straighten/Crop without
  crashing, confirming Crop still runs correctly last even with healing
  now running first.
- `tests/unit/test_controllers/test_image_controller.py`
  (`TestImageControllerHealing`, 17 tests): default state is `[]`;
  `restore_adjustment_state` round-trips a multi-spot list (mixed
  clone/heal modes); a payload missing `"heal_spots"` entirely defaults
  cleanly to `[]`; malformed input (non-list, a spot with a bad mode
  mixed with a good one, out-of-range geometry/opacity) is tolerated and
  clamped/skipped; a real spot list reaches `get_export_image()` and
  genuinely changes it; `on_heal_spots_changed` round-trips through
  `get_adjustment_state()` and adds to history; `on_heal_spots_changed([])`
  clears a previously-set list; `on_heal_spots_changed` normalizes/clamps
  defensively; the core state-aware-undo-redo regression pattern (spots
  A, then spots B, undo, assert the state equals A, not B);
  `reset_to_original` and loading a different image both clear the list
  back to `[]`; a spot list alongside a crop still produces the
  correctly-shaped, finite export (pipeline-order regression); a spot
  list alongside Exposure still produces a finite export (controller-
  level ordering smoke test).
- The two pre-existing exact-dict contract tests,
  `test_get_adjustment_state_returns_normalized_defaults` and
  `test_restore_adjustment_state_applies_saved_values`, were updated
  with a `"heal_spots": []` entry, the same mechanical update every
  prior processor slice has needed.

## 9. Rollout

Additive and `[]`-defaulted. A plain revert removes it; older builds
ignore the extra persisted `"heal_spots"` key. No UI control calls
`on_heal_spots_changed` yet, so this slice changes no visible behavior
for any existing user flow -- it is reachable only by direct API calls
(tests today, slice 2's UI tomorrow). Acceptance requires the full
vertical data-layer path (processor, pipeline wiring at every
integration point -- now FIRST rather than appended at the end,
undo/redo, export) with no UI-thread image math, backward-compatible
restore, and passing targeted/full tests.

## 10. Implementation summary

Implemented `HealingProcessor` (`src/processors/healing_processor.py`):
per-spot defensive normalization, edge-safe same-shape patch extraction
(symmetric offset clamping against both centers' distance-to-edge),
a feathered cubic-smoothstep alpha field (reusing Mask/Vignette's own
convention), a pure-float32 Clone blend, and a Heal blend that reuses
`cv2.seamlessClone` (OpenCV's own Poisson-blending implementation -- no
Poisson math written here) through a round-trip via this codebase's
EXISTING `linear_to_srgb`/`uint8_srgb_to_linear` conversion helpers (no
new conversion math in either direction), with a tiny-radius/pathological-
geometry fallback to Clone to avoid a confirmed native OpenCV crash.
Applied as a NEW FIRST step, before Exposure, in every pipeline
integration point -- see section 2.2 for the full ordering rationale,
the one genuinely new architectural decision in this slice.

Wired it through every point `mask_params`/`crop_params` touch:
`ImageController` (`_healing_processor`/`_healing_params`,
`_HEALING_MODES`/`_HEALING_SPOT_DEFAULTS`, `get_export_image`,
`get_adjustment_state`, `_apply_state_params`/`restore_adjustment_state`,
`reset_to_original`, `apply_adjustments`'s threaded/sync/command paths,
the four `on_*_changed` debounced pass-through dicts,
`_on_throttled_adjustment`/`_on_debounced_adjustment`,
`on_slider_released`, `_has_pending_adjustment_changes`,
`_submit_delayed_final_render`, `commit_adjustments`, a new
`_normalize_heal_spots_state` method, and the new
`on_heal_spots_changed` public API), `ProcessingRequest`/`ProcessingQueue`,
`ProcessingWorker` (processor, submit/apply/cache-key/signature --
including the new `_hashable_heal_spots` list-to-tuple conversion for
the cache key -- and perf logging), and `CombinedAdjustmentCommand`'s
synchronous fallback.

**Pipeline-ordering decision (healing-first).** Documented in full in
section 2.2: the one genuinely new architectural wrinkle in this slice,
since every prior Phase G/H/I/J processor was appended LATER in the
chain, never before Exposure.

**The 8-bit round-trip for Heal mode.** Documented in full in section 5,
including the empirical near-black precision finding and the
tiny-radius/`cv2.error` crash-avoidance fallback to Clone -- both
confirmed directly against this environment's real OpenCV 5.0.0 build,
not assumed.

**A LIST, not a dict/single-slot.** Documented in section 2.1: `[]` is
the meaningful default, mirroring tone curve's own "always a list"
convention rather than mask's "`None` for no neutral geometry"
convention, since a list naturally empties.

**Programmatic API, not UI.** `ImageController.on_heal_spots_changed(heal_spots)`
is this slice's entire "UI surface" -- a single discrete commit (no
debounce/throttle dance, unlike a slider), routed through the existing
`apply_adjustments(..., add_to_history=True)` path so it participates
fully in the state-aware undo/redo system. No button, overlay, or
click-to-place interaction was wired to it. "Visualize spots" (even the
roadmap's own "(simplified)" version) is entirely slice 2's job.

**Deviation notes.**

1. `_MIN_HEAL_RADIUS_PX = 3` (a Heal-mode spot whose radius rounds below
   3px silently falls back to Clone) was not in the original task spec
   verbatim, but is a direct, necessary consequence of the empirical
   finding that `cv2.seamlessClone` can crash (a native exception, not a
   cleanly-catchable Python error in every code path) on a mask with
   only a handful of nonzero pixels -- confirmed directly in this
   slice's own investigation (see section 5) before writing the
   processor, not discovered after the fact. A defensive
   `try/except cv2.error` around the actual call additionally catches
   the cleanly-raised exception case.
2. No other deviation of substance from the task's design spec for the
   processor math, state shape, or pipeline-ordering contract -- the
   suggested `HealingProcessor.process` signature, the per-spot dict
   shape, the clone/heal blend formulas, and the "healing goes first"
   ordering decision were all followed as given.

**Verification.** New/changed test files: `tests/unit/test_processors/
test_healing_processor.py` (21 tests, new), `tests/unit/test_processing/
test_processing_queue.py` (+2 tests), `tests/unit/test_processing/
test_processing_worker.py` (`TestProcessingWorkerHealing`, 7 tests, new),
`tests/unit/test_commands/test_adjustment_commands.py` (+2 tests),
`tests/unit/test_controllers/test_image_controller.py`
(`TestImageControllerHealing`, 17 tests, new) -- all passing in
file-scoped runs, and the full `tests/unit/` suite (1122 passed, 1
skipped) with no regressions. Full suite run per the task's verification
command; see the calling session's own run for the final authoritative
pass count. This slice's own local run observed the same pre-existing,
documented `test_geometry_is_restored_on_next_launch` offscreen-platform
flake already noted in every prior implementation note (deselected, not
fixed, per the task's own instructions), plus one additional
already-known, unrelated native-crash-at-interpreter/thread-teardown
flake surfaced once during a full-suite run (a worker thread still
mid-`ExposureProcessor.process` during `ImageController.cleanup()`'s
`processing_worker.stop()` in `tests/performance/test_integrated_performance.py`)
-- a clean rerun passed with no failures, confirming it is a
pre-existing teardown-timing flake unrelated to this slice's own code
(Healing is not on that particular test's failure path; the traceback
points at Exposure processing racing thread shutdown, code untouched by
this slice).
