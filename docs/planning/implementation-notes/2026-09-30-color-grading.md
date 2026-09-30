# 2026-09-30 -- Color Grading wheels (Phase F, PDF section 15)

Related plan: [PRODUCT_ROADMAP.md](../PRODUCT_ROADMAP.md) Phase F (second bullet, deferred by
[2026-09-30-hsl-color-mixer.md](2026-09-30-hsl-color-mixer.md) section 1); [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) sections 4, 5.1. Follows the HSL Color Mixer (`e09b022`) and the image-load responsiveness/zoom fixes (`4c4fc79`).

## 1. Problem and goal

PDF section 15 ("Color Grading") is the second and last half of Phase F:
Shadows/Midtones/Highlights color wheels plus Blending and Balance
sliders -- a 3-range tonal color tint, distinct from the HSL Mixer's
8-band *hue-selective* adjustment.

**Goal:** a Color Grading panel -- three tonal ranges (Shadows, Midtones,
Highlights), each with independent Hue/Saturation/Luminance, plus two
global sliders (Blending, Balance), threaded through the same pipeline
every prior category uses, landing after the HSL Mixer (PDF/Lightroom
order: Basic -> Curve -> Color -> Mixer -> **Grading**).

**Non-goals (explicit deferral, matching the HSL Mixer slice's own
precedent of documenting UI simplifications):**

- **A literal 2D color wheel widget.** Real Lightroom's Shadows/Midtones/
  Highlights controls are circular wheels (angle = hue, radius =
  saturation). This slice uses three Hue/Saturation/Luminance sliders per
  range instead -- the same pragmatic choice the HSL Mixer already made
  (tabbed sliders instead of a literal per-hue color band picker). The
  underlying *parameter model* (a hue angle 0-360 and a saturation 0-100
  per range) matches Lightroom's data; only the input widget differs.
  Swapping in a real wheel widget later is confined to the view layer.
- **Lightroom's exact shadow/highlight crossover behavior.** This slice's
  `Balance` and `Blending` are a documented simplification (section 3)
  tuned for a smooth, artifact-free 3-way blend rather than a pixel-exact
  match to Adobe's internal tone-range split.

## 2. Current behavior

- Pipeline order today: exposure -> tonal -> white balance -> curve ->
  color (saturation/vibrance) -> HSL mixer (last). Per PDF/Lightroom
  ordering, Color Grading runs **after** the HSL Mixer.
- `HslMixerProcessor` already establishes two directly reusable
  precedents: (a) linear-light HSV math via `cv2.cvtColor` (no sRGB
  round-trip, unlike `CurveProcessor`), and (b) a raised-cosine window
  function for soft-edged range membership, with a documented, tested
  partition-of-unity property. Color Grading reuses both, but windows
  luminance (HSV `V`) instead of hue, and blends toward a fixed tint
  color instead of rotating existing hue.
- Every prior parameter category is threaded as its own dict through
  `ImageController`/`ProcessingQueue`/`ProcessingWorker`/
  `CombinedAdjustmentCommand`, and nested under one key in
  `get_adjustment_state()`/`restore_adjustment_state()` (`"tone_curve"`,
  `"hsl"`). Color Grading adds a 7th: `"color_grading"`, an 11-key flat
  `Dict[str, float]`.

## 3. Proposed design

