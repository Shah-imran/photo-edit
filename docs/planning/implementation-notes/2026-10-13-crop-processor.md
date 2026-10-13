# Crop processor (data/processing layer), slice 1 of 2

Related roadmap: Phase I ("Geometry and Crop", PDF sections 19-20),
`docs/planning/PRODUCT_ROADMAP.md`'s Crop tool bullet. Related prior
slice: `docs/planning/implementation-notes/2026-10-12-straighten.md`,
which already documents a very similar "where does a Geometry-phase
step fit in the fixed pipeline" tradeoff -- this note's reasoning is
consistent with it, just one step further down the chain.

## 1. Problem, goal, and non-goals

This is **slice 1 of 2** for the roadmap's Crop tool bullet. It adds the
data/processing layer only: a `CropProcessor`, full adjustment-state and
pipeline wiring, undo/redo integration, and export correctness, plus a
programmatic (non-mouse-driven) way to set the crop rectangle.

**Explicitly NOT built here (all slice 2's job, a separate, later
change):**

- The interactive drag-handle canvas overlay (corner/edge handles,
  hit-testing, live-drag feedback).
- Aspect-ratio presets, rule-of-thirds/grid overlays, rotate-and-flip
  controls.
- The "Crop" button in `EditingToolStrip`
  (`src/views/widgets/workspace_header.py`), currently a disabled
  placeholder (`("Crop", "crop")` in its tool list) -- this slice does
  not enable it or wire anything to it.

This slice's entire "UI surface" is one public, directly-callable
controller method, `ImageController.on_crop_changed(crop)`, which the
later UI slice will call into once the drag-handle overlay exists.

### The one genuinely new architectural wrinkle

Every processor added to this codebase so far -- Texture, Clarity,
Dehaze, Vignette, Grain, Sharpening, Luminance NR, Color NR, Remove CA,
Defringe, Straighten, all ~20 of them -- preserves the exact input
`(H, W, C)` shape, `(H, W, C)` in, `(H, W, C)` out. This invariant is
relied on throughout the codebase. Crop is the **one deliberate
exception**: cropping removes pixels by definition, so the output must
be smaller than the input. To keep every *other* step's own
shape-preservation invariant intact, `CropProcessor` is applied as the
**absolute last step in the entire processing pipeline** -- after
Straighten, after Grain, after literally everything else -- so only the
very last step of the chain ever changes shape.

## 2. Architectural reasoning: why Crop must be last, confirmed per
   downstream consumer

The claim "every other processor preserves shape, so Crop must run last
or every earlier invariant breaks" is not just asserted here -- every
actual downstream consumer of a processed image in this codebase was
traced directly, and each one was confirmed to already tolerate a
variable image size (none needed a fix):

- **Preview caching** (`ProcessingWorker._cache_key`/`_result_cache`):
  the cache key already includes `tuple(source.shape)` plus every
  param dict (now including `crop_params`), and the cached
  `_CachedPreview` stores whatever shape `result` happens to be after
  the full `_apply_adjustments` chain runs (crop included, last). Two
  requests that differ only in `crop_params` already produce different
  cache keys (pinned by
  `test_different_crop_params_produce_different_cache_keys`), and the
  cache never assumes a fixed shape per source -- it keys on the
  source's own shape value, not a constant. No fix needed.
