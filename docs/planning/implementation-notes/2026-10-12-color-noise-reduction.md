# Color Noise Reduction adjustment

Related roadmap: Phase G / PDF section 17. Related workflow: `INCREMENTAL_WORKFLOW.md` sections 4 and 5.1.
Related prior slices: docs/planning/implementation-notes/2026-09-30-texture.md,
docs/planning/implementation-notes/2026-10-12-clarity.md,
docs/planning/implementation-notes/2026-10-12-dehaze.md,
docs/planning/implementation-notes/2026-10-12-vignette.md,
docs/planning/implementation-notes/2026-10-12-grain.md,
docs/planning/implementation-notes/2026-10-12-sharpening.md,
docs/planning/implementation-notes/2026-10-12-luminance-noise-reduction.md.

## 1. Problem, goal, and non-goals

Sharpening and Luminance NR shipped the first two of the Detail group's
three items. This slice adds the third and **final** item -- Color Noise
Reduction ("Color NR"), a third zero-by-default slider added into the
*existing* "Detail" `ToolsPanel` section (not a new section), directly
below Luminance NR, sharing the section's existing "Reset Detail" button.
It does not add Lightroom's full Color NR sub-panel (a separate Detail
slider for the chroma smoothing radius) -- only the single "Color NR"
amount slider, matching how every other Phase G control shipped as a
single slider. **This slice completes Phase G of the roadmap in full:**
all eight Effects/Detail items (Texture, Clarity, Dehaze, Vignette, Grain,
Sharpening, Luminance NR, Color NR) are now implemented.

## 2. Current behavior

`ToolsPanel`'s "Detail" section (added by the Sharpening slice, extended
by the Luminance NR slice) holds two sliders, Sharpening and Luminance NR,
sharing one section-level reset button. `ImageController` owns normalized
state and coordinates preview/final rendering; `ProcessingRequest` and
`ProcessingWorker` carry category dictionaries; `CombinedAdjustmentCommand`
provides the synchronous undo fallback. Luminance NR is currently the
final pipeline stage, applied right after Sharpening.

## 3. Design and flow

Add a third slider, "Color NR", to the existing Detail section, directly
below Luminance NR, sharing the section's existing "Reset Detail" button
(now resetting all three sliders). Color NR remains a top-level persisted
float for consistency with other single-slider controls, while processing
APIs carry `{"color_nr": value}` as a separate category, following
Luminance NR's wiring pattern exactly (`color_nr_processor`/
`_color_nr_params`/`color_nr_params`, by direct analogy to
`luminance_nr_processor`/`_luminance_nr_params`/`luminance_nr_params`). The
controller sends it through preview, final, synchronous, restore, export,
reset, and history paths. The worker applies it after Luminance NR and
includes it in preview cache signatures. Pipeline order is now
... Sharpening -> Luminance NR -> Color NR, so Color NR is the new final
stage -- the complete end of the Phase G pipeline.

Luminance NR smooths brightness while preserving color (it broadcasts a
luminance-only delta equally across all three channels). Color NR does
the exact complementary thing: it smooths the **chrominance** (color)
while leaving **luminance/brightness** detail untouched -- the standard
Lightroom division of labor, where Color NR targets color speckle/
blotches (chroma noise) without softening edge detail the way Luminance
NR targets brightness grain.

Unlike Luminance NR's "add a luminance-only delta to every channel"
approximation, `ColorNoiseReductionProcessor` is built on an explicit,
*exactly invertible* luminance/chrominance decomposition, so the math is
exact rather than an approximation layered on top of a delta trick:

```
wr, wg, wb = 0.2126, 0.7152, 0.0722                 # Rec.709 weights

Y  = wr*R + wg*G + wb*B                              # luminance
Cr = R - Y                                           # opponent chroma 1
Cb = B - Y                                           # opponent chroma 2

smoothed_Cr = cv2.GaussianBlur(Cr, sigma=_CHROMA_SIGMA, BORDER_REFLECT_101)
smoothed_Cb = cv2.GaussianBlur(Cb, sigma=_CHROMA_SIGMA, BORDER_REFLECT_101)

t = color_nr / 100.0
Cr_blended = Cr + t * (smoothed_Cr - Cr)
Cb_blended = Cb + t * (smoothed_Cb - Cb)

# Exact algebraic inverse of the decomposition above:
R' = Y + Cr_blended
B' = Y + Cb_blended
G' = Y - (wr*Cr_blended + wb*Cb_blended) / wg        # wg is never 0
```