- New `src/processors/color_grading_processor.py`
  (`ColorGradingProcessor(BaseProcessor)`):
  - Three tonal ranges, keyed by name: `shadows`, `midtones`,
    `highlights`. Each has `<range>_hue` (0..360), `<range>_sat`
    (0..100), `<range>_lum` (-100..100). Plus two global keys:
    `blending` (0..100, default 50) and `balance` (-100..100, default 0).
    11 keys total; `default_color_grading_params()` mirrors
    `default_hsl_params()`'s shape.
  - **Range membership weighting:** convert to linear-light HSV (as
    `HslMixerProcessor` does), read `V` (0..1) as the luminance measure.
    Range centers: `shadow_center = 0.0`, `highlight_center = 1.0`,
    `midtone_center = 0.5 + (balance / 100.0) * 0.25` (so balance sweeps
    the crossover point between 0.25 and 0.75 -- shifting how much of the
    tonal range midtones vs. shadows/highlights claims, the documented
    simplification of Adobe's own Balance slider). A raised-cosine window
    of full width `W = 0.4 + (blending / 100.0) * 1.2` (so `blending=50`
    gives `W=1.0` -- double the 0.5 default center spacing, the same
    Hann-window 50%-overlap COLA shape the HSL Mixer already uses and
    tests, giving an exact partition of unity at the default balance/
    blending) gives each range's raw weight. Unlike hue (cyclic), `V` is
    a bounded linear domain, so no wraparound handling is needed.
  - **Normalization, always:** raw weights are divided by their sum
    (elementwise, guarded against divide-by-zero) rather than relying on
    the COLA property to hold exactly for every `balance`/`blending`
    combination. At the default `balance=0`/`blending=50` this is a
    no-op (sum is already 1 everywhere by construction, mirroring the
    HSL Mixer's exact property); away from the defaults it keeps the
    3-way blend a valid convex combination instead of over- or
    under-applying color as the window width/centers move.
  - **Tint blend (not hue rotation):** unlike the HSL Mixer, which
    rotates a pixel's *existing* hue, Color Grading blends toward a
    fixed tint color per range -- this is what "grading" means (a
    global tint over a tonal range), and it is also what keeps a
    fully-neutral (gray) pixel colorizable, which a hue-rotation
    approach cannot do (rotating the hue of a zero-saturation pixel is a
    no-op). Per range: a constant tint RGB is computed once per call via
    `cv2.cvtColor` on `HSV(hue, 1.0, 1.0)`. Blend amount per range =
    `normalized_weight * (sat / 100.0) * TINT_STRENGTH` (`TINT_STRENGTH
    = 0.6`, chosen so a fully-weighted, full-saturation range blends
    60% toward the pure hue color -- visibly a tint, not a full color
    replacement). The three per-range amounts are summed (`total_amount`,
    clipped to `[0, 1]`) and their tint colors combined as a weighted
    average, then blended with the pixel's **original, unclipped** RGB:
    `result = original * (1 - total_amount) + combined_tint *
    total_amount`. Using the original (not HSV-round-tripped) RGB as the
    blend base means a pixel with `total_amount == 0` (no range applies
    there, e.g. `blending=0` leaves a gap) passes through byte-for-byte,
    including any linear-light headroom from upstream exposure -- HSV is
    used only to *measure* `V` for weighting, never as the output path.
  - **Luminance offset:** unlike the tint blend, applied as a direct
    additive brightness shift on the already-tint-blended RGB (all three
    channels equally), not another HSV round-trip: `lum_delta =
    sum(normalized_weight_i * (lum_i / 100.0) * LUM_STRENGTH)`
    (`LUM_STRENGTH = 0.25`). Chosen to be additive-in-RGB rather than
    V-in-HSV specifically so it composes with the tint blend above
    without a second clip-for-HSV-validity round-trip.
  - Identity fast path: `all(v == 0 for the 9 hue/sat/lum keys)` skips
    the whole HSV conversion and blend -- `blending`/`balance` are
    irrelevant when every range's saturation and luminance are zero, so
    they are excluded from the identity check (matches how the HSL
    Mixer's per-band early-`continue` skips a band whose 3 params are
    all zero without touching global state).
  - Pipeline order: ... -> color -> hsl mixer -> **color grading**
    (last).
- New `src/views/widgets/color_grading_panel.py`
  (`ColorGradingPanel(QWidget)`): a `QTabWidget` with three tabs
  (Shadows, Midtones, Highlights), each holding 3 `AdjustmentSlider`s
  (Hue 0..360 step 1 decimals 0, Saturation 0..100 step 1 decimals 0,
  Luminance -100..100 step 1 decimals 0) for that range. Below the tabs
  (not inside them -- these are global, not per-range), two more
  `AdjustmentSlider`s: Blending (0..100, default 50) and Balance
  (-100..100, default 0). Emits `values_changed = pyqtSignal(dict)` (the
  full 11-key dict) and `slider_released = pyqtSignal()`, exactly
  mirroring `HslMixerPanel`'s shape. No adjustment math in the widget.
- `ToolsPanel`: new "Color Grading" section (after "Color Mixer",
  matching PDF/Lightroom order), holding one `ColorGradingPanel`.
  `_color_grading_values: Dict[str, float]` (11 keys, default via
  `default_color_grading_params()`), `get_color_grading_params()` getter
  mirroring `get_hsl_params()`. Threaded through
  `set_adjustments()`/`reset_all()`/`set_enabled()`. A new
  `color_grading_changed = pyqtSignal(dict)` output signal (parallel to
  `hsl_changed`/`curve_changed` -- kept out of the main flat
  `adjustments_changed` dict for the same reasoning already documented
  twice).
- `ImageController`: `_color_grading_processor` +
  `_color_grading_params: Dict[str, float]` (defaults via a new
  `_COLOR_GRADING_DEFAULTS` class constant), a new
  `on_color_grading_changed(values)` slot (parallel to `on_hsl_changed`,
  reusing `_normalize_floats` -- already factored out generically enough
  by the HSL Mixer slice to cover an 11-key dict with no further
  extraction needed), threaded through every method that already threads
  `hsl_params` (`apply_adjustments`, `get_export_image`,
  `restore_adjustment_state`, `reset_to_original`,
  `on_adjustments_changed`, `_on_throttled_adjustment`,
  `_on_debounced_adjustment`, `_submit_delayed_final_render`,
  `_has_pending_adjustment_changes`, `commit_adjustments`,
  `get_adjustment_state`/`restore_adjustment_state`).
- `ProcessingQueue.ProcessingRequest`/`create_request` and
  `ProcessingWorker.submit_request`/`submit_preview_request`/
  `submit_final_request`/`_apply_adjustments`/`_cache_key`/
  `_adjustment_signature` gain `color_grading_params: Dict[str, float] =
  {}`, threaded exactly like `hsl_params`.
- `CombinedAdjustmentCommand` gains `color_grading_params` + a
  `ColorGradingProcessor`, applied last (after the HSL mixer).
- `MainWindow._adjustment_values_from_payload`: add one new key,
  `"color_grading"` (nested flat dict, defaulted via
  `default_color_grading_params()` if missing/malformed, tolerant like
  every other restore path).
- `LibraryImagePreviewCacheService.build_cache_key`: no change needed --
  confirmed (not assumed) in the HSL Mixer slice that
  `_format_adjustment_value`'s existing `except (TypeError, ValueError):
  return repr(value)` fallback already handles any dict value safely;
  `"color_grading"` is exactly the same shape as `"hsl"` and hits the
  identical fallback path.

## 4. API and data contracts

- `ImageController.get_adjustment_state()`/`restore_adjustment_state()`:
  one new key, `"color_grading"`, an 11-key flat `Dict[str, float]`.
  Breaking change to the exact-dict-equality tests (updated in this
  slice, same pattern as every prior slice).
- `ToolsPanel`: new `color_grading_changed = pyqtSignal(dict)`; new
  `get_color_grading_params() -> Dict[str, float]` (11 keys).
- `ProcessingRequest`/`ProcessingWorker`/`CombinedAdjustmentCommand`:
  additive `color_grading_params: Dict[str, float] = {}`, default
  behaves as a no-op.
- Persisted JSON: one new key, `color_grading`, additive, no schema
  version bump (same reasoning as every prior slice).

## 5. Nuances and failure modes

- **HSV used only to measure, never to output.** Unlike the HSL Mixer
  (which converts to HSV, edits it, and converts back), Color Grading
  converts to HSV only to read `V` for range-weighting, then blends in
  RGB against the *original* unclipped array. This matters specifically
  so an untouched pixel (outside every range's window, e.g. a gap at
  `blending=0`) is bit-identical to its input, preserving linear-light
  headroom -- a pixel that happens to land in a covered range does lose
  headroom where it blends toward the tint, which is an inherent,
  expected property of blending toward a bounded `[0,1]` tint color, not
  a bug.
- **Divide-by-zero in normalization.** At extreme `blending` (narrow
  windows) with `balance` pushed to an edge, a luminance value can fall
  in a gap covered by no range (`total_weight == 0`). Guarded with
  `np.where(total_weight > 0, ..., 0)` so those pixels get zero
  grading effect rather than a NaN.
- **Balance only moves the midtone center, not the shadow/highlight
  anchors.** Keeping `shadow_center=0`/`highlight_center=1` fixed (only
  `midtone_center` moves) was chosen over moving all three anchors
  because it keeps pure black/white pixels always addressable by the
  Shadows/Highlights wheels regardless of `balance`, at the cost of not
  matching Adobe's internal crossover math exactly (documented
  non-goal, section 1).
- **RGBA passthrough:** alpha untouched, mirrors every other processor's
  `TestRgbaPassthrough` pattern.
- **Identity fast path excludes `blending`/`balance`.** They only affect
  the window shape/position, which has no visible effect when every
  range's saturation and luminance are zero -- checking only the 9
  hue/sat/lum keys (not all 11) is correct, not an oversight; a test
  pins that a non-default `blending`/`balance` with all-zero sat/lum is
  still a no-op.

## 6. UI and reskin impact

- New "Color Grading" section, positioned after "Color Mixer" (PDF/
  Lightroom order: Basic -> Curve -> Color -> Mixer -> Grading).
- New `ColorGradingPanel` widget: a `QTabWidget` (Shadows/Midtones/
  Highlights) with two always-visible sliders (Blending, Balance) below
  it -- the same dark-theme hex palette used everywhere else, no new
  design-token system.

## 7. Dependencies

- Builds on the same pipeline-threading pattern and the HSL Mixer's
  raised-cosine/COLA precedent; no new third-party dependency.
- This is the last slice of Phase F; Phase G (Effects and Detail) is
  next per the roadmap.

## 8. Test plan

- `tests/unit/test_processors/test_color_grading_processor.py` (new):
  identity is a true no-op (both with all-default params and with
  non-default `blending`/`balance` but all-zero sat/lum); range weights
  sum to exactly 1.0 across a dense luminance sweep at default balance/
  blending (pins the COLA property); a pure-black pixel is only
  addressable by the Shadows range and a pure-white pixel only by
  Highlights (range isolation, mirrors `TestBandIsolation`); a
  documented-formula test for the tint blend and luminance offset
  (mirrors `TestDocumentedFormula`); `balance` shifts which range a
  mid-gray pixel responds to; RGBA alpha passthrough; dtype/shape
  preserved.
- `tests/unit/test_views/test_color_grading_panel.py` (new): defaults to
  identity; moving one slider emits the full 11-key dict with only that
  key changed; `slider_released` fires on any slider's release;
  switching tabs preserves values entered on other tabs; `set_values`
  restores state without emitting.
- `tests/unit/test_views/test_tools_panel.py`: extend with
  `TestToolsPanelColorGrading` mirroring `TestToolsPanelHslMixer`.
- `tests/unit/test_controllers/test_image_controller.py`: update the
  exact-dict-equality tests for the new `color_grading` key; add
  `on_color_grading_changed`/`restore_adjustment_state` round-trip
  coverage and that a non-identity grading setting reaches
  `get_export_image()`.
- `tests/unit/test_processing/test_processing_queue.py` /
  `test_processing_worker.py`: extend with `color_grading_params`.
- `tests/unit/test_commands/test_adjustment_commands.py`: extend
  `CombinedAdjustmentCommand` with a `color_grading_params`-only case.
- Full existing suite stays green.

## 9. Rollout and rollback

- Purely additive; default (all zeros + default blending/balance, which
  are themselves inert at zero sat/lum) is a no-op. Rollback is a plain
  revert; extra `color_grading` keys in already-saved catalogs are
  harmless to older code, same precedent as every prior slice.

## 10. Acceptance criteria

- Moving any of the 11 sliders updates the live preview through the same
  throttled/debounced threaded path as every other control, with a
  full-res render + undo entry on release.
- Color Grading state round-trips through `get_adjustment_state()`/
  `restore_adjustment_state()`/persistence.
- Identity grading costs no extra HSV conversion (fast-path test).
- The 3-range weight function's partition-of-unity property at default
  balance/blending is pinned by a test.
- All new/updated tests pass; full existing suite stays green.

Plan approved -- implementation allowed: **Approved via autonomous continuation session (2026-09-30)**, continuing the roadmap slice sequence (completing Phase F).

## 11. Implementation summary

Landed as planned:

- `src/processors/color_grading_processor.py`: 3 tonal ranges (Shadows/
  Midtones/Highlights) weighted by linear-light HSV `V` via a
  raised-cosine window (COLA-exact at default balance=0/blending=50,
  pinned by a test sweeping 500 luminance values); `balance` moves only
  the midtone center (shadows/highlights stay fixed at 0.0/1.0), and
  `blending` reshapes the window width; weights are always normalized by
  their sum so the 3-way blend stays a valid convex combination at any
  balance/blending. Per-range Hue/Saturation define a fixed tint color
  blended into the pixel's *original, unclipped* RGB (not a hue rotation
  like the HSL Mixer) so headroom is preserved wherever no range applies
  and neutral/gray pixels remain colorizable. Luminance is a separate
  additive RGB brightness shift. Identity fast path checks only the 9
  hue/sat/lum keys (blending/balance are inert at all-zero sat/lum).
- `src/views/widgets/color_grading_panel.py`: a `QTabWidget` with
  Shadows/Midtones/Highlights tabs (3 sliders each) plus two
  always-visible Blending/Balance sliders below, emitting the full
  11-key dict via `values_changed`. No adjustment math in the widget.
- New "Color Grading" `ToolsPanel` section (after "Color Mixer", per PDF/
  Lightroom order); `get_color_grading_params()`; a dedicated
  `color_grading_changed` signal, mirroring the HSL Mixer's.
- Color Grading threaded as a 7th parameter category through
  `ImageController` (`on_color_grading_changed`,
  `_COLOR_GRADING_DEFAULTS`, `_normalize_color_grading_state`, reusing
  the existing `_normalize_floats` helper with no changes needed),
  `ProcessingQueue`/`ProcessingWorker` (pipeline order: ... -> hsl mixer
  -> color grading, last), and `CombinedAdjustmentCommand`.
- One nuance not fully anticipated in the plan: `_has_pending_adjustment_changes`
  and `restore_adjustment_state`'s `has_changes` check both needed a
  default-aware comparison (`value != default` per key) rather than the
  simple `any(v != 0 ...)` pattern every other flat-float category uses,
  since `blending` defaults to 50.0, not 0.0. Implemented once and reused
  in both places via `_COLOR_GRADING_DEFAULTS.items()`.
- `MainWindow._adjustment_values_from_payload` gained the new
  `"color_grading"` key from the start (no repeat of the Tone Curve
  slice's original whitelist bug).

Verified: full suite (597 tests, up from 552) passes, including the
partition-of-unity pin, range-isolation tests (pure black/white pixels
only addressable by Shadows/Highlights respectively), the balance-shifts-
midtone-center tests, and exact-formula tests for the luminance offset
and tint-strength blend. Manually smoke-tested the panel in a live
`MainWindow` instance (slider move updates `get_color_grading_params()`
correctly).

This completes Phase F (HSL Color Mixer + Color Grading) per the
roadmap. Per the user's instruction, no further roadmap slices were
started after this one.