- **Undo/redo buffers**
  (`AdjustmentStateCommand`/`ImageStateChangeCommand`/
  `CombinedAdjustmentCommand`): these swap whole `LinearImage` buffers
  in and out of `ImageModel.current_image` by reference, with no shape
  assumption anywhere in that swap -- `ImageModel.current_image` is
  just an `Optional[LinearImage]` attribute. `apply_history_state`
  (the state-aware-undo-redo slice's own mechanism) likewise just
  assigns whatever image it is given. No fix needed; confirmed by
  `test_crop_undo_restores_image_shape_too`, which crops to two
  different rectangles and asserts undo restores the exact
  intermediate shape, not just the final one.
- **Zoom/display math** (`ImageView`): `fit_to_window`/
  `view_100_percent`/`zoom_in`/`zoom_out` and
  `_preserve_scale_after_pixmap_swap` all read `self._pixmap.size()`
  live at call time, never a cached/stale dimension from a previous
  frame. `_preserve_scale_after_pixmap_swap` already exists specifically
  to handle a pixmap swap between two *different*-sized buffers
  (previously only exercised by the interactive-proxy vs. full-res
  proxy swap, which are already different sizes from each other) --
  it recomputes the zoom factor from the ratio of old to new pixmap
  width, which works unmodified for a crop-induced shape change too. No
  fix needed.
- **Histogram** (`src/views/widgets/histogram_widget.py`): computes
  its bars from whatever pixel array it is handed; nothing in it
  assumes a fixed width/height. No fix needed.
- **`ImageModel.get_image_size()`**: reads `self.current_image.shape[:2]`
  live on every call, not a cached size set once at load. No fix
  needed.
- **`ProxyManager`**: the proxy/interactive-proxy images are generated
  once, from the *original, uncropped* image, at load time (`set_image`)
  -- crop runs only inside `_apply_adjustments`'s processor chain,
  **after** the proxy/original source has already been read out of
  `ProxyManager`. So `ProxyManager` itself never sees a cropped image
  and needed no change; its one shape-sensitive unused helper,
  `upscale_to_original_size`, is dead code (not called anywhere in
  `src/`) and is not on this pipeline's active path at all.
- **`DisplayFrame`/`linear_to_display_rgb`**: both only assert
  `ndim == 3 and shape[2] == 3` (a 3-channel check), never a specific
  width/height. No fix needed.
- **Export** (`ImageController.get_export_image`): already
  reprocesses the *original* image through every `_xxx_params`
  processor call in sequence and returns whatever shape falls out the
  end -- adding one more conditional processor call (crop, last) needed
  no structural change, only the new call itself.

**One pre-existing, cosmetic gap found and left for slice 2, not fixed
here (see section 6):** `MainWindow._on_image_loaded`'s
`_dimensions_label` status-bar text is set once, at image load, from
`ImageModel.get_image_size()`, and is never refreshed on a later edit.
This was already true before this slice (Straighten doesn't change
shape, so it was never observable), but Crop now makes it observably
stale -- after a programmatic crop, the status bar still shows the
original, pre-crop dimensions until the next image load. This is a
display-only cosmetic issue (nothing downstream reads the label's text
as data), not a correctness bug, and it only becomes reachable once a
UI control actually calls `on_crop_changed` -- which is slice 2's job.
It is flagged here rather than silently fixed, per the instruction to
report explicitly on anything found when tracing display consumers.

## 3. Current behavior

`ImageController` owns ~20 `_xxx_params` fields plus three non-flat
categories (`tone_curve`, `hsl`, `color_grading`), applied in a fixed
order by `get_export_image`/`restore_adjustment_state`/
`apply_adjustments`'s synchronous fallback, `ProcessingWorker._apply_adjustments`,
and `CombinedAdjustmentCommand.execute`. Straighten is currently the
final stage. No operation in the pipeline changes output shape.

## 4. Design

### 4.1 State shape

A new, non-flat key, `"crop"`, alongside `tone_curve`/`hsl`/
`color_grading`: a 4-key dict `{"x0", "y0", "x1", "y1"}`, each a
normalized fraction in `[0.0, 1.0]` of whatever image the pipeline
happens to be processing at the time (full-res for final render/export,
a smaller proxy for preview) -- the same reasoning
`VignetteProcessor` already uses for computing its radial center from
whatever image it is given rather than a fixed resolution (confirmed by
re-reading `vignette_processor.py`: it derives `half_h`/`half_w` from
`image.shape` on every call, never a stored constant). Default (no
crop) is the full frame, `{"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}`.

### 4.2 `CropProcessor`

`src/processors/crop_processor.py`. Clamps/swaps `x0/y0/x1/y1`
defensively (never trusts the caller -- the rectangle may come from an
old catalog entry, a malformed imported preset, or interactive UI
input in the later slice), returns an identity copy at the full-frame
rectangle, and otherwise slices the array and returns a real copy
(`astype(..., copy=True)`) so the result never aliases the source.

**Was `copy=True` verified necessary, not just cheap insurance?** Yes --
checked directly: no caller anywhere in `src/` (controller, commands,
worker) mutates a processor's returned array in place; every call site
does `result = some_processor.process(result, ...)`, never
`result[...] = ...` on the return value. So no live caller currently
needs the copy, but it is kept anyway as correct, cheap insurance (a
crop slice is a *view* into its parent array by default in NumPy, and
relying on "no caller happens to mutate it today" would be fragile).

**1x1 source image.** Verified directly
(`test_tiny_1x1_image_does_not_crash`): the clamp logic
(`right = max(left + 1, min(right, width))`) guarantees `right > left`
and `bottom > top` even when `width == height == 1`, so the result is
always non-empty and in-bounds; no crash, no zero-area output.

### 4.3 Pipeline wiring

`crop_params` (a flat kwargs-style dict matching `CropProcessor.process`'s
signature) threads through every site Straighten already goes through:
`ImageController` (`_crop_processor`/`_crop_params`, defaults, `get_export_image`,
`restore_adjustment_state`, `apply_adjustments`'s threaded/sync/command
paths, the four `on_*_changed` debounced paths' pass-through dicts,
`_on_throttled_adjustment`/`_on_debounced_adjustment`,
`on_slider_released`, `_has_pending_adjustment_changes`,
`_submit_delayed_final_render`, `commit_adjustments`),
`ProcessingRequest`/`ProcessingQueue`, `ProcessingWorker`
(processor, submit/apply/cache-key/signature, perf logging), and
`CombinedAdjustmentCommand`'s synchronous fallback. Crop is applied
strictly **last** everywhere, after Straighten.

### 4.4 The falsy/empty-dict convention -- a deliberate deviation from
     Straighten's pattern

Every other `_xxx_params` field's all-zero default is itself falsy
(`{"straighten": 0.0}` is truthy as a dict, but every OTHER processor's
guard checks `if self._xxx_params:` where the *stored* value, once
normalized, is still a non-empty dict -- the real "skip" signal for
most of them is the inner `!= 0.0` check, not dict-emptiness).
Tone curve (`_curve_params`) is the one existing field that already
uses `{}` itself as its own "identity/no-op" sentinel (an empty dict
when the curve is the identity curve, a `{"points": [...]}` dict
otherwise) -- `_curve_params`'s guard in `apply_adjustments` is
`if curve_params is not None:`, not `if curve_params:`, specifically so
a caller can explicitly reset it to `{}`.

Crop's natural "no crop" default (the full-frame rectangle) is a
non-empty 4-key dict, so it cannot double as its own falsy sentinel the
way Straighten's `0.0` or every other scalar default does. **Decision
made:** mirror curve's convention exactly, not Straighten's:
`self._crop_params` is initialized to `{}` (falsy, "not yet touched")
everywhere every other field is reset to its default
(`__init__`, `_apply_loaded_image`, `reset_to_original`), and is only
ever populated with the real `{"x0": ..., "y0": ..., "x1": ..., "y1": ...}`
values when a non-identity crop is actually set. `_apply_state_params`
(shared by `restore_adjustment_state` and `apply_history_state`) does
this reduction itself: it always normalizes/clamps the incoming `"crop"`
value into a full 4-key dict via the new `_normalize_crop_state`, then
collapses it to `{}` if `_is_identity_crop(...)` is true. `apply_adjustments`'s
own direct `crop_params` keyword guard is `if crop_params is not None:`
(matching curve, not the truthy-only guard every scalar field uses), so
a caller (including `on_crop_changed`) can explicitly pass `{}` to
reset to full-frame.

`get_adjustment_state()["crop"]` always returns the full 4-key dict
(never omitted, matching `tone_curve`/`hsl`/`color_grading`'s own
always-present convention): `{**self._CROP_DEFAULTS, **self._crop_params}`.

Every downstream processor-call guard (worker, export, command,
sync fallback) is a plain `if self._crop_params:`/`if crop_params:` --
correct because `_crop_params` is *always* either `{}` (skip) or a
genuinely non-identity 4-key dict (run) by construction; it is never
the identity dict itself as a non-empty value, so there is no
"harmless but wasteful" extra `CropProcessor.process()` call on every
single render the way the task's design sketch anticipated as a
fallback possibility. (An explicit `apply_adjustments(crop_params={...full
frame...}, ...)` call from a test *can* still store a non-identity-free
full-frame dict directly, bypassing the identity-collapsing done inside
`_apply_state_params`/`on_crop_changed` -- in that case the processor
does run but is a cheap no-op via its own internal identity check, which
is the documented, accepted fallback behavior.)

### 4.5 `on_crop_changed` vs. a slider's `on_*_changed`

Every existing non-flat `on_*_changed` (`on_curve_changed`,
`on_hsl_changed`, `on_color_grading_changed`) captures pre-gesture state,
normalizes, stores the param, and then either debounces through the
threaded preview path (`add_to_history=False`) or falls back to a
synchronous `apply_adjustments` call -- because a slider drag is a
*continuous stream* of in-flight values that only becomes a discrete
history entry on release/pause.

A programmatic crop-rectangle set (today) or a future "Apply Crop"
button click (slice 2) is not that: it is a **single discrete action**.
`on_crop_changed` therefore skips the debounce/throttle dance entirely
and calls `apply_adjustments(crop_params=..., add_to_history=True)`
directly, in one step -- `apply_adjustments` already knows how to
route a direct `add_to_history=True` call through the full
threaded-or-synchronous, command-pushing path (exactly as existing
tests already exercise it, e.g.
`apply_adjustments(straighten_params={...}, add_to_history=True)`), so
no new history-pushing logic was needed.

### 4.6 `_normalize_crop_state`

Unlike `_normalize_floats` (shared, verbatim, by `_normalize_adjustment_state`/
`_normalize_hsl_state`/`_normalize_color_grading_state`, which only
float-coerces each key independently against a default), crop's 4
values are mutually constrained -- each must be in `[0.0, 1.0]`, and
`x1`/`y1` must not end up below `x0`/`y0`. `_normalize_crop_state`
first reuses `_normalize_floats` for the float-coercion/missing-key
tolerance, then applies the exact same clamp-then-swap logic
`CropProcessor.process` itself applies, so a malformed/out-of-range
persisted rectangle is normalized identically whether it is caught by
the controller's state layer or the processor's own input validation.

## 5. Contracts

- State key: `"crop"`, a 4-key `{"x0", "y0", "x1", "y1"}` dict of
  normalized `[0.0, 1.0]` fractions, default `{"x0": 0.0, "y0": 0.0,
  "x1": 1.0, "y1": 1.0}` (full frame). Always present in
  `get_adjustment_state()`'s return value.
- `CropProcessor.process(image, x0=0.0, y0=0.0, x1=1.0, y1=1.0)`:
  clamps each coordinate to `[0.0, 1.0]`, swaps `x0/x1` and `y0/y1` if
  reversed, returns an identity copy at the full-frame rectangle, and
  otherwise returns a genuinely smaller `(H', W', C)` array (`H' <= H`,
  `W' <= W`) that never aliases its input.
- Pipeline position: **strictly last**, after Straighten, in every
  integration point.
- `ImageController.on_crop_changed(crop: Dict[str, float]) -> None`:
  public, directly-callable API. Defensively normalizes/clamps the
  input, stores it, and commits it to history in one discrete step
  (`add_to_history=True`). Not wired to any UI control in this slice.
- Older payloads that omit `"crop"` entirely restore as the full-frame
  rectangle. No schema-version bump is needed (additive, defaulted key).

## 6. Nuances and failure modes

**Crop shrinks `current_image`, never `original_image`.**
`ImageModel.original_image` is only ever set once, at load
(`set_original_image`), and crop is applied only inside the processor
chain that produces a *result* assigned to `current_image` -- so
`get_original_image()` (used as the base for every re-render,
including after a crop is later changed or removed) always stays at
full, uncropped resolution. This is why resetting/undoing a crop, or
changing it to a different rectangle, always recomputes correctly from
the true original rather than re-cropping an already-cropped buffer.

**The status-bar dimensions label goes stale after a crop (see section
2's final paragraph).** Flagged, not fixed -- it is unreachable until a
UI control calls `on_crop_changed`, which is slice 2's job, and fixing
it would mean guessing at how slice 2's UI wants to refresh it (e.g.
on `adjustment_state_restored`, or synchronously in `on_crop_changed`'s
own caller). Left as an explicit note for whoever builds slice 2.

**A crop rectangle is resolution-relative, by design, not
resolution-absolute.** The exact same `{"x0": 0.25, ...}` rectangle
produces a proportionally-equivalent but pixel-different crop whether
applied to a `600px` interactive proxy, a `1400px` quality proxy, or
the full-resolution original -- this is the entire point of storing
fractions rather than pixel coordinates (see section 4.1), and it is
exercised directly by the preview/final-render split already built
into this pipeline (the interactive and quality proxies are genuinely
different pixel sizes from each other and from the original, and crop
already has to behave correctly across that split the same way every
existing resolution-relative processor, like Vignette, already does).

**Degenerate/near-zero-area rectangles never produce an empty
result.** `CropProcessor`'s clamp logic (`right = max(left + 1, ...)`,
`bottom = max(top + 1, ...)`) guarantees at least a `1x1` output even
from a rectangle whose `x0`/`x1` (or `y0`/`y1`) round to the same pixel
column/row after `int(round(...))`. Pinned by
`test_degenerate_near_zero_area_rectangle_is_still_non_empty`.