**Deriving the reconstruction formula.** From `Y = wr*R + wg*G + wb*B`,
`Cr = R - Y`, and `Cb = B - Y`: solving `Cr = R - Y` for `R` gives
`R = Y + Cr`, and solving `Cb = B - Y` for `B` gives `B = Y + Cb`.
Substituting both into the definition of `Y` gives
`Y = wr*(Y + Cr) + wg*G + wb*(Y + Cb)`, i.e.
`Y = wr*Y + wr*Cr + wg*G + wb*Y + wb*Cb`. Collecting and solving for `G`:
`wg*G = Y - wr*Y - wb*Y - wr*Cr - wb*Cb = Y*(1 - wr - wb) - wr*Cr - wb*Cb`.
Since `wr + wg + wb = 1` (the Rec.709 weights sum to 1), `1 - wr - wb = wg`,
so `wg*G = wg*Y - wr*Cr - wb*Cb`, giving
`G = Y - (wr*Cr + wb*Cb) / wg`. This is an *identity* that holds for any
`(Cr, Cb)`, not only the original decomposition's `Cr`/`Cb` -- which is
exactly what makes substituting the *blended* `Cr_blended`/`Cb_blended`
into it a correct reconstruction rather than an approximation.

**This algebra was verified numerically, not just derived on paper**,
before being relied on: a random `(16, 16, 3)` RGB array was decomposed
into `(Y, Cr, Cb)`, then immediately reconstructed with zero smoothing/
blending (`Cr_blended = Cr`, `Cb_blended = Cb`), and the result matched
the original source to within `1.2e-7` (well inside `atol=1e-5`) --
i.e. machine-precision float32 round-off, not an algebra bug. This exact
check is also pinned as its own test,
`test_decompose_reconstruct_round_trips_at_zero_blending`, independent of
the processor's `value == 0.0` short-circuit (see below), so a future
change to the reconstruction formula that breaks the identity is caught
directly rather than only through the zero-is-identity test.

Each chroma channel is smoothed with `cv2.GaussianBlur` -- *not*
`cv2.bilateralFilter`, deliberately, for three reasons documented at the
call site: (1) color blotches/speckle don't need edge-awareness the way
luminance grain does -- a smeared color edge is far less objectionable
than a smeared luminance edge, since human vision is much more sensitive
to luminance detail than chrominance detail (the same perceptual
asymmetry that underlies chroma subsampling in video/image codecs);
(2) Lightroom's own Color NR is itself a fairly aggressive, non-edge-aware
chroma blur; and (3) using a plain Gaussian here keeps this processor
mechanically distinct from Luminance NR's bilateral filter, exercising a
different, simpler code path. `borderType=cv2.BORDER_REFLECT_101` matches
the other Gaussian-based processors in this codebase (Texture, Clarity,
Sharpening).

Color NR is one-directional (`0..100`, Lightroom "Amount" semantics --
there is no "add color noise" direction), like Grain, Sharpening, and
Luminance NR, unlike Texture/Clarity/Dehaze/Vignette's `-100..100`. Zero
returns `source.copy()` immediately, skipping the decompose/blur/
reconstruct round trip entirely -- see section 5 for why this matters.

## 4. Contracts and compatibility

- State key: `color_nr` (short, matching `luminance_nr`'s naming
  convention), finite numeric float, default `0.0`.
- UI and processor range: `0..100` (one-directional, like Grain,
  Sharpening, and Luminance NR); the processor clamps out-of-range callers
  (including negative values, which clamp to `0`, i.e. identity).
- Older payloads that omit the key restore as zero.
- No schema-version bump is needed because this is an additive defaulted
  key.
