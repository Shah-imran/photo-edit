# Luminance Noise Reduction adjustment

Related roadmap: Phase G / PDF section 16. Related workflow: `INCREMENTAL_WORKFLOW.md` sections 4 and 5.1.
Related prior slices: docs/planning/implementation-notes/2026-09-30-texture.md,
docs/planning/implementation-notes/2026-10-12-clarity.md,
docs/planning/implementation-notes/2026-10-12-dehaze.md,
docs/planning/implementation-notes/2026-10-12-vignette.md,
docs/planning/implementation-notes/2026-10-12-grain.md,
docs/planning/implementation-notes/2026-10-12-sharpening.md.

## 1. Problem, goal, and non-goals

Sharpening shipped the first of the Detail group's three items. This
slice adds the second: Luminance Noise Reduction ("Luminance NR"), a
second zero-by-default slider added into the *existing* "Detail"
`ToolsPanel` section (not a new section), directly below Sharpening. It
does not add Lightroom's full Luminance NR sub-panel (separate Detail/
Contrast sub-sliders) -- only the single "Luminance NR" amount slider,
matching how every other Phase G control shipped as a single slider. It
also does not add Color Noise Reduction -- the third and final Detail
item, left for a future slice (see section 6 for the resulting Phase G
status).

## 2. Current behavior

`ToolsPanel`'s "Detail" section (added by the Sharpening slice) holds one
slider, Sharpening, with its own section-level reset button.
`ImageController` owns normalized state and coordinates preview/final
rendering; `ProcessingRequest` and `ProcessingWorker` carry category
dictionaries; `CombinedAdjustmentCommand` provides the synchronous undo
fallback. Sharpening is currently the final pipeline stage, applied right
after Grain.

## 3. Design and flow

Add a second slider, "Luminance NR", to the existing Detail section,
directly below Sharpening, sharing the section's existing "Reset Detail"
button (now resetting both sliders). Luminance NR remains a top-level
persisted float for consistency with other single-slider controls, while
processing APIs carry `{"luminance_nr": value}` as a separate category,
following Sharpening's wiring pattern exactly
(`luminance_nr_processor`/`_luminance_nr_params`/`luminance_nr_params`, by
direct analogy to `sharpening_processor`/`_sharpening_params`/
`sharpening_params`). The controller sends it through preview, final,
synchronous, restore, export, reset, and history paths. The worker
applies it after Sharpening and includes it in preview cache signatures.
Pipeline order is now
... Grain -> Sharpening -> Luminance NR, so Luminance NR is the new final
stage. This ordering is deliberate, not incidental: noise reduction
conventionally runs near the very end of a simplified linear pipeline,
*after* sharpening, because sharpening's unsharp-mask step amplifies
whatever fine-scale detail is present in the image at that point --
including sensor noise and the grain just added by the Grain control --
and NR needs to see (and calm) that amplified noise, not the
pre-sharpening noise floor.

`LuminanceNoiseReductionProcessor` is the first Detail/Effects processor
built from neither a Gaussian-blur residual (Texture/Clarity/Dehaze/
Sharpening) nor a radial mask (Vignette) nor seeded noise (Grain).
Instead it uses an **edge-preserving smoothing filter**
(`cv2.bilateralFilter`) applied to a **luminance-only** channel:

```
luminance = 0.2126*R + 0.7152*G + 0.0722*B           # Rec.709 weights
smoothed  = cv2.bilateralFilter(luminance, d=9, sigmaColor=0.1, sigmaSpace=9)
delta     = smoothed - luminance
t         = luminance_nr / 100.0
result[c] = source[c] + t * delta   for each channel c (broadcast)
```

Deriving a scalar luminance channel, smoothing *only* that channel with a
filter whose range term (`sigmaColor`) suppresses smoothing across large
intensity jumps (i.e. it preserves edges, unlike a plain Gaussian blur),
and then adding the resulting *luminance delta* equally to all three
channels is what keeps this "luminance-only": every pixel's luminance is
shifted toward its locally-smoothed value, but its chrominance (the
per-channel *ratios*, i.e. hue and saturation) is left completely intact,
because the same scalar delta is added to R, G, and B alike. This is the
entire reason Luminance NR exists as a distinct control from a plain
denoising blur -- it removes brightness-variation noise without
smearing color detail or softening color edges, which `cv2.bilateralFilter`
applied directly to all three RGB channels (or, worse, a plain Gaussian
blur) would do.

