# Straighten (Geometry) adjustment

Related roadmap: Phase I / PDF sections 19-20. Related workflow:
`INCREMENTAL_WORKFLOW.md` sections 4 and 5.1.
Related prior slices: docs/planning/implementation-notes/2026-10-12-remove-chromatic-aberration.md
(precedent for creating a brand-new `ToolsPanel` section and for using
`cv2` geometric-transform APIs safely),
docs/planning/implementation-notes/2026-10-12-defringe.md (freshest
full wiring-point reference).

## 1. Problem, goal, and non-goals

Phase H ("Optics", PDF section 18) is complete (Remove CA, Defringe).
This slice **starts Phase I** ("Geometry and Crop", PDF sections 19-20)
with the one piece of it that safely fits this codebase's established
single-slider-processor pattern: "Straighten", a small-angle rigid
rotation that corrects a tilted horizon/vertical. It is added as a new
"Geometry" `ToolsPanel` section, placed after Optics, holding a single
`-45..45` degree "Straighten" slider with its own reset button.

**Non-goals, and why they are a real, durable scope boundary -- not
just "later," and explicitly a *larger, separate* undertaking than any
previous Phase G/H "next slice":**

- **The full interactive Crop tool (PDF section 20).** Lightroom's Crop
  tool is not a slider -- it is draggable corner/edge handles on an
  image-canvas overlay, aspect-ratio-constrained dragging, rule-of-
  thirds/grid overlays, rotate-and-flip, and (critically) it **changes
  the output image's pixel dimensions** (cropping literally removes
  pixels). Every processor this codebase has ever added -- Texture,
  Clarity, Dehaze, Vignette, Grain, Sharpening, Luminance NR, Color NR,
  Remove CA, Defringe, and now Straighten -- preserves the exact input
  `(H, W, C)` shape, and this invariant is relied on throughout the
  codebase: preview caching (`ProcessingWorker._result_cache` keys and
  stores images assuming a stable shape per source), undo/redo buffers
  (`ImageStateChangeCommand`/`CombinedAdjustmentCommand` swap whole
  `LinearImage` buffers in and out of `ImageModel.current_image`),
  zoom/display math (`ImageView`'s zoom-to-fit and 100%-view
  calculations are derived from the image's own pixel dimensions), and
  export (`get_export_image` reprocesses the *original* at full
  resolution and expects every processor call in the chain to return
  something comparable). A real Crop tool needs an entirely different
  interaction model -- mouse-driven canvas event handling for dragging
  handles, hit-testing against handle regions, aspect-ratio-constraint
  math, and a decision about how (or whether) a cropped image continues
  to round-trip through this fixed-shape pipeline at all -- none of
  which exists in this codebase today. This is a materially larger,
  architecturally different undertaking than "write a processor and
  thread it through the five existing call sites," and it needs its own
  dedicated design pass with live visual verification (checking that
  drag handles track the mouse correctly, that aspect-ratio locking
  behaves as expected, etc.) that cannot be done safely by blind
  implementation in a non-interactive environment. **This slice does
  not attempt it, does not stub it, and does not lay any Crop-specific
  groundwork beyond the fact that Straighten's own rotation happens to
  be dimension-preserving.**
- **Upright modes (Off/Guided/Auto/Level/Vertical/Full).** Lightroom's
  Upright analyzes the image (vanishing-line/horizon detection or a
  user-guided reference) and computes a corrective perspective
  transform automatically. This requires real computer-vision analysis
  (line/edge detection, a perspective-correction solve) this codebase
  has no infrastructure for, and a UI for picking/previewing the mode.
  Out of scope entirely for this slice.
- **Distortion, Scale, X/Y Offset, Constrain Crop.** Distortion
  correction (barrel/pincushion) is a profile-or-model-based geometric
  warp with the same "no lens profile infrastructure" gap the Remove CA
  note already documented (see that note's section 1) -- still durable,
  still unbuilt. Scale and X/Y Offset are typically paired with Upright/
  Distortion to recompose the frame after those corrections, and
  "Constrain Crop" is explicitly a *crop*-tool feature (it trims the
  rotated/distorted image back down to a rectangle with no empty
  corners) -- meaningless without the Crop tool itself existing. None of
  these four are implemented here.
- **Rotate 90/180 and Flip horizontal/vertical.** These are lossless,
  shape-*changing* (for 90/270) or shape-preserving-but-trivial (for 180
  and flips) discrete transforms, conceptually adjacent to Straighten
  but a distinct control surface (typically toolbar buttons, not a
  slider) in Lightroom's own UI. Not implemented in this slice; left as
  a plausible small future addition that, unlike Crop, *would* fit this
  codebase's existing slider-processor pattern reasonably well (for the
  180/flip cases) or could be handled as a pure view-layer rotation
  without needing a new processor at all (for 90/270, if ever done) --
  but deciding which is a separate design question, not addressed here.

**Summary: after this slice, Phase I has exactly one item done
(Straighten) out of a large PDF section 19-20 scope, and the remaining
items -- Crop tool, Upright, Distortion/Scale/Offset/Constrain-Crop --
are flagged here as a genuinely large, separate future undertaking
requiring its own implementation plan, not a quick next slice the way
e.g. "Defringe" was a quick next slice after Remove CA.**

## 2. Current behavior

`ToolsPanel`'s sections run Light -> Tone Curve -> Color -> Color Mixer
-> Color Grading -> Effects -> Detail -> Optics, each built by
`_create_section`. `ImageController` owns normalized state and
coordinates preview/final rendering; `ProcessingRequest` and
`ProcessingWorker` carry category dictionaries; `CombinedAdjustmentCommand`
provides the synchronous undo fallback. Defringe is currently the final
pipeline stage, applied right after Remove CA, completing Phase H.

## 3. Design and flow

Add a new "Geometry" section to `ToolsPanel`, placed immediately after
Optics, starting collapsed (not in `_create_section`'s
`expanded = title in {"Light", "Tone Curve", "Color"}` set). It holds a
single `-45..45` (degrees) "Straighten" slider with its own reset
button that resets only that slider (nothing else lives in Geometry
yet, pending the much larger future Crop/Upright work flagged in
section 1). The section header icon uses `line_icon("crop")` -- an
existing icon (four corner crop-mark brackets) reused rather than
inventing a new one. This is a deliberate choice despite this slice
*not* implementing the Crop tool: no dedicated "geometry"/"straighten"
icon exists in `src/views/icons.py`, and a crop-mark bracket is the
closest existing visual metaphor for "this section is about the
image's framing/orientation," which is accurate for Straighten and will
remain accurate if/when Crop itself is eventually added to this same
section. `"transform"` (the bounding-box-with-handles icon used for
Optics) was considered and rejected for Geometry specifically because
it is already in use for Optics -- reusing it again for an adjacent
section would make the two section headers visually indistinguishable
at a glance.

`StraightenProcessor` (`src/processors/straighten_processor.py`)
threads through every integration point Defringe threads through, by
direct analogy (`straighten_processor`/`_straighten_params`/
`straighten_params`, mirroring `defringe_processor`/`_defringe_params`/
`defringe_params`). Straighten is applied immediately **after**
Defringe everywhere in the pipeline, making the full, final Phase
G+H+I pipeline order: ... Luminance NR -> Color NR -> Remove CA ->
Defringe -> Straighten. This is simply the next append in the same
fixed five-call-site append chain Remove CA's own note documents at
length in its section 5 -- that rationale is not repeated at length
here, but see this note's own section 5 for the geometry-specific angle
on the same compromise (a "correct" pipeline would run geometric
corrections, including Straighten, very early, not at the very end).

`StraightenProcessor` does **not** reuse any existing processor's
math wholesale -- it is a **rigid rotation about the image center**, a
new kind of geometric transform in this codebase's Effects/Detail/
Optics/Geometry family (Remove CA's geometric remap independently
scales two channels around the center with a *fixed, tiny* factor;
Straighten rotates the *entire* image by a *user-controlled, much
larger* angle):

```
source = np.asarray(image, dtype=np.float32)
value = clip(straighten, -45.0, 45.0)
if value == 0.0:
    return source.copy()

height, width = source.shape[0], source.shape[1]
center = ((width - 1) / 2.0, (height - 1) / 2.0)
rotation_matrix = cv2.getRotationMatrix2D(center, value, 1.0)
result = cv2.warpAffine(
    source, rotation_matrix, (width, height),
    flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101,
)
```

`cv2.warpAffine` is called **once**, directly on the full 3-channel
`float32` array -- verified empirically (see section 5) to handle
multi-channel float32 input correctly in a single call, unlike Remove
CA's `cv2.remap`, which had to be called once per channel because it
needed each of R/B remapped by a *different* scale factor (and G left
untouched). Straighten applies the identical rotation to every channel,
so there is no reason to split channels, and `cv2.warpAffine` doing the
right thing in one call keeps this processor simpler than Remove CA's.
Passing `(width, height)` explicitly as `warpAffine`'s destination size
is what *guarantees* the output shape matches the input shape by
construction -- this is not a property that happens to hold, it is the
reason this specific call signature was chosen.

## 4. Contracts and compatibility

- State key: `straighten`, finite numeric float, default `0.0`.
- UI and processor range: `-45..45` **degrees** -- bidirectional (like
  Texture/Clarity/Dehaze/Vignette's `-100..100`), but note the range is
  genuinely in degrees, not the `-100..100` or `0..100` convention every
  other slider in this codebase uses. This is a deliberate, documented
  break from that convention: a rotation angle has a natural, small,
  physically meaningful unit (degrees) that a `-100..100` abstract scale
  would obscure, and `±45` degrees comfortably covers any plausible
  "the horizon is tilted" correction without needing finer granularity
  at the extremes. The processor clamps out-of-range callers in both
  directions.
- Older payloads that omit the key restore as zero.
- No schema-version bump is needed because this is an additive
  defaulted key.
- `cv2` (already a dependency via Texture/Clarity/Dehaze/Grain/
  Sharpening/Luminance NR/Color NR/Remove CA/Defringe) is reused for
  `cv2.getRotationMatrix2D` and `cv2.warpAffine`; these are new
  *functions* from that same dependency, not a new package.
- The roadmap coverage table's PDF-19-20 row was updated from `Gap` to
  `Partial` ("Straighten (rotation, dimension-preserving) implemented;
  no Upright modes, Distortion/Scale/Offset, or interactive Crop tool
  (needs new canvas-overlay UI infrastructure)"), replacing the
  previous wording that described the entire section as a gap.

## 5. Nuances and failure modes

**The hard invariant this entire slice exists to respect.** Every
processor in this codebase preserves `(H, W, C)` exactly. Straighten is
the first *rotation* in this family, and rotating a rectangular image
by a nonzero angle necessarily exposes empty corners (the rotated
content no longer fills the original rectangle) -- a naive
implementation might be tempted to either (a) grow the output canvas to
fit the fully-rotated content (changing the shape, breaking the
invariant) or (b) leave the newly-exposed corners as black/zero. This
implementation does neither: `cv2.warpAffine`'s `(width, height)`
destination-size argument keeps the output locked to the input's exact
pixel dimensions, and `cv2.BORDER_REFLECT_101` fills the newly-exposed
corners by reflecting the existing image content back into them --
the same border-handling convention this codebase's other
geometric/blur-based processors already use for their own border
pixels (`RemoveChromaticAberrationProcessor`'s `cv2.remap` calls, and
every Gaussian-blur-based processor's implicit border handling). This
is a real, visible simplification relative to a "true" Lightroom
Straighten (which effectively auto-crops away the empty corners, which
is exactly why Lightroom's real Straighten lives *inside* the Crop
tool, not as a free-standing slider) -- the reflected corners are
visibly repeated/mirrored content rather than genuinely absent pixels,
but this trade-off is what makes Straighten implementable *at all*
without first building the Crop tool's output-dimension-changing
machinery (see section 1). This is the one deliberate, flagged
simplification at the heart of this slice's design, not an oversight.

**The sign convention, and how it was verified.** `cv2.getRotationMatrix2D`'s
own documentation states that a positive angle rotates
counter-clockwise, but per this codebase's established "verify, don't
assume" discipline (used for Remove CA's shrink/expand direction and
Defringe's hue-band math), this was checked directly rather than taken
on faith. A single bright marker pixel was placed at `(x=90, y=50)` in a
`101x101` all-dark synthetic image (center at `(50, 50)`, so the marker
sits directly to the image's right at the same height as the center --
the "3 o'clock" position) and rotated:

```
angle=+10.0: marker moved from (90, 50) to (89, 43)  -- y decreased (moved up)
angle=-10.0: marker moved from (90, 50) to (89, 57)  -- y increased (moved down)
```

In image coordinates (origin top-left, `y` increasing downward, as
rendered on screen), a point starting at the "3 o'clock" position that
moves toward smaller `y` (up, toward "12 o'clock") is moving
**counter-clockwise** as a person looking at the screen would describe
it; moving toward larger `y` (down, toward "6 o'clock") is **clockwise**.
This confirms: **positive `straighten` values rotate the image's
content counter-clockwise (as displayed on screen); negative values
rotate it clockwise** -- matching `cv2`'s own documented convention,
but now pinned by direct empirical measurement rather than assumed from
the docs, exactly per this codebase's standing discipline on this
point. `test_positive_angle_rotates_counter_clockwise_on_screen` pins
this directly, independent of the processor's other behavior.

**`cv2.warpAffine` handles 3-channel float32 input in a single call --
verified, not assumed.** Before writing this processor, a direct check
was run: a `(20, 15, 3)` random `float32` array passed through
`cv2.warpAffine` with a real rotation matrix returned a `(20, 15, 3)`
`float32` array with no error and no need to loop over channels. This
is a genuine difference from Remove CA, whose `cv2.remap` calls had to
be split per-channel (not because `cv2.remap` can't take multi-channel
input in general, but because Remove CA's R and B channels needed
*different* scale factors applied to them, which a single `cv2.remap`
call cannot express). Straighten applies the identical transform to
every channel, so a single `cv2.warpAffine` call over the whole
3-channel array is both correct and simpler.

**Tiny/degenerate images.** `cv2.warpAffine` was verified directly
against `1x1` and `2x2` float32 inputs (with the same
`getRotationMatrix2D`/`warpAffine` construction the processor uses)
before writing this processor, and it did not crash or misbehave on
either -- a `1x1` input trivially returns its single pixel (there is
only one coordinate to sample from, regardless of rotation angle), and
a `2x2` input likewise returned its four pixels unchanged (uniform
input, so no visible effect from the degenerate rotation). No
defensive bypass was added, matching Remove CA's/Color NR's/Defringe's
"verify first, add no unneeded insurance" precedent.
`test_tiny_1x1_image_does_not_crash` and
`test_tiny_2x2_image_does_not_crash` pin this directly.

**No clipping for output, dtype/shape preserved.** Like every prior
Effects/Detail/Optics processor, Straighten does not clip its actual
output, preserving HDR headroom.
`test_preserves_headroom_without_clipping` pins this with a large
constant-value source image, sampling well away from any rotated-in
border region to avoid boundary-interpolation ambiguity (a non-constant
image near a reflected border could plausibly blend to a different
value even without any "clipping" taking place; a constant-value
interior region sidesteps that ambiguity entirely).

**Determinism.** `process()` is a pure, deterministic function of
`(image, straighten)` -- no RNG anywhere in the rotation-matrix
construction or `cv2.warpAffine` itself.
`test_is_deterministic_pure_function` pins two calls with the same
inputs as byte-identical.

**Pipeline position -- a deliberate, flagged compromise (same shape as
Remove CA's, with a geometry-specific wrinkle).** Straighten is applied
**last**, after Defringe, everywhere in the pipeline (controller
`get_export_image`/`restore_adjustment_state`/`apply_adjustments`
paths, `ProcessingWorker._apply_adjustments`,
`CombinedAdjustmentCommand.execute`). In a "correct" pipeline, geometric
corrections like Straighten conventionally happen very early -- right
alongside (or even before) Remove CA/Upright/Distortion, and certainly
before any creative/tonal work, color grading, texture/sharpening, or
noise reduction -- because rotating the frame is a property of how the
photo was framed, not an artistic choice, and ideally every downstream
effect (Vignette's radial falloff, Grain's texture, Sharpening's edge
enhancement) would be computed relative to the *already-straightened*
frame. Placing Straighten last means all of those effects are instead
computed relative to the *original, tilted* frame, and then the whole
already-processed result gets rotated afterward. The geometry-specific
wrinkle: this also means Vignette's radial falloff pattern (centered on
the *original* image's center) ends up slightly offset relative to the
*straightened* image's visual center once rotation is applied on top --
a small, usually imperceptible effect at `±45` degrees' worth of
rotation applied to an already-centered vignette, but a real, honest
deviation from "textbook correct" worth naming explicitly. This slice
makes the same choice Remove CA's note already made and documented at
length (its section 5): appending at the end of the fixed five-call-site
chain is the lowest-risk way to add a new stage to a codebase with no
reorderable-stage abstraction, at the cost of this ordering inaccuracy.
A future rewrite that gives this pipeline a proper reorderable-stage
abstraction should move all of Remove CA/Defringe/Straighten (and any
future Upright/Distortion work) to the *front* of the chain together,
not just Straighten alone.

## 6. UI/reskin, dependencies, and performance

The view adds a single `AdjustmentSlider` ("Straighten",
`min_value=-45.0, max_value=45.0, default_value=0.0, step=0.1,
decimals=1`) to a brand-new "Geometry" `CollapsibleSection`, placed
after Optics, with its own "Reset Geometry" header button resetting
just that one slider. `decimals=1` (sub-degree precision) was chosen
over the `decimals=0` most other `0..100`-range sliders in this
codebase use, since a tenth of a degree is a meaningful, usable amount
of precision for straightening a tilted horizon (a whole-degree-only
control would feel coarse for this specific use), while `step=0.1`
matches that same precision for mouse-wheel/arrow-key increments. All
math stays in the processor; existing throttling, cancellation,
interactive proxies, quality preview, and delayed full-resolution
rendering are unchanged. No new dependency is added (`cv2.
getRotationMatrix2D`/`cv2.warpAffine` are new *functions* from the
existing `cv2` dependency). A single `cv2.warpAffine` call over the
full 3-channel array at full resolution is comparable in cost to Remove
CA's two single-channel `cv2.remap` calls (actually somewhat cheaper,
being one call instead of two) and was not observed to be a bottleneck
against this codebase's (small) synthetic test images; the
`straighten == 0.0` early return (skipping the rotation-matrix
construction and `cv2.warpAffine` call entirely) is kept as the no-op
fast path, matching every other processor's convention.

**This starts Phase I.** After this slice, Straighten (a small-angle,
dimension-preserving rotation) is implemented; the full interactive
Crop tool, Upright modes (Auto/Level/Vertical/Full), and Distortion/
Scale/Offset/Constrain-Crop controls remain explicitly out of scope, as
a genuinely large, separate future undertaking (new canvas-overlay
mouse-interaction UI infrastructure this codebase does not have today),
not a quick next slice the way Defringe was for Remove CA -- see
section 1.

## 7. Test plan and manual smoke

Automated coverage pins: identity/copy at zero (exact
`np.array_equal`); **output shape identical to input shape at every
tested angle, including both extremes (`-45`/`+45`)** -- the single most
important invariant in this slice, tested explicitly and prominently
via `test_output_shape_identical_to_input_shape`, parametrized over six
angles; the empirically-verified rotation-direction/sign convention
(a marker pixel at the "3 o'clock" position moves toward "12 o'clock"
under a positive angle and toward "6 o'clock" under the same-magnitude
negative angle, confirming counter-clockwise-for-positive /
clockwise-for-negative as rendered on screen); dtype preservation;
headroom/no-clipping preservation (a large constant-value image stays
at that exact value in its interior, away from any rotated-in border,
avoiding boundary-interpolation ambiguity); parameter clamping in both
directions (`-90` clamps to `-45`; `+90` clamps to `+45`); determinism
(two calls with identical inputs are byte-identical); and `1x1`/`2x2`
images not crashing (matching the empirically-verified tiny-image
behavior from section 5). Integration coverage mirrors Defringe's test
structure file-for-file: a `CombinedAdjustmentCommand` undo test
(`test_straighten_only_and_undo`, which also re-checks the output shape
invariant), queue param threading
(`test_create_request_threads_straighten_params`), worker propagation/
skip-at-zero behavior and cache-key sensitivity to Straighten params
(`TestProcessingWorkerStraighten`), controller persistence/export/undo
(`TestImageControllerStraighten`, which also re-checks the export
image's shape against the original), and UI range (`-45..45`)/
emission/restore, plus a new section-exists-and-starts-collapsed test
(`test_geometry_section_exists_and_starts_collapsed`, mirroring Remove
CA's/Sharpening's equivalent tests for their own new sections) and a
reset-button test confirming "Reset Geometry" resets only Straighten
(`test_reset_geometry_resets_only_straighten`). The two existing
exact-dict contract tests in `test_image_controller.py`
(`test_get_adjustment_state_returns_normalized_defaults` and
`test_restore_adjustment_state_applies_saved_values`) were updated with
a `"straighten": 0.0` entry. Two pre-existing `ToolsPanel` tests that
located Detail's reset button via `_section_reset_buttons[-2]` were
updated to `[-3]`, and one that located Optics' reset button via `[-1]`
was updated to `[-2]`, since the newly-added Geometry section's reset
button is now the last one in that list -- a direct, expected
consequence of inserting a new section after Optics, not a design flaw
(exactly the same kind of renumbering Remove CA's own note documented
when Optics was first inserted after Detail).

Manual: open an image with a visibly tilted horizon; move Straighten in
both directions; verify a responsive preview showing the whole frame
rotating (not just a region), with the previously-tilted horizon
becoming level and the newly-exposed corners filled with reflected
content rather than black; final render on release, undo/redo, reset
(only Straighten, via "Reset Geometry"), image-switch restore, and
export, with the complete Phase G+H+I pipeline (Texture through
Straighten) active together.

## 8. Rollout, rollback, and acceptance

The feature is additive and identity-defaulted. A plain revert removes
it; older builds ignore the extra persisted key. Acceptance requires
the full vertical path, no UI-thread image math, backward-compatible
restore, passing targeted/full tests, clean diff checks, and honest
manual-test reporting.

## 9. Implementation summary

Implemented `StraightenProcessor` (`src/processors/straighten_processor.py`):
a deterministic rigid rotation about the image center, the first
rotation (as opposed to Remove CA's independent per-channel scaling) in
this codebase's Effects/Detail/Optics/Geometry family. It builds a
rotation matrix via `cv2.getRotationMatrix2D(center, value, 1.0)` and
applies it to the whole 3-channel `float32` array in a single
`cv2.warpAffine` call, passing `(width, height)` explicitly as the
destination size (which is what guarantees the output shape matches
the input shape by construction) and `cv2.BORDER_REFLECT_101` to fill
the newly-exposed corners by reflection rather than leaving them black
or growing the canvas. Bidirectional `-45..45` degree range (a genuine
break from this codebase's usual `-100..100`/`0..100` slider
convention, since degrees are the natural unit here); zero returns an
identity copy without building a rotation matrix or calling
`cv2.warpAffine` at all.

Wired it through every integration point Defringe touches:
`ImageController` (defaults, processor/params state, preview/final/sync
rendering, export, restore/export state, reset, `apply_adjustments`,
the four `on_*_changed` debounced paths, slider-release,
`_has_pending_adjustment_changes`, delayed final render, and
`commit_adjustments`), `ProcessingRequest`/`ProcessingQueue`,
`ProcessingWorker` (processor, submit/apply/cache-key/signature, perf
logging), `CombinedAdjustmentCommand`'s synchronous fallback, and a new
"Geometry" `CollapsibleSection` (placed after Optics, starting
collapsed, icon `line_icon("crop")`) holding a single "Straighten"
slider (`min_value=-45.0, max_value=45.0, step=0.1, decimals=1`) with
its own reset button in `ToolsPanel`. Straighten is applied at the very
end of the pipeline, after Defringe -- a deliberate, explicitly-flagged
pragmatic compromise (see section 5) rather than the textbook-correct
"geometric corrections run first" placement, chosen for the same
lowest-risk-append reason Remove CA's own note already established. No
unrelated code was touched.

**Scope boundary (the most important part of this slice).** The full
interactive Crop tool, Upright modes (Auto/Level/Vertical/Full), and
Distortion/Scale/Offset/Constrain-Crop controls are explicitly **not**
implemented and are **not** a quick follow-up slice the way Defringe
was after Remove CA -- they require new interactive canvas-overlay
mouse-interaction UI infrastructure (draggable handles, hit-testing,
aspect-ratio-constrained dragging) and a decision about how an
output-dimension-changing operation fits into a pipeline where every
existing processor preserves `(H, W, C)` exactly. This is flagged as a
genuinely larger, separate future undertaking needing its own
dedicated implementation plan with live visual verification -- see
section 1 for the full reasoning.

**Rotation sign convention.** Verified empirically against
`cv2.getRotationMatrix2D`/`cv2.warpAffine` directly (not assumed from
documentation, per this codebase's standing "verify, don't assume"
discipline): positive `straighten` values rotate the image's content
counter-clockwise as rendered on screen; negative values rotate it
clockwise. A marker pixel at the image's "3 o'clock" position moved
toward "12 o'clock" under `angle=+10` and toward "6 o'clock" under
`angle=-10`, confirming the direction before it was relied on.
`test_positive_angle_rotates_counter_clockwise_on_screen` pins this
directly.

**`cv2.warpAffine` multi-channel handling.** Verified directly that
`cv2.warpAffine` accepts a 3-channel `float32` array in a single call
and returns a correctly-shaped 3-channel result -- no per-channel
looping was needed (unlike Remove CA's `cv2.remap`, which needed
different scale factors per channel and so could not use one call).

**Tiny images.** `cv2.warpAffine` was verified directly against `1x1`
and `2x2` float32 inputs before writing the processor and did not crash
or misbehave on either, so no defensive bypass was added -- matching
Remove CA's/Color NR's/Defringe's "verify first, add no unneeded
insurance" precedent.

As with each prior Effects/Detail/Optics slice, the two existing
exact-dict contract tests in `test_image_controller.py`
(`test_get_adjustment_state_returns_normalized_defaults` and
`test_restore_adjustment_state_applies_saved_values`) needed a
`"straighten": 0.0` entry added alongside the other now-21 top-level
float keys. Two pre-existing `ToolsPanel` tests that located Detail's
reset button via `_section_reset_buttons[-2]` were updated to `[-3]`,
and one that located Optics' reset button via `[-1]` was updated to
`[-2]`, since the newly-added Geometry section's reset button is now
the last one in that list -- a direct, expected consequence of
inserting a new section after Optics, not a design flaw.

**Icon choice.** `line_icon("crop")` (an existing icon: four corner
crop-mark brackets) was reused for the Geometry section header. This
was chosen deliberately even though this slice does not implement the
Crop tool: no dedicated "geometry"/"straighten" icon exists in
`src/views/icons.py`, a crop-mark bracket is the closest existing
visual metaphor for "this section concerns the image's framing/
orientation" (which is accurate for Straighten today and will remain
accurate if Crop itself is ever added to this same section later), and
reusing `"transform"` (already used for Optics) was rejected
specifically to keep the two adjacent section headers visually
distinguishable.

**Deviation note.** None of substance: the task's design spec was
followed as given for the processor math, range/state-key contract, and
wiring pattern. The pipeline-ordering compromise (append at the end,
after Defringe, rather than the textbook-correct "run geometric
corrections first") was called out explicitly as instructed, following
the exact shape of Remove CA's own documented compromise. The icon
choice (`"crop"` over inventing a new icon or reusing `"transform"`)
was a judgment call documented explicitly per the task's own
instruction to document whatever is landed on and why.

Verification: targeted new/changed tests (processor + command +
controller + queue + worker + tools-panel Straighten tests, run
alongside the Defringe/Remove CA/Color NR/Luminance NR/Sharpening/
Grain/Vignette/Dehaze/Clarity/Texture suites they extend) **283 passed**
in the file-scoped run; complete suite **833 passed, 1 deselected in
109.35s** (the pre-existing `test_geometry_is_restored_on_next_launch`
offscreen flake noted in every prior Phase G/H note persists and was
deselected, not fixed, per the task instructions -- note this flake's
name is an unrelated pre-existing coincidence referring to Qt window
geometry/settings persistence, not this slice's "Geometry" section).
No other test failures or intermittent flakes were observed during this
work. A live GUI smoke test was not performed in this non-interactive
environment.
