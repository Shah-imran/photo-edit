# Sharpening adjustment

Related roadmap: Phase G / PDF section 16. Related workflow: `INCREMENTAL_WORKFLOW.md` sections 4 and 5.1.
Related prior slices: docs/planning/implementation-notes/2026-09-30-texture.md,
docs/planning/implementation-notes/2026-10-12-clarity.md,
docs/planning/implementation-notes/2026-10-12-dehaze.md,
docs/planning/implementation-notes/2026-10-12-vignette.md,
docs/planning/implementation-notes/2026-10-12-grain.md.

## 1. Problem, goal, and non-goals

Texture, Clarity, Dehaze, Vignette, and Grain complete the Effects group of
Phase G. This slice starts the Detail group with the first of its three
planned items -- Sharpening -- adding one zero-by-default Sharpening Amount
control in a brand-new "Detail" section (not inside Effects). It does not
add Lightroom's full Sharpening sub-panel (separate Radius/Detail/Masking
sliders) -- only the single "Amount" slider, with a masking-style safeguard
against over-sharpening flat areas baked in as fixed, non-user-adjustable
internal behavior. It also does not add noise reduction (Luminance NR and
Color NR, the other two Detail items) -- those remain for future slices.

## 2. Current behavior

`ToolsPanel` emits flat basic adjustments; `ImageController` owns normalized
state and coordinates preview/final rendering; `ProcessingRequest` and
`ProcessingWorker` carry category dictionaries; `CombinedAdjustmentCommand`
provides the synchronous undo fallback. Grain is currently the final
pipeline stage, applied right after Vignette (which runs right after
Dehaze, which runs right after Clarity, which runs right after Texture,
which runs right after Color Grading).

## 3. Design and flow