Luminance NR is one-directional (`0..100`, Lightroom "Amount" semantics
-- there is no "add noise" direction), like Grain and Sharpening, unlike
Texture/Clarity/Dehaze/Vignette's `-100..100`. Zero returns `source.copy()`
immediately, skipping the bilateral filter call entirely -- see section 6
for why this matters more here than for any prior processor.

## 4. Contracts and compatibility

- State key: `luminance_nr` (not `luminance_noise_reduction` -- kept
  short like the other single-word/short-phrase Detail/Effects keys),
  finite numeric float, default `0.0`.
- UI and processor range: `0..100` (one-directional, like Grain and
  Sharpening); the processor clamps out-of-range callers (including
  negative values, which clamp to `0`, i.e. identity).
- Older payloads that omit the key restore as zero.
- No schema-version bump is needed because this is an additive defaulted
  key.
- `cv2` (already a dependency via Texture/Clarity/Dehaze/Grain/
  Sharpening) is reused for the bilateral filter; no new dependency is
  added.

## 5. Nuances and failure modes

**Why bilateral, and why these constants.** `cv2.bilateralFilter`
combines a spatial Gaussian term with a *range* (intensity-difference)
Gaussian term, so it only averages together pixels that are both
spatially close *and* similar in value -- this is what makes it
edge-preserving, unlike `cv2.GaussianBlur`, which averages indiscriminately
and would smear real edges along with noise. `d=9` picks a 9x9 pixel
neighborhood -- a modest, fixed spatial extent in the same spirit as
Sharpening's `sigma=1.0` Gaussian and Grain's ~1/3-resolution noise field
(small, fixed internal parameters rather than user-exposed sub-controls).
`sigmaColor=0.1` is in the same linear-light units as the image itself
(nominally `[0, 1]`, with HDR headroom beyond that); it is small enough
that genuine edges (a meaningfully large fraction of the full range) are
still treated as edges and barely smoothed across, while being large
enough to meaningfully average down sensor-noise/grain-scale luminance
jitter, which is typically much smaller in magnitude than a real edge.
`sigmaSpace=9.0` matches the diameter in spatial extent, the usual OpenCV
convention when `d > 0` (the alternative `d <= 0` form, which derives the
neighborhood size from `sigmaSpace` alone, was considered but not used --
an explicit, fixed `d` is easier to reason about and test against, and
keeps this processor's behavior independent of OpenCV's internal
`d <= 0` sizing heuristic). These three constants were validated directly:
on a synthetic flat patch with injected Gaussian noise
(`sigma=0.05` on a `0.5` base), the bilateral filter at full strength
reduces measured luminance variance by roughly an order of magnitude
(`test_positive_value_reduces_luminance_variance`), while a colorful
two-tone edge image's color identity (which side reads red-dominant vs.
blue-dominant) and overall per-channel change remain intact
(`test_preserves_color_ratios_on_colorful_edge_image`).

**Determinism.** Like Sharpening (and unlike Grain), Luminance NR is a
pure, deterministic function of `(image, luminance_nr)` -- `cv2.bilateralFilter`
has no RNG involved. `process()` called twice with the same inputs
returns byte-identical output, pinned directly by
`test_is_deterministic_pure_function`, matching this codebase's general
idempotency expectation (the preview cache and every non-Grain processor
rely on it).

