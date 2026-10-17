# Remove Chromatic Aberration (Optics) adjustment

Related roadmap: Phase H / PDF section 18. Related workflow: `INCREMENTAL_WORKFLOW.md` sections 4 and 5.1.
Related prior slices: docs/planning/implementation-notes/2026-09-30-texture.md,
docs/planning/implementation-notes/2026-10-12-clarity.md,
docs/planning/implementation-notes/2026-10-12-dehaze.md,
docs/planning/implementation-notes/2026-10-12-vignette.md,
docs/planning/implementation-notes/2026-10-12-grain.md,
docs/planning/implementation-notes/2026-10-12-sharpening.md,
docs/planning/implementation-notes/2026-10-12-luminance-noise-reduction.md,
docs/planning/implementation-notes/2026-10-12-color-noise-reduction.md.

## 1. Problem, goal, and non-goals

Phase G (Effects and Detail) is complete. This slice **starts Phase H**
("Optics", PDF section 18) with its first and only item for this slice:
"Remove Chromatic Aberration" ("Remove CA"), a single zero-by-default
slider in a brand-new "Optics" `ToolsPanel` section, placed after
Detail, mirroring the Sharpening slice's precedent for creating a new
section rather than Color NR's precedent for extending an existing one.

**Non-goals, and why they are real gaps, not just "later":**

- **Defringe (purple/green hue-range sliders).** This is explicitly the
  *next* slice for Phase H, not part of this one. It targets a different
  artifact (purple/green fringing at extreme out-of-focus highlight
  edges) with a different mechanism (hue-range-targeted desaturation,
  not a geometric remap), and deserves its own design pass.
- **"Enable Lens Corrections" (profile-based distortion/vignetting/CA
  correction).** This is **not** a "deferred to next slice" item --
  it is a **durable, structural gap** in this codebase. Lightroom's real
  "Enable Lens Corrections" toggle looks up a per-camera-body/per-lens
  calibration profile (focal length, aperture, and sometimes focus
  distance all matter) from a profile database (Adobe's own lens
  profile library, or a user-supplied one) and applies a *measured*,
  lens-specific distortion/vignetting/CA correction. This codebase has
  **no lens profile database, no profile file format, no camera/lens
  metadata extraction pipeline to look a profile up by, and no UI for
  selecting/managing profiles** -- none of that infrastructure exists
  today, and building it is a multi-slice undertaking in its own right
  (metadata extraction, a profile storage/lookup format, a correction
  model parameterized by the profile, and UI for profile selection and
  manual fine-tuning). Remove CA in this slice is therefore a
  *profile-free, fixed, uniform approximation* -- a real, visible
  simplification relative to Lightroom's actual Optics panel, not a
  stepping stone that trivially becomes "Enable Lens Corrections" later.
  This gap should stay visible in the roadmap (see section 4) until that
  infrastructure is actually built, rather than being implied "done" by
  Remove CA's presence.
- **Distortion/vignetting-by-profile correction.** Also out of scope,
  and for the same reason (no profile database). Separately, Lightroom's
  own geometric *distortion* correction (barrel/pincushion, as opposed to
  CA) is conceptually closer to Phase I ("Geometry", PDF sections 19-20,
  which already covers Upright/distortion/rotate/scale) than to Phase H's
  remaining Defringe work -- so even with a profile system in place,
  that half of "Enable Lens Corrections" would more naturally land in
  Phase I's scope than Phase H's.

## 2. Current behavior

`ToolsPanel`'s sections run Light -> Tone Curve -> Color -> Color Mixer
-> Color Grading -> Effects -> Detail, each built by `_create_section`.
`ImageController` owns normalized state and coordinates preview/final
rendering; `ProcessingRequest` and `ProcessingWorker` carry category
dictionaries; `CombinedAdjustmentCommand` provides the synchronous undo
fallback. Color NR is currently the final pipeline stage, applied right
after Luminance NR, completing Phase G.

## 3. Design and flow

Add a new "Optics" section to `ToolsPanel`, placed immediately after
Detail, starting collapsed (it is not in `_create_section`'s
`expanded = title in {"Light", "Tone Curve", "Color"}` set). It holds a
single `0..100` "Remove CA" slider with its own reset button that resets
only that slider (nothing else lives in Optics yet, pending the
Defringe slice). The section header icon uses `line_icon("transform")`
-- an existing icon (a bounding box with four corner handles) reused
rather than inventing a new one; it reads reasonably as a geometric/
lens-level transform, which is what this section's corrections
conceptually are, and no dedicated "lens"/"optics" icon exists in
`src/views/icons.py`.