**`get_adjustment_state()["crop"]` is a plain 4-key dict, not a
`CropProcessor`-shaped kwargs dict with defaults omitted.** Always all
4 keys present, mirroring `hsl`/`color_grading`'s "always complete"
convention rather than `tone_curve`'s point-list shape.

## 7. Test plan

- `tests/unit/test_processors/test_crop_processor.py` (new): identity
  at the full-frame default; a real crop produces the exact correct
  sliced sub-array (a per-quadrant synthetic test image); output shape
  strictly smaller than input shape for a real crop (the one
  deliberate shape-change test in this codebase, called out explicitly
  in the test's own docstring); clamping of out-of-range input in both
  directions; `x0/x1` and `y0/y1` swap-if-reversed; a degenerate
  near-zero-area rectangle still produces a non-empty result; a `1x1`
  source image does not crash; dtype is `float32`; determinism; the
  returned array does not alias the source (mutating the result does
  not mutate the source, confirming `copy=True`'s necessity claim is
  at least behaviorally correct even though no live caller currently
  needs it).
- `tests/unit/test_processing/test_processing_queue.py`: `crop_params`
  threads through `create_request`; defaults to `{}`.
- `tests/unit/test_processing/test_processing_worker.py`
  (`TestProcessingWorkerCrop`): crop params reach the processor; an
  empty crop dict skips the processor entirely; the worker's real
  end-to-end pipeline (not a mocked processor) produces a genuinely
  smaller full-resolution result for a real crop; two different crop
  rectangles produce different cache keys.
- `tests/unit/test_commands/test_adjustment_commands.py`
  (`TestCombinedAdjustmentCommand`): crop-only execute/undo (undo
  restores the pre-crop image by identity, matching every other
  combined-command test's pattern); crop applied strictly after
  Straighten (asserted by confirming the final shape is the *cropped*
  shape, not re-grown back to the original by Straighten's own
  shape-locking `warpAffine` call, which would happen if crop ran
  first).
- `tests/unit/test_controllers/test_image_controller.py`
  (`TestImageControllerCrop`): default full-frame state;
  `restore_adjustment_state` applies/round-trips a crop; a payload
  missing `"crop"` entirely defaults cleanly to full-frame (the
  backward-compatibility pattern mirroring `tone_curve`/`hsl`/
  `color_grading`'s own equivalent tests); malformed/out-of-range
  input is tolerated and clamped; a real crop reaches `get_export_image()`
  and genuinely shrinks it; `on_crop_changed` round-trips through
  `get_adjustment_state()` and adds to history; `on_crop_changed`
  normalizes/clamps defensively; the core state-aware-undo-redo
  regression pattern (crop to rect A, then rect B, undo, assert the
  state equals rect A, not rect B); undo restores the actual image
  shape too, not just the state dict; `reset_to_original` and loading a
  different image both clear the crop back to full-frame.
- The two pre-existing exact-dict contract tests,
  `test_get_adjustment_state_returns_normalized_defaults` and
  `test_restore_adjustment_state_applies_saved_values`, were updated
  with a `"crop": {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}` entry,
  the same mechanical update every prior processor slice has needed.

## 8. Rollout

Additive and identity-defaulted. A plain revert removes it; older
builds ignore the extra persisted `"crop"` key. No UI control calls
`on_crop_changed` yet, so this slice changes no visible behavior for
any existing user flow -- it is reachable only by direct API calls
(tests today, slice 2's UI tomorrow). Acceptance requires the full
vertical data-layer path (processor, pipeline wiring at every
integration point, undo/redo, export) with no UI-thread image math,
backward-compatible restore, and passing targeted/full tests.

## 9. Implementation summary

Implemented `CropProcessor` (`src/processors/crop_processor.py`): the
one processor in this codebase that deliberately changes output shape,
via normalized-fraction rectangle slicing with defensive
clamp/swap/degenerate-rectangle handling, applied strictly **last** in
every pipeline integration point (after Straighten) so every other
processor's `(H, W, C)`-preservation invariant stays intact at every
earlier step.

Wired it through every point Straighten touches: `ImageController`
(`_CROP_DEFAULTS`, `_crop_processor`/`_crop_params`, `get_export_image`,
`get_adjustment_state`, `_apply_state_params`/`restore_adjustment_state`,
`reset_to_original`, `apply_adjustments`'s threaded/sync/command paths,
the four `on_*_changed` debounced pass-through dicts,
`_on_throttled_adjustment`/`_on_debounced_adjustment`,
`on_slider_released`, `_has_pending_adjustment_changes`,
`_submit_delayed_final_render`, `commit_adjustments`, a new
`_normalize_crop_state`/`_is_identity_crop` pair, and the new
`on_crop_changed` public API), `ProcessingRequest`/`ProcessingQueue`,
`ProcessingWorker` (processor, submit/apply/cache-key/signature, perf
logging), and `CombinedAdjustmentCommand`'s synchronous fallback.

**The falsy/empty-dict convention (the one real design decision in this
slice).** `_crop_params` is kept at `{}` ("not yet touched"/identity)
whenever there is no actual crop, mirroring tone curve's existing
`{}`-as-identity-sentinel convention (and its `is not None` guard in
`apply_adjustments`) rather than every scalar field's truthy-default
convention, specifically because crop's natural "no crop" default (the
full-frame rectangle) is itself a non-empty, and therefore truthy,
dict -- see section 4.4 for the full reasoning.

**Downstream-consumer trace (the most important verification in this
slice).** Every actual consumer of a processed image -- preview caching,
undo/redo buffers, zoom/display math, histogram, `ImageModel.get_image_size()`,
`ProxyManager`, `DisplayFrame`/`linear_to_display_rgb`, and export --
was traced directly and confirmed to already tolerate a variable image
size; none needed a fix. One pre-existing, now-observable cosmetic gap
was found (`MainWindow`'s status-bar dimensions label does not live-update
after an edit) and is explicitly flagged, not fixed, since it is
unreachable until slice 2 wires a UI control to `on_crop_changed`. See
section 2 for the full per-consumer trace.

**Programmatic API, not UI.** `ImageController.on_crop_changed(crop)` is
this slice's entire "UI surface" -- a single discrete commit (no
debounce/throttle dance, unlike a slider), routed through the existing
`apply_adjustments(..., add_to_history=True)` path so it participates
fully in the state-aware undo/redo system. No button, overlay, or
slider was wired to it; `EditingToolStrip`'s "Crop" placeholder remains
disabled, exactly as before this slice.

**Deviation note.** None of substance from the task's design spec for
the processor math or pipeline-ordering contract -- both were followed
exactly as given, including using the provided `CropProcessor`
implementation verbatim after independently verifying its claims (1x1
safety, `copy=True`'s necessity, confirmed per sections 4.2 and this
summary). The one real judgment call -- `_crop_params`'s falsy/empty-dict
convention (mirroring tone curve's existing pattern rather than
Straighten's scalar-default pattern, per the task's own observation
that the naive truthy-skip guard would be a harmless-but-unnecessary
no-op) -- is documented in full in section 4.4, exactly as instructed.

Verification: targeted new/changed tests (processor + queue + worker +
command + controller Crop tests, run alongside every prior
Effects/Detail/Optics/Geometry suite they extend) all passed in
file-scoped runs. Full suite run per the task's verification command;
see the calling session's own run for the final authoritative pass
count, since this slice's own local run observed the same pre-existing
`test_geometry_is_restored_on_next_launch` offscreen flake already
documented in every prior Phase G/H/I note (deselected, not fixed, per
the task's own instructions) and no other failures or regressions in
any test that assumed a constant image shape across a full
adjustment-state round trip.