Add a new "Detail" section to `ToolsPanel`, placed after the Effects
section, starting collapsed (like Color Mixer/Color Grading -- Detail is
not in `_create_section`'s `expanded = title in {"Light", "Tone Curve",
"Color"}` set). It holds a single 0..100 "Sharpening" slider with its own
reset button that resets only that slider (nothing else lives in Detail
yet). The section header icon uses `line_icon("mask")` -- an existing
icon (a half-filled circle) reused rather than inventing a new one, since
no dedicated "sharpen" icon exists in `src/views/icons.py`.

Sharpening remains a top-level persisted float for consistency with other
single-slider controls, while processing APIs carry `{"sharpening": value}`
as a separate category, following Grain's wiring pattern exactly
(`sharpening_processor`/`_sharpening_params`/`sharpening_params`, by direct
analogy to `grain_processor`/`_grain_params`/`grain_params`). The controller
sends it through preview, final, synchronous, restore, export, reset, and
history paths. The worker applies it after Grain and includes it in preview
cache signatures. Pipeline order is now
... Color Grading -> Texture -> Clarity -> Dehaze -> Vignette -> Grain ->
Sharpening, so Sharpening is the very last stage -- it sharpens the final
toned, vignetted, grain-added image, matching how real-world sharpening is
conventionally the last step before output.

`SharpeningProcessor` computes a Gaussian base at `sigma=1.0` (smaller than
Texture's `sigma=2.0`, since Sharpening targets fine, pixel-level edge
detail rather than Texture's medium-scale detail) and forms the signed
residual `detail = source - blurred`, exactly as Texture does. Unlike
Texture, which is bidirectional, Sharpening only ever *adds* the residual
(Lightroom "Amount" semantics, `0..100`, no "soften" direction) and scales
it by a soft, edge-aware mask derived from the residual's own magnitude:

```
edge_strength = abs(detail)
mask = edge_strength / (edge_strength + _MASK_EPSILON)   # _MASK_EPSILON = 0.02
amount = (sharpening / 100.0) * _MAX_AMOUNT               # _MAX_AMOUNT = 1.25
result = source + amount * detail * mask
```

`mask` is 0 where `edge_strength` is 0 (flat regions) and approaches 1 as
`edge_strength` grows large relative to `_MASK_EPSILON` (real edges), so
flat or already-smooth areas receive little to no added sharpening while
high-contrast edges receive close to the full effect -- a deliberately
simple (3-line), non-"full edge-detector" safeguard against amplifying
sensor noise or banding in skies and shadows, serving the same purpose as
Lightroom's separate Masking slider without exposing it as its own control.
`_MAX_AMOUNT = 1.25` is higher than Texture's `0.75`, since Sharpening is
meant to read as a stronger, more clearly visible effect at its maximum
than Texture's medium-scale enhancement. It operates per channel on
float32 linear-light data and does not clip intermediate values, preserving
HDR headroom. Zero returns immediately, skipping the blur entirely.

## 4. Contracts and compatibility

- State key: `sharpening`, finite numeric float, default `0.0`.
- UI and processor range: `0..100` (one-directional, like Grain, unlike
  Texture/Clarity/Dehaze/Vignette's `-100..100`); the processor clamps
  out-of-range callers (including negative values, which clamp to `0`,
  i.e. identity).
- Older payloads that omit the key restore as zero.
- No schema-version bump is needed because this is an additive defaulted
  key.
- `cv2` (already a dependency via Texture/Clarity/Dehaze/Grain) is reused
  for the Gaussian blur; no new dependency is added.

## 5. Nuances and failure modes

**Determinism.** Unlike Grain, Sharpening is a pure, deterministic function
of `(image, sharpening)` with no RNG involved -- `process()` called twice
with the same inputs returns byte-identical output, which a dedicated test
(`test_is_deterministic_pure_function`) pins directly, matching the
idempotency expectation the preview cache and every other non-Grain
processor in this codebase rely on.

**The masking safeguard is the central design decision of this slice.**
Without it, applying unsharp masking at `sigma=1.0` with a meaningfully
large `_MAX_AMOUNT` would amplify per-pixel sensor noise and quantization
banding in flat skies/shadows just as much as it sharpens real edges --
exactly the failure mode Lightroom's separate Masking slider exists to
prevent. Rather than exposing a second user-facing slider for this (out of
scope -- see section 1's non-goals), the safeguard is derived directly from
the same `detail` residual already being computed for the unsharp step
itself, at zero extra cost: `edge_strength / (edge_strength +
_MASK_EPSILON)` is a soft knee that is exactly `0` when `edge_strength` is
exactly `0` (a perfectly flat/constant image stays *exactly* flat, not just
approximately -- `test_flat_image_stays_nearly_flat` uses a tight
`atol=1e-5` for this reason) and asymptotically approaches `1` as
`edge_strength` grows well beyond `_MASK_EPSILON`. `_MASK_EPSILON = 0.02`
was chosen as a small fraction of the full `[0, 1]` linear-light range --
large enough to meaningfully suppress sub-threshold noise-scale residuals,
small enough that real edges (residuals a significant fraction of the full
range) are barely attenuated. `test_masking_suppresses_flat_regions_
relative_to_edges` pins the core behavioral claim directly: on an image
with both a hard edge and a flat region, the pixel-wise change from
sharpening is much larger near the edge than deep in the flat region.

**Sharpening is the final pipeline stage.** It is applied after Grain
everywhere (controller `get_export_image`/`restore_adjustment_state`/
`apply_adjustments` paths, `ProcessingWorker._apply_adjustments`,
`CombinedAdjustmentCommand.execute`), matching the real-world editing
convention that sharpening is one of the very last steps -- applied to the
final toned, vignetted, and grain-added image, including sharpening the
grain's own fine structure along with genuine image detail. This also
means an image that is pure flat color (e.g. a swatch) picks up no visible
change from Sharpening even at `sharpening=100`, by design (see the masking
discussion above) -- a controller-level test for this slice therefore uses
a synthetic two-color edge image rather than the shared flat-color
`sample_image` fixture (which Grain's equivalent export test could safely
use, since grain always adds noise regardless of image content).

**No clipping, dtype/shape preserved, tiny images.** Like every prior
Effects/Detail processor, Sharpening does not clip its output, preserving
HDR headroom. Output dtype (`float32`) and shape are retained
unconditionally. `cv2.GaussianBlur` already handles a `1x1` image without
special-casing (Texture relies on the same behavior), so no extra
downsample-guard logic (unlike Grain's) is needed here.

## 6. UI/reskin, dependencies, and performance

The view contains only the slider and emits plain data; all math stays in
the processor. Existing throttling, cancellation, interactive proxies,
quality preview, and delayed full-resolution rendering remain unchanged.
The new "Detail" `CollapsibleSection` follows the exact same construction
as "Effects" (`_create_section`, a header reset button via
`_reset_button_for`, a single-slider `_reset_sliders` callback), just with
one slider instead of five, and starts collapsed like Color Mixer/Color
Grading. A single `sigma=1.0` Gaussian blur over the full-resolution image
is comparable in cost to Texture/Clarity's own Gaussian blurs and was not
observed to be a bottleneck in the automated suite. No new dependency is
added. This starts the Detail group of Phase G (Sharpening done; Luminance
NR and Color NR remain for future slices).

## 7. Test plan and manual smoke

Automated coverage pins identity/copy behavior at zero, positive sharpening
increasing local contrast/edge energy on a synthetic step-edge and
checkerboard image, the masking safeguard keeping a flat/constant image
exactly flat (tight tolerance) while discriminating between an edge zone
and a flat zone on the same image, dtype/shape/headroom preservation
without clipping, parameter clamping in both directions (negative clamps to
zero/identity; above 100 clamps to 100), a 1x1 image not crashing, and
determinism (same image and amount processed twice is byte-identical).
Integration coverage mirrors Texture/Clarity/Dehaze/Vignette/Grain's test
structure file-for-file: queue param threading, worker propagation/
skip-at-zero behavior and cache-key sensitivity to sharpening params,
controller persistence/export/undo (using a synthetic edge image rather
than the shared flat `sample_image` fixture -- see section 5), command
undo, UI range (`0..100`)/emission/restore, and a new check that the
"Detail" section exists and starts collapsed. Run the complete suite.

Manual: open a detailed image; move Sharpening from 0 upward; verify a
responsive preview showing crisper fine edges without visibly amplified
noise in flat skies/shadows, final render on release, undo/redo, reset
(only Sharpening, not the rest of Detail/Effects), image-switch restore,
and export, with Texture, Clarity, Dehaze, Vignette, Grain, and Sharpening
active together.

## 8. Rollout, rollback, and acceptance

The feature is additive and identity-defaulted. A plain revert removes it;
older builds ignore the extra persisted key. Acceptance requires the full
vertical path, no UI-thread image math, backward-compatible restore,
passing targeted/full tests, clean diff checks, and honest manual-test
reporting.

Plan approved -- implementation allowed: mirrors the approved Texture/
Clarity/Dehaze/Vignette/Grain slices' scope and wiring pattern (2026-10-12).

## 9. Implementation summary

Implemented `SharpeningProcessor` (deterministic unsharp mask at
`sigma=1.0`, one-directional `0..100` range, a soft edge-aware masking
safeguard derived from the unsharp residual's own magnitude, `_MAX_AMOUNT
= 1.25`) and wired it through every integration point Grain touches:
`ImageController` (defaults, processor/params state, preview/final/sync
rendering, export, restore/export state, reset, `apply_adjustments`, the
four `on_*_changed` debounced paths, slider-release,
`_has_pending_adjustment_changes`, delayed final render, and
`commit_adjustments`), `ProcessingRequest`/`ProcessingQueue`,
`ProcessingWorker` (processor, submit/apply/cache-key/signature, perf
logging), `CombinedAdjustmentCommand`'s synchronous fallback, and a new
"Detail" `CollapsibleSection` (placed after Effects, starting collapsed,
icon `line_icon("mask")`) holding a single "Sharpening" slider
(`min_value=0.0, max_value=100.0`) with its own reset button in
`ToolsPanel`. Sharpening is applied immediately after Grain everywhere in
the pipeline, as the final stage. No unrelated code was touched; the
roadmap coverage table and git history are left for the calling session.

As with each prior Effects/Detail slice, two existing exact-dict contract
tests in `test_image_controller.py`
(`test_get_adjustment_state_returns_normalized_defaults` and
`test_restore_adjustment_state_applies_saved_values`) asserted the complete
`get_adjustment_state()` payload key-for-key and needed a
`"sharpening": 0.0` entry added alongside the other now-15 top-level float
keys.

One deviation from a literal reading of the task: the controller-level
"round trips and reaches export" test could not reuse the shared
flat-color `sample_image` fixture the way Grain's equivalent test does,
because Sharpening's masking safeguard correctly leaves a perfectly flat
image unchanged even at `sharpening=100` -- that is by design, not a bug.
That one test was written against a small synthetic two-color edge image
instead; every other test in this slice mirrors its Grain counterpart's
fixture choices exactly.

Verification: targeted new/changed tests (processor + controller + command
+ queue + worker + tools-panel Sharpening tests, run alongside the full
Grain/Vignette/Dehaze/Clarity/Texture suites they extend) all passed as
part of the complete-suite run below (no separate narrower count was
captured, since the complete suite already completes in under two
minutes); complete suite **718 passed, 1 deselected in 108.50s** (the
pre-existing `test_geometry_is_restored_on_next_launch` offscreen flake
noted in every prior Phase G note persists and was deselected, not fixed,
per the task instructions). A separate, unrelated cross-test flake
(`TestLibraryPanel::test_clear_library`, a background-thumbnail-thread
teardown race) was observed once during this work and reproduced as
passing when re-run in isolation; it is pre-existing and untouched by this
slice. A live GUI smoke test was not performed in this non-interactive
environment.