**Tiny/degenerate images.** `cv2.bilateralFilter` was tested directly
against `1x1` and `2x2` float32 inputs (and `3x3`/`5x5`) before writing
this processor, and it did **not** crash or raise on any of them -- it
simply returns an array of the same shape (for a `1x1` input, trivially
unchanged, since there is only one pixel and no neighborhood to average
against). Despite this, a defensive bypass is still included:
`min(height, width) < _MIN_FILTER_DIMENSION` (`_MIN_FILTER_DIMENSION = 3`)
skips the filter call entirely and returns an identity copy (equivalent
to treating `delta` as all-zero). This is not working around an observed
crash -- none occurred in testing against this OpenCV version -- but is
kept anyway as cheap insurance against a degenerate-input edge case in a
future OpenCV version, and because a 9x9-neighborhood filter is not
spatially meaningful on a 1x1/2x2 image regardless of whether OpenCV
happens to accept it. `test_tiny_1x1_image_does_not_crash` and
`test_tiny_2x2_image_does_not_crash` both pin this directly.

**Pipeline position and why NR follows sharpening.** Luminance NR is
applied immediately after Sharpening everywhere in the pipeline
(controller `get_export_image`/`restore_adjustment_state`/
`apply_adjustments` paths, `ProcessingWorker._apply_adjustments`,
`CombinedAdjustmentCommand.execute`). This mirrors the real-world editing
convention (and Lightroom's own Detail panel ordering intent, even though
Lightroom applies both as part of one coupled render rather than two
independent sequential stages) that noise reduction should see the
*sharpened* image, including whatever fine-scale noise sharpening's
unsharp-mask step amplified, so that NR has something meaningful to act
on rather than running on a pre-sharpening noise floor that sharpening
would then re-amplify downstream.

**No clipping, dtype/shape preserved.** Like every prior Effects/Detail
processor, Luminance NR does not clip its output, preserving HDR
headroom. Output dtype (`float32`) and shape are retained
unconditionally, pinned by
`test_preserves_dtype_shape_and_headroom_without_clipping`.

## 6. UI/reskin, dependencies, and performance

The view contains only the slider and emits plain data; all math stays in
the processor. Existing throttling, cancellation, interactive proxies,
quality preview, and delayed full-resolution rendering remain unchanged.
No new `CollapsibleSection` is created -- the slider is added directly
into the existing "Detail" section's content layout, right after
Sharpening, and both sliders now share the section's single "Reset
Detail" header button. No new dependency is added (`cv2` is already a
Texture/Clarity/Dehaze/Grain/Sharpening dependency).

**Performance matters more here than for prior processors.** Bilateral
filtering is a substantially more expensive per-pixel operation than a
separable Gaussian blur (it cannot be decomposed into two 1-D passes the
way a Gaussian can, since its range term depends on the actual pixel
values in the neighborhood, not just their positions), so the early
`luminance_nr == 0.0` return -- skipping luminance-channel computation and
the bilateral filter call entirely -- is a more load-bearing optimization
for this processor than Sharpening's equivalent early return on
`sharpening == 0.0`; the overwhelmingly common default/no-op case must
never touch `cv2.bilateralFilter`. This was not observed to be a
bottleneck in the automated suite's own synthetic test images (all of
which are small), but is worth calling out for anyone profiling a large
real photo with Luminance NR active.

This completes the second of Phase G's Detail group's three items
(Sharpening, Luminance NR done; Color NR remains). After this slice,
Phase G's Effects group (Texture, Clarity, Dehaze, Vignette, Grain) and
two of three Detail items (Sharpening, Luminance NR) are complete; **Color
Noise Reduction is the one remaining gap in Phase G**, left for a future
slice.

## 7. Test plan and manual smoke

Automated coverage pins identity/copy behavior at zero, positive Luminance
NR measurably reducing luminance variance on a synthetic noisy flat
patch (deterministic noise via `np.random.default_rng` with a fixed
seed, confirming the *test* is reproducible even though the processor
itself has no randomness), determinism (same image and amount processed
twice is byte-identical, since `cv2.bilateralFilter` has no RNG),
color-ratio/chrominance preservation on a colorful two-tone edge image
(no gross desaturation or color shift), dtype/shape/headroom preservation
without clipping, parameter clamping in both directions (negative clamps
to zero/identity; above 100 clamps to 100), and `1x1`/`2x2` images not
crashing (exercising the defensive small-image bypass). Integration
coverage mirrors Sharpening's test structure file-for-file: queue param
threading, worker propagation/skip-at-zero behavior and cache-key
sensitivity to Luminance NR params, controller persistence/export/undo,
command undo, and UI range (`0..100`)/emission/restore/membership in the
existing Detail section's shared reset button (now covering both
sliders). Run the complete suite.