Remove CA remains a top-level persisted float for consistency with other
single-slider controls, while processing APIs carry
`{"remove_ca": value}` as a separate category, following Color NR's
wiring pattern exactly (`remove_ca_processor`/`_remove_ca_params`/
`remove_ca_params`, by direct analogy to `color_nr_processor`/
`_color_nr_params`/`color_nr_params`). The controller sends it through
preview, final, synchronous, restore, export, reset, and history paths.
The worker applies it after Color NR and includes it in preview cache
signatures.

**Pipeline position -- a deliberate, flagged compromise.** Remove CA is
applied **last**, after Color NR, everywhere in the pipeline (controller
`get_export_image`/`restore_adjustment_state`/`apply_adjustments` paths,
`ProcessingWorker._apply_adjustments`, `CombinedAdjustmentCommand.
execute`). In a "correct" pipeline, lens-level geometric corrections
(CA, distortion, vignetting-by-profile) conventionally happen **first**,
right after the raw demosaic/white-balance stage and *before* any
creative/tonal work -- because they correct a property of the optical
system, not an artistic choice, and every downstream tonal/creative
adjustment implicitly assumes a geometrically-corrected image. Placing
Remove CA last means it runs on an image that has already had Color
Grading, Texture/Clarity/Dehaze/Vignette/Grain, Sharpening, and both
noise-reduction passes applied to it. See section 5 for the full
rationale on why this physically-last placement was chosen anyway, and
what it would take to fix.

`RemoveChromaticAberrationProcessor` does **not** reuse any existing
processor's math -- it is a **geometric remap**, not a blur/filter, the
first of its kind in this codebase's Effects/Detail/Optics family:

```
k = _MAX_K * (remove_ca / 100.0)          # _MAX_K = 0.0015 (0.15%)

cx, cy = (W - 1) / 2.0, (H - 1) / 2.0
map_x, map_y = meshgrid(arange(W), arange(H))   # identity grid, float32

def remap_channel(channel, scale):
    scaled_x = cx + (map_x - cx) * (1.0 + scale)
    scaled_y = cy + (map_y - cy) * (1.0 + scale)
    return cv2.remap(channel, scaled_x, scaled_y,
                      interpolation=INTER_LINEAR,
                      borderMode=BORDER_REFLECT_101)

new_r = remap_channel(R, +k)   # shrink red toward center
new_b = remap_channel(B, -k)   # expand blue away from center
new_g = G                      # green is the untouched reference channel
```

Green is always passed through completely unmodified -- it is the
reference channel real CA correction is defined relative to. Red and
blue are each independently remapped with a small, fixed, **uniform**
radial scale factor `k` around the image center, built from an identity
pixel-coordinate grid (`map_x[y, x] = x`, `map_y[y, x] = y`) scaled by
`(1.0 + k)` relative to the center before sampling via `cv2.remap`.
`_MAX_K = 0.0015` (0.15% of the center-relative coordinate) was chosen
as small enough to read as a plausible, subtle lens correction rather
than a visible warp, scaled linearly by `value / 100.0`. Zero returns an
identity copy immediately, without building the meshgrid or calling
`cv2.remap` at all -- both for performance and so the zero case is an
*exact* identity test rather than a numerically-near-identity one.

## 4. Contracts and compatibility

- State key: `remove_ca` (short, consistent with `color_nr`/
  `luminance_nr` naming), finite numeric float, default `0.0`.
- UI and processor range: `0..100` (one-directional -- there is no
  "add chromatic aberration" creative use case, matching Grain/
  Sharpening/Luminance NR/Color NR precedent); the processor clamps
  out-of-range callers (including negative values, which clamp to `0`,
  i.e. identity).
- Older payloads that omit the key restore as zero.
- No schema-version bump is needed because this is an additive defaulted
  key.
- `cv2` (already a dependency via Texture/Clarity/Dehaze/Grain/
  Sharpening/Luminance NR/Color NR) is reused for `cv2.remap`; no new
  dependency is added.