- `cv2` (already a dependency via Texture/Clarity/Dehaze/Grain/
  Sharpening/Luminance NR) is reused for the Gaussian blur; no new
  dependency is added.

## 5. Nuances and failure modes

**Why a plain Gaussian, and why `sigma=4.0`.** `_CHROMA_SIGMA = 4.0` was
chosen as a fixed, moderate value inside the documented `3.0`-`5.0`
range: large enough to meaningfully average down color-speckle-scale
chroma noise over a several-pixel neighborhood (a single-pixel-scale
chroma speckle sits well inside a `sigma=4` kernel's effective support),
small enough that it does not noticeably bleed color across unrelated,
large-scale color regions of a typical photo (a `sigma=4` Gaussian's
effective radius, roughly `3*sigma ~= 12px`, is still small relative to
most meaningful color regions in a full-resolution photo, though it is
a real, visible softening at `color_nr=100` on a small synthetic test
image -- expected and consistent with Lightroom's own Color NR being a
visibly strong effect at full strength). This is a single, fixed internal
constant (not user-exposed), in the same spirit as Sharpening's
`sigma=1.0` and Luminance NR's `d=9`/`sigmaColor=0.1`/`sigmaSpace=9.0`.

**Why an explicit decomposition instead of Luminance NR's delta trick.**
Luminance NR's "compute a luminance-only delta and broadcast it to all
three channels" approach works because it only ever needs to *shift*
luminance uniformly -- it never needs to independently vary the two
chroma channels. Color NR's job is the opposite: it must smooth `Cr` and
`Cb` *independently* (they are genuinely different signals -- a red/green
imbalance and a blue/yellow imbalance are not the same noise), which has
no equivalent "single delta broadcast" formulation. An explicit forward
decomposition into `(Y, Cr, Cb)`, independent smoothing of the two chroma
channels, and an exact algebraic inverse back to RGB is therefore not
just a design preference but the natural (and simplest) way to express
"smooth chrominance, hold luminance fixed" exactly.

**Determinism.** Like Sharpening and Luminance NR, Color NR is a pure,
deterministic function of `(image, color_nr)` -- `cv2.GaussianBlur` has
no RNG involved. `process()` called twice with the same inputs returns
byte-identical output, pinned directly by
`test_is_deterministic_pure_function`.

**Tiny/degenerate images.** Unlike Luminance NR (which added a defensive
`_MIN_FILTER_DIMENSION` bypass for its bilateral filter despite no
observed crash), this processor includes no such bypass, because
`cv2.GaussianBlur` was verified directly against `1x1`, `2x2`, and `3x3`
float32 inputs before writing this processor and did not crash or raise
on any of them -- it simply returns an array of the same shape (for a
`1x1` input, trivially unchanged, since a Gaussian kernel averaged over a
single pixel returns that pixel). `test_tiny_1x1_image_does_not_crash`
and `test_tiny_2x2_image_does_not_crash` both pin this directly.

**Luminance preservation.** Because `Y` is carried through the
decomposition and reconstruction completely unchanged (only `Cr`/`Cb` are
smoothed/blended), Color NR cannot systematically brighten or darken an
image -- `test_luminance_is_approximately_preserved` pins the mean
luminance of a synthetic chroma-noisy image before and after processing
to within `1e-4`.

**Pipeline position.** Color NR is applied immediately after Luminance NR
everywhere in the pipeline (controller `get_export_image`/
`restore_adjustment_state`/`apply_adjustments` paths,
`ProcessingWorker._apply_adjustments`,
`CombinedAdjustmentCommand.execute`), as the final stage of the complete
Phase G pipeline. This ordering means Color NR sees whatever residual
color noise is present after both sharpening (which can itself introduce
some color fringing at sharp color edges, in principle, though this
codebase's Sharpening operates per-channel without cross-channel coupling
beyond the shared mask) and Luminance NR have already run -- Color NR is
the very last noise-cleanup step before the image is considered final.

**No clipping, dtype/shape preserved.** Like every prior Effects/Detail
processor, Color NR does not clip its output, preserving HDR headroom.
Output dtype (`float32`) and shape are retained unconditionally, pinned by
`test_preserves_dtype_shape_and_headroom_without_clipping`.

## 6. UI/reskin, dependencies, and performance

The view contains only the slider and emits plain data; all math stays in
the processor. Existing throttling, cancellation, interactive proxies,
quality preview, and delayed full-resolution rendering remain unchanged.
No new `CollapsibleSection` is created -- the slider is added directly
into the existing "Detail" section's content layout, right after
Luminance NR, and all three sliders now share the section's single
"Reset Detail" header button. No new dependency is added (`cv2` is
already a Texture/Clarity/Dehaze/Grain/Sharpening/Luminance NR
dependency).

**Performance.** `cv2.GaussianBlur` is separable (two 1-D passes) and
therefore substantially cheaper per pixel than Luminance NR's non-
separable bilateral filter, even running twice (once per chroma channel)
-- but the early `color_nr == 0.0` return (skipping the decomposition,
both blurs, and the reconstruction entirely) is still kept as the
no-op fast path, matching every other Effects/Detail processor's
convention, since the overwhelmingly common default case must never pay
even a cheap blur's cost. This was not observed to be a bottleneck in the
automated suite's own synthetic test images (all of which are small).

**This completes Phase G in full.** After this slice, Phase G's Effects
group (Texture, Clarity, Dehaze, Vignette, Grain) and all three Detail
items (Sharpening, Luminance NR, Color NR) are complete -- there is no
remaining gap in Phase G (PDF sections 16-17).

## 7. Test plan and manual smoke

Automated coverage pins identity/copy behavior at zero, the decomposition/
reconstruction algebra round-tripping to near machine precision at zero
blending (pinned as its own explicit test, independent of the zero-value
short-circuit), positive Color NR measurably reducing chroma (`Cr`/`Cb`)
standard deviation on a synthetic image with deterministic per-pixel
chroma jitter (`np.random.default_rng` with a fixed seed, constructed so
the perturbation is approximately luminance-neutral and therefore
genuinely chroma noise rather than brightness noise), mean luminance being
approximately preserved on that same image (Color NR must not darken/
brighten), a perfectly flat image staying nearly flat (zero chroma to
smooth), determinism (same image and amount processed twice is
byte-identical, since `cv2.GaussianBlur` has no RNG), dtype/shape/headroom
preservation without clipping, parameter clamping in both directions
(negative clamps to zero/identity; above 100 clamps to 100), and
`1x1`/`2x2` images not crashing. Integration coverage mirrors Luminance
NR's test structure file-for-file: queue param threading, worker
propagation/skip-at-zero behavior and cache-key sensitivity to Color NR
params, controller persistence/export/undo, command undo, and UI range
(`0..100`)/emission/restore/membership in the existing Detail section's
shared reset button, plus a dedicated test confirming the reset button now
resets all three Detail sliders (Sharpening, Luminance NR, Color NR)
together. Run the complete suite.

Manual: open a color-noisy image (e.g. a low-light photo with visible
chroma speckle); move Color NR from 0 upward; verify a responsive preview
showing reduced color speckle/blotchiness without a visible brightness
shift or loss of luminance detail/edges, final render on release, undo/
redo, reset (all three Detail sliders together via "Reset Detail", not
the rest of Effects), image-switch restore, and export, with Texture,
Clarity, Dehaze, Vignette, Grain, Sharpening, Luminance NR, and Color NR
active together -- the complete Phase G pipeline.

## 8. Rollout, rollback, and acceptance

The feature is additive and identity-defaulted. A plain revert removes
it; older builds ignore the extra persisted key. Acceptance requires the
full vertical path, no UI-thread image math, backward-compatible restore,
passing targeted/full tests, clean diff checks, and honest manual-test
reporting.

Plan approved -- implementation allowed: mirrors the approved Texture/
Clarity/Dehaze/Vignette/Grain/Sharpening/Luminance NR slices' scope and
wiring pattern (2026-10-12).

## 9. Implementation summary

Implemented `ColorNoiseReductionProcessor` (deterministic, exactly
invertible Rec.709 luminance/chrominance decomposition --
`Y = wr*R + wg*G + wb*B`, `Cr = R - Y`, `Cb = B - Y` -- with each chroma
channel independently smoothed by a fixed `sigma=4.0` `cv2.GaussianBlur`
and blended toward the original by the requested amount, then
reconstructed via the exact algebraic inverse `R = Y + Cr_blended`,
`B = Y + Cb_blended`, `G = Y - (wr*Cr_blended + wb*Cb_blended) / wg`;
one-directional `0..100` range; zero returns an identity copy without
running the decomposition at all) and wired it through every integration
point Luminance NR touches: `ImageController` (defaults, processor/params
state, preview/final/sync rendering, export, restore/export state, reset,
`apply_adjustments`, the four `on_*_changed` debounced paths,
slider-release, `_has_pending_adjustment_changes`, delayed final render,
and `commit_adjustments`), `ProcessingRequest`/`ProcessingQueue`,
`ProcessingWorker` (processor, submit/apply/cache-key/signature, perf
logging), `CombinedAdjustmentCommand`'s synchronous fallback, and a third
"Color NR" slider added directly into the existing "Detail"
`CollapsibleSection` in `ToolsPanel`, right after Luminance NR, sharing its
existing reset button (now resetting all three sliders). Color NR is
applied immediately after Luminance NR everywhere in the pipeline, as the
new final stage. No new "Detail" section was created, and no unrelated
code was touched.

**This slice completes Phase G of the roadmap.** All eight Effects/Detail
items -- Texture, Clarity, Dehaze, Vignette, Grain, Sharpening, Luminance
NR, and Color NR -- are now implemented. The roadmap coverage table (PDF
sections 16 and 17, both previously "Partial"/"Gap") was updated to
"Done" as part of this slice, since this is the phase-completing change.

As with each prior Effects/Detail slice, the same two existing exact-dict
contract tests in `test_image_controller.py`
(`test_get_adjustment_state_returns_normalized_defaults` and
`test_restore_adjustment_state_applies_saved_values`) asserted the
complete `get_adjustment_state()` payload key-for-key and needed a
`"color_nr": 0.0` entry added alongside the other now-17 top-level float
keys.

The reconstruction algebra (`G = Y - (wr*Cr + wb*Cb) / wg`) was verified
numerically before being relied on, per the task's explicit instruction:
a random `(16, 16, 3)` RGB array was decomposed to `(Y, Cr, Cb)` at zero
blending and reconstructed, matching the original source to
`~1.2e-7` -- well inside a `1e-5` tolerance, confirming the algebra (not
just the code) is correct. This check is also pinned as a standalone unit
test (`test_decompose_reconstruct_round_trips_at_zero_blending`), separate
from the processor's `value == 0.0` fast-path identity test, so the two
are checked independently.

One deviation from a literal reading of the task: the task's section 6
speculated that `cv2.GaussianBlur` might need special handling on 1x1
images ("cv2.GaussianBlur handles tiny images fine, no special bypass
needed here -- but verify this directly"). This was verified directly
(`1x1`/`2x2`/`3x3` float32 inputs via `cv2.GaussianBlur(..., (0,0),
sigmaX=4.0, borderType=cv2.BORDER_REFLECT_101)`) before writing the
processor, and, consistent with the task's own expectation, no crash
occurred and no bypass was added -- unlike Luminance NR, which added a
defensive bypass anyway as "cheap insurance" despite not needing one. This
processor omits that extra insurance, since the task's framing for this
slice did not ask for it and the simpler code (no extra branch) is
preferred when nothing requires it.

Verification: targeted new/changed tests (processor + controller + command
+ queue + worker + tools-panel Color NR tests, run alongside the full
Luminance NR/Sharpening/Grain/Vignette/Dehaze/Clarity/Texture suites they
extend) **243 passed** in the file-scoped run; complete suite **762
passed, 1 deselected in 113.34s** (the pre-existing
`test_geometry_is_restored_on_next_launch` offscreen flake noted in every
prior Phase G note persists and was deselected, not fixed, per the task
instructions). No other test failures or intermittent flakes were
observed during this work. A live GUI smoke test was not performed in
this non-interactive environment.