Manual: open a noisy/grainy image; move Luminance NR from 0 upward;
verify a responsive preview showing reduced luminance noise/grain texture
without visible color smearing or desaturation at edges, final render on
release, undo/redo, reset (both Detail sliders together via "Reset
Detail", not the rest of Effects), image-switch restore, and export, with
Texture, Clarity, Dehaze, Vignette, Grain, Sharpening, and Luminance NR
active together.

## 8. Rollout, rollback, and acceptance

The feature is additive and identity-defaulted. A plain revert removes
it; older builds ignore the extra persisted key. Acceptance requires the
full vertical path, no UI-thread image math, backward-compatible restore,
passing targeted/full tests, clean diff checks, and honest manual-test
reporting.

Plan approved -- implementation allowed: mirrors the approved Texture/
Clarity/Dehaze/Vignette/Grain/Sharpening slices' scope and wiring pattern
(2026-10-12).

## 9. Implementation summary

Implemented `LuminanceNoiseReductionProcessor` (deterministic
Rec.709-luminance-channel bilateral filter with fixed constants `d=9`,
`sigmaColor=0.1`, `sigmaSpace=9.0`; one-directional `0..100` range; the
smoothed-luminance delta broadcast equally across all three channels to
preserve chrominance; a defensive bypass below `min(height, width) = 3`)
and wired it through every integration point Sharpening touches:
`ImageController` (defaults, processor/params state, preview/final/sync
rendering, export, restore/export state, reset, `apply_adjustments`, the
four `on_*_changed` debounced paths, slider-release,
`_has_pending_adjustment_changes`, delayed final render, and
`commit_adjustments`), `ProcessingRequest`/`ProcessingQueue`,
`ProcessingWorker` (processor, submit/apply/cache-key/signature, perf
logging), `CombinedAdjustmentCommand`'s synchronous fallback, and a
second "Luminance NR" slider added directly into the existing "Detail"
`CollapsibleSection` in `ToolsPanel`, right after Sharpening, sharing its
existing reset button (now resetting both sliders). Luminance NR is
applied immediately after Sharpening everywhere in the pipeline, as the
new final stage. No new "Detail" section was created, and no unrelated
code was touched; the roadmap coverage table and git history are left for
the calling session.

As with each prior Effects/Detail slice, the same two existing exact-dict
contract tests in `test_image_controller.py`
(`test_get_adjustment_state_returns_normalized_defaults` and
`test_restore_adjustment_state_applies_saved_values`) asserted the
complete `get_adjustment_state()` payload key-for-key and needed a
`"luminance_nr": 0.0` entry added alongside the other now-16 top-level
float keys.

One deviation from a literal reading of the task: `cv2.bilateralFilter`
was explicitly tested against `1x1`/`2x2`/`3x3`/`5x5` float32 inputs
before writing the processor, and it did not crash on any of them (unlike
the speculative "it may reject tiny inputs" framing in the original
task). The defensive bypass (`_MIN_FILTER_DIMENSION = 3`) was still added
as documented insurance rather than a strictly necessary crash fix --
section 5 documents this explicitly so the discrepancy between the
task's expectation and the observed OpenCV behavior is not silently
lost.

Verification: targeted new/changed tests (processor + controller +
command + queue + worker + tools-panel Luminance NR tests, run alongside
the full Sharpening/Grain/Vignette/Dehaze/Clarity/Texture suites they
extend) **257 passed** in the file-scoped run; complete suite **739
passed, 1 deselected in 104.70s** (the pre-existing
`test_geometry_is_restored_on_next_launch` offscreen flake noted in every
prior Phase G note persists and was deselected, not fixed, per the task
instructions). No other test failures or intermittent flakes were
observed during this work. A live GUI smoke test was not performed in
this non-interactive environment.