- The roadmap coverage table's PDF-18 row was updated from `Gap` to
  `Partial` ("Remove CA implemented; Defringe remains; no lens-profile-
  based corrections (no profile database exists)"), since Remove CA
  alone does not close out Phase H -- Defringe is still missing, and the
  profile-based gap is durable (see section 1).

## 5. Nuances and failure modes

**Why physically-last pipeline placement is a pragmatic, flagged
compromise, not an oversight.** This codebase's processing pipeline is
architected as a fixed, linear sequence of "apply processor N, then
processor N+1" calls repeated identically across five call sites
(`ImageController.get_export_image`, `.restore_adjustment_state`,
`.apply_adjustments` (both the threaded-submit and synchronous-fallback
branches), `ProcessingWorker._apply_adjustments`, and
`CombinedAdjustmentCommand.execute`). Every prior Phase G slice
(Texture, Clarity, Dehaze, Vignette, Grain, Sharpening, Luminance NR,
Color NR) extended this chain by **appending** its processor call after
the current last stage, and every one of those slices' own
implementation notes documents this as the lowest-risk way to add a
step: nothing already relies on where in the middle of the chain a new
stage lands, because it never lands in the middle. Inserting Remove CA
near the *front* of that chain -- which is where a "correct" lens
correction belongs, conventionally right after white balance and before
any creative/tonal work -- would require touching the *order* of calls
at all five of those call sites simultaneously, each of which currently
assumes "white balance, then curve, then color, then HSL, then Color
Grading, then Texture...Color NR" is both the complete list and the
correct order. That is a meaningfully larger, more error-prone change
than one more append, for a codebase with no per-stage pipeline
abstraction to reorder safely (e.g. no declarative stage list that each
call site iterates generically -- each call site spells out the full
chain by hand). Given the explicit instruction to minimize risk of
breaking the existing eight-stage Phase G pipeline, this slice appends
Remove CA at the very end, after Color NR, and documents the resulting
inaccuracy honestly here rather than silently: **a real implementation
would run lens corrections (CA, distortion, vignetting-by-profile) first,
before any creative/tonal adjustment**, so that every downstream stage
operates on a geometrically-corrected image, exactly as a real camera
RAW pipeline does. The practical effect of getting this "wrong" is
small but real: Remove CA's small, fixed radial remap is applied to an
image that has already been resaturated/retoned/sharpened/denoised, so
e.g. Sharpening's edge-enhanced detail at the image periphery gets a
further sub-pixel geometric nudge from the subsequent CA remap, rather
than CA happening once, cleanly, before any of that detail work exists.
Because `_MAX_K` is so small (0.15% maximum), this ordering error is not
expected to be visually significant in practice, but it is a real,
measurable deviation from a textbook-correct pipeline, and a durable
architectural note for whoever eventually gives this pipeline a proper
reorderable-stage abstraction (plausibly alongside the lens-profile
infrastructure from section 1, since that work would need to insert
itself early in the chain too).

**The sign convention (shrink red / expand blue) and how it was
verified.** Lateral CA correction has no "correct" direction to pick
in the abstract -- real CA direction depends on the specific lens, its
focal length, and aperture, none of which this codebase has a profile
for (section 1). The implementation therefore makes an
arbitrary-but-conventional choice: shrink red toward the center
(`k = +_MAX_K`), expand blue away from the center (`k = -_MAX_K`),
leaving green untouched as the reference. This is "arbitrary" in the
sense that swapping the two signs would be an equally defensible
*fictional* correction (there is no real lens being corrected, so
neither direction is more "right"), but "conventional" in that red
fringing on the convex side and blue/cyan fringing on the concave side
of a point source is a commonly cited pattern for lateral CA in
consumer lenses, so this slice's fixed direction at least matches a
plausible real-world CA signature rather than an arbitrary one.

What is *not* arbitrary is which sign of `k` does which: this was
**verified empirically against `cv2.remap` directly**, not assumed from
the formula alone, before being relied on. A single bright pixel was
placed near the edge of a synthetic image (at `x=90` of a `101`-wide
image, center `cx=50`), then remapped with `k=+0.05` and `k=-0.05`:

```
k=+0.05: bright pixel moved from x=90 to x=88  (toward center  -> "shrink")
k=-0.05: bright pixel moved from x=90 to x=92  (away from center -> "expand")
```

This confirms: for output pixel `x` near (but not at) the center, the
source coordinate `cx + (x - cx) * (1 + k)` is *further* from center
than `x` when `k > 0`, so sampling from that further-out source pulls
the original content *inward* in the output (a shrink); the reverse
holds for `k < 0`. This exact check is pinned as
`test_sign_convention_shrinks_red_and_expands_blue` in the processor's
test file, independent of the processor's own behavior, so a future
change to the remap formula that silently flips the sign convention is
caught directly.

**Why a geometric remap, not a filter.** Every other Effects/Detail
processor in this codebase (Texture, Clarity, Dehaze, Vignette, Grain,
Sharpening, Luminance NR, Color NR) is a per-pixel intensity
transformation -- a blur, a blend, a tone curve, additive noise. Remove
CA is fundamentally different: it corrects a *spatial misregistration*
between channels, which can only be expressed as a *geometric*
transformation (resampling one channel's content at different source
coordinates than another's), not an intensity operation. `cv2.remap`
with `cv2.INTER_LINEAR` interpolation and `cv2.BORDER_REFLECT_101`
border handling (matching the border convention already used by this
codebase's Gaussian-blur-based processors) is the natural, idiomatic
OpenCV tool for this: it is explicitly a per-output-pixel
"sample the source at this other coordinate" primitive.

**Determinism.** Like Sharpening, Luminance NR, and Color NR, Remove CA
is a pure, deterministic function of `(image, remove_ca)` --
`cv2.remap` has no RNG involved. `process()` called twice with the same
inputs returns byte-identical output, pinned directly by
`test_is_deterministic_pure_function`.

**Tiny/degenerate images.** `cv2.remap` was verified directly against
`1x1`, `2x2`, and `3x3` float32 inputs (with the same meshgrid/scale
construction the processor uses) before writing this processor, and it
did not crash or raise on any of them -- for a `1x1` input, the single
source pixel is trivially returned regardless of the (degenerate)
scale, since there is only one coordinate to sample from under
`BORDER_REFLECT_101`. No defensive bypass was added, matching Color NR's
precedent (verify first, add no insurance the verification shows is
unnecessary) rather than Luminance NR's precedent (add insurance anyway).
`test_tiny_1x1_image_does_not_crash` and `test_tiny_2x2_image_does_not_
crash` both pin this directly.

**Green channel invariance.** Because green is passed through
completely unmodified (never remapped at all, not even with `k=0`),
`result[..., 1]` is byte-identical to the source's green channel at
every nonzero `remove_ca` value -- `test_green_channel_is_never_
modified` pins this directly across several values rather than only at
one.

**No clipping, dtype/shape preserved.** Like every prior Effects/
Detail/Optics processor, Remove CA does not clip its output, preserving
HDR headroom. Output dtype (`float32`) and shape are retained
unconditionally, pinned by
`test_preserves_dtype_shape_and_headroom_without_clipping`.

**Sub-pixel effect size.** Because `_MAX_K` is tiny (0.15% maximum), the
resulting pixel displacement is well under one pixel for most of a
typical image and only reaches a handful of pixels at the extreme
corners of a very large image. This means a naive "did the brightest
pixel move to a different integer coordinate" test is the wrong metric
at full strength on a modestly-sized synthetic image (it doesn't, since
the shift is sub-pixel) -- the processor test file instead measures a
sub-pixel intensity-weighted centroid over a small window around the
affected point, which is sensitive to exactly this kind of sub-pixel
resampling shift. See `test_positive_value_reduces_r_g_and_b_g_
misalignment` and its `_channel_centroid_x` helper.

## 6. UI/reskin, dependencies, and performance

The view contains only the slider and emits plain data; all math stays
in the processor. Existing throttling, cancellation, interactive
proxies, quality preview, and delayed full-resolution rendering remain
unchanged. The new "Optics" `CollapsibleSection` follows the exact same
construction as "Detail" (`_create_section`, a header reset button via
`_reset_button_for`, a single-slider `_reset_sliders` callback), just
with one slider instead of three, and starts collapsed like Detail did
when it was introduced. No new dependency is added (`cv2` is already a
Texture/Clarity/Dehaze/Grain/Sharpening/Luminance NR/Color NR
dependency; `cv2.remap` is a new *function* from that same dependency,
not a new package). Two `cv2.remap` calls (one per non-green channel) at
full resolution are comparable in cost to a single-channel Gaussian
blur call and were not observed to be a bottleneck in the automated
suite's own synthetic test images (all of which are small); the
early `remove_ca == 0.0` return (skipping the meshgrid construction and
both remap calls entirely) is kept as the no-op fast path, matching
every other Effects/Detail/Optics processor's convention.

**This starts Phase H.** After this slice, Phase H's first item (Remove
CA) is implemented; Defringe (purple/green hue-range sliders) is the
next slice, and profile-based "Enable Lens Corrections" remains a
durable, out-of-scope gap pending lens-profile infrastructure that does
not exist in this codebase today (section 1).

## 7. Test plan and manual smoke

Automated coverage pins identity/copy behavior at zero, green-channel
invariance at several nonzero values, positive Remove CA measurably
reducing R-G and B-G sub-pixel centroid misalignment on a synthetic
image with deliberately pre-misaligned R/G/B bright points (constructed
in exactly the direction the processor corrects, since there is no
"real" misalignment to correct against without a lens profile),
a flat image staying nearly flat, determinism (same image and amount
processed twice is byte-identical, since `cv2.remap` has no RNG),
dtype/shape/headroom preservation without clipping, parameter clamping
in both directions (negative clamps to zero/identity; above 100 clamps
to 100), `1x1`/`2x2` images not crashing, and a dedicated test pinning
the empirically-verified sign convention (`k > 0` shrinks toward center,
`k < 0` expands away from center) directly against `cv2.remap`,
independent of the processor's own behavior. Integration coverage
mirrors Color NR's test structure file-for-file: queue param threading,
worker propagation/skip-at-zero behavior and cache-key sensitivity to
Remove CA params, controller persistence/export/undo, command undo, and
UI range (`0..100`)/emission/restore/reset-only-this-slider, plus a
dedicated test confirming the new "Optics" section exists and starts
collapsed (mirroring the Sharpening slice's equivalent "Detail section
exists and starts collapsed" test, since Optics is a brand-new section
exactly as Detail was). The two existing exact-dict contract tests in
`test_image_controller.py` (`test_get_adjustment_state_returns_
normalized_defaults` and `test_restore_adjustment_state_applies_saved_
values`) were updated with a `"remove_ca": 0.0` entry. Three pre-existing
Detail-section tests (`test_reset_detail_resets_only_sharpening`,
`test_reset_detail_resets_both_sharpening_and_luminance_nr`,
`test_reset_detail_resets_all_three_detail_sliders`) that located
Detail's reset button via `_section_reset_buttons[-1]` were updated to
`[-2]`, since the new Optics section's reset button is now last. Run the
complete suite.

Manual: open an image with visible edge CA fringing; move Remove CA from
0 upward; verify a responsive preview showing a very subtle shift in red/
blue channel registration toward image edges (the effect is deliberately
small/subtle, matching `_MAX_K`), final render on release, undo/redo,
reset (only Remove CA, via "Reset Optics"), image-switch restore, and
export, with the complete Phase G pipeline (Texture through Color NR)
plus Remove CA active together.

## 8. Rollout, rollback, and acceptance

The feature is additive and identity-defaulted. A plain revert removes
it; older builds ignore the extra persisted key. Acceptance requires the
full vertical path, no UI-thread image math, backward-compatible
restore, passing targeted/full tests, clean diff checks, and honest
manual-test reporting.

Plan approved -- implementation allowed: starts Phase H, following the
same scope and wiring-pattern discipline as the approved Phase G
slices (2026-10-12).

## 9. Implementation summary

Implemented `RemoveChromaticAberrationProcessor`
(`src/processors/remove_chromatic_aberration_processor.py`): a
deterministic geometric remap, the first non-filter/non-blur processor
in this codebase's Effects/Detail/Optics family. It builds an identity
pixel-coordinate grid, scales it by a small fixed factor `k` (`_MAX_K =
0.0015` at `value=100`, scaled linearly below that) around the image
center, and resamples the red channel with `k=+_MAX_K` (shrink toward
center) and the blue channel with `k=-_MAX_K` (expand away from center)
via `cv2.remap(..., interpolation=cv2.INTER_LINEAR, borderMode=cv2.
BORDER_REFLECT_101)`, leaving green completely untouched as the
reference channel. One-directional `0..100` range; zero returns an
identity copy without building the meshgrid or calling `cv2.remap` at
all.

Wired it through every integration point Color NR touches:
`ImageController` (defaults, processor/params state, preview/final/sync
rendering, export, restore/export state, reset, `apply_adjustments`, the
four `on_*_changed` debounced paths, slider-release,
`_has_pending_adjustment_changes`, delayed final render, and
`commit_adjustments`), `ProcessingRequest`/`ProcessingQueue`,
`ProcessingWorker` (processor, submit/apply/cache-key/signature, perf
logging), `CombinedAdjustmentCommand`'s synchronous fallback, and a new
"Optics" `CollapsibleSection` (placed after Detail, starting collapsed,
icon `line_icon("transform")`) holding a single "Remove CA" slider
(`min_value=0.0, max_value=100.0`) with its own reset button in
`ToolsPanel`. Remove CA is applied at the very end of the pipeline,
after Color NR -- a deliberate, explicitly-flagged pragmatic compromise
(see section 5) rather than the textbook-correct "lens corrections run
first" placement, chosen to avoid reordering five call sites' existing
eight-stage append chains. No unrelated code was touched.

**Sign convention.** Verified empirically against `cv2.remap` directly
(not assumed from the formula): a positive radial scale `k` pulls
sampled content *inward* toward the image center (a shrink); a negative
`k` pushes it *outward* (an expand). A single bright test pixel at
`x=90` in a `101`-px-wide synthetic image moved to `x=88` under
`k=+0.05` and to `x=92` under `k=-0.05`, confirming the direction before
it was relied on in the processor. The processor therefore uses
`k=+_MAX_K` for red (shrink) and `k=-_MAX_K` for blue (expand) -- an
arbitrary-but-conventional direction choice (there is no real lens to
measure against without profile infrastructure), pinned directly by
`test_sign_convention_shrinks_red_and_expands_blue`.

**Tiny images.** `cv2.remap` was verified directly against `1x1`, `2x2`,
and `3x3` float32 inputs before writing the processor and did not crash
or misbehave on any of them (a `1x1` input trivially returns its single
pixel under `BORDER_REFLECT_101`), so no defensive bypass was added --
matching Color NR's "verify first, add no unneeded insurance" precedent.

**Icon choice.** `line_icon("transform")` (an existing icon: a bounding
box with four corner handles) was reused for the Optics section header,
since no dedicated lens/optics icon exists in `src/views/icons.py` and
a bounding-box-with-handles reads reasonably as a geometric transform,
consistent with what this section's corrections conceptually are.

As with each prior Effects/Detail slice, the two existing exact-dict
contract tests in `test_image_controller.py`
(`test_get_adjustment_state_returns_normalized_defaults` and
`test_restore_adjustment_state_applies_saved_values`) asserted the
complete `get_adjustment_state()` payload key-for-key and needed a
`"remove_ca": 0.0` entry added alongside the other now-18 top-level
float keys. Three pre-existing `ToolsPanel` tests that located Detail's
section-reset button via `_section_reset_buttons[-1]` had to be updated
to `[-2]`, since the newly-added Optics section's reset button is now
the last one in that list -- a direct, expected consequence of inserting
a new section after Detail, not a design flaw.

**Deviation note.** The task's design section speculated that a believable
CA correction needed "direction only matters for a believable
implementation, not for correctness" -- this was taken at face value:
the shrink-red/expand-blue choice is documented as genuinely arbitrary
(no real lens exists to validate against), while the *mechanics* of
which numeric sign produces which effect were still verified empirically
rather than assumed, per the task's explicit instruction to verify
rather than guess.

Verification: targeted new/changed tests (processor + controller +
command + queue + worker + tools-panel Remove CA tests, run alongside
the full Color NR/Luminance NR/Sharpening/Grain/Vignette/Dehaze/Clarity/
Texture suites they extend) **246 passed** in the file-scoped run;
complete suite **785 passed, 1 deselected in 114.90s** (the pre-existing
`test_geometry_is_restored_on_next_launch` offscreen flake noted in
every prior Phase G/H note persists and was deselected, not fixed, per
the task instructions). No other test failures or intermittent flakes
were observed during this work. A live GUI smoke test was not performed
in this non-interactive environment.
