# 2026-09-30 -- HSL Color Mixer (Phase F, PDF section 14)

Related plan: [PRODUCT_ROADMAP.md](../PRODUCT_ROADMAP.md) Phase F; [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) sections 4, 5.1. Follows White Balance (`5613858`) and the library-rebuild responsiveness fix (`01c1819`).

## 1. Problem and goal

PDF section 14 ("Color Mixer") is the next unimplemented Develop panel:
per-color-range Hue/Saturation/Luminance adjustment across 8 named color
bands (Red, Orange, Yellow, Green, Aqua, Blue, Purple, Magenta).

**Goal:** a full HSL Mixer -- 8 bands x 3 channels (24 sliders total),
organized as Hue/Saturation/Luminance tabs (matching Lightroom's own
layout), threaded through the same pipeline every prior Basic-panel
control uses.

**Non-goals (explicit deferral, matches Phase F's own two-bullet split in
the roadmap):**

- Color Grading wheels (PDF section 15) -- a separate roadmap bullet,
  next slice.
- Lightroom's exact non-uniform band centers/widths (Lightroom's bands are
  not evenly spaced -- e.g. Yellow/Green covers a wider hue range than
  Orange -- reflecting perceptual color naming). This slice uses 8 evenly
  spaced bands (45 deg apart) with a raised-cosine falloff, which gives a
  mathematically clean partition of unity (weights always sum to exactly
  1, see section 3) at the cost of not matching Lightroom's exact band
  boundaries pixel-for-pixel. Documented as a deliberate simplification;
  tuning centers/widths later is a small, isolated change confined to one
  constant tuple if it proves to matter.

## 2. Current behavior

- `ColorProcessor` already establishes the precedent of doing
  Saturation/Vibrance directly in **linear-light HSV** via
  `cv2.cvtColor(..., COLOR_RGB2HSV)` -- not converting to sRGB first
  (unlike `CurveProcessor`, which deliberately does). This slice follows
  the same precedent for consistency: hue/saturation/luminance math
  happens directly on the linear-light `LinearImage`.
- Pipeline order is exposure -> tonal -> white balance -> curve -> color
  (saturation/vibrance). Per PDF/Lightroom ordering (Basic -> Curve ->
  Color -> **Mixer** -> Grading), the HSL Mixer runs **after** color.
- Every prior parameter category has been threaded as its own dict
  through `ImageController`/`ProcessingQueue`/`ProcessingWorker`/
  `CombinedAdjustmentCommand`. HSL adds a 6th: `hsl_params`, a **flat**
  24-key `Dict[str, float]` (`"red_hue"`, `"red_sat"`, `"red_lum"`,
  `"orange_hue"`, ... `"magenta_lum"`) -- the values are plain floats, so
  (unlike tone-curve points) this reuses the exact float-dict pattern
  `wb_params` already established, just with more keys.
- `get_adjustment_state()`'s top-level contract stays clean: rather than
  flattening 24 new keys into the top-level dict (which would make every
  exact-dict-equality test list 24 more entries), HSL nests under **one**
  new top-level key, `"hsl"`, holding the flat 24-key dict -- the same
  choice already made for `"tone_curve"` (one key, richer value).

## 3. Proposed design

- New `src/processors/hsl_mixer_processor.py`
  (`HslMixerProcessor(BaseProcessor)`):
  - 8 bands at evenly spaced hue centers: Red 0, Orange 45, Yellow 90,
    Green 135, Aqua 180, Blue 225, Purple 270, Magenta 315 (degrees, HSV
    hue).
  - Per-band weight: a raised-cosine (Hann) window, `width=90`, centered
    on the band: `weight = 0.5 * (1 + cos(2*pi*d/width))` for angular
    distance `d < width/2`, else 0. With bands spaced 45 deg apart and a
    90 deg window, adjacent bands' windows overlap by exactly half their
    width -- the classic Hann-window 50%-overlap COLA (constant
    overlap-add) condition, so **the 8 weights sum to exactly 1.0 at
    every hue** with no extra normalization needed.
  - Per pixel: `total_hue_shift = sum(weight_i * (hue_param_i/100) *
    MAX_HUE_SHIFT_DEG)`, `total_sat_factor = sum(weight_i *
    (sat_param_i/100))`, `total_lum_delta = sum(weight_i *
    (lum_param_i/100) * LUM_STRENGTH)`. Applied as: hue += shift (mod
    360), saturation *= (1 + sat_factor) (same `1.0 + value/100` shape
    `ColorProcessor.saturation` already uses, so a fully-weighted +100
    band saturation slider doubles saturation exactly like the global
    Saturation slider does), value += lum_delta (clamped to `[0, 1]` --
    required for a valid HSV round-trip, unlike other processors that
    leave linear-light headroom unclamped).
  - `MAX_HUE_SHIFT_DEG = 40.0`, `LUM_STRENGTH = 0.3` -- chosen so a
    full-range slide is clearly visible without becoming a different tool
    (a huge hue rotation would look like a color-replace effect, not a
    hue nudge).
  - Identity fast path: `all(v == 0 for v in band_params.values())` skips
    the whole HSV round-trip, matching every other processor.
- Pipeline order: exposure -> tonal -> white balance -> curve -> color ->
  **hsl mixer**.
- New `src/views/widgets/hsl_mixer_panel.py` (`HslMixerPanel(QWidget)`): a
  `QTabWidget` with three tabs (Hue, Saturation, Luminance), each holding
  8 `AdjustmentSlider`s (one per band, range -100..100, matching every
  other Basic-panel slider's shape). Emits a single
  `values_changed = pyqtSignal(dict)` (the full 24-key flat dict) and
  `slider_released = pyqtSignal()`, mirroring `AdjustmentSlider`'s own
  `value_changed`/`slider_released` shape so `ToolsPanel` wires it in
  exactly like every other control. No adjustment math in the widget
  (INCREMENTAL_WORKFLOW.md 5.1) -- it only reports raw slider values.
- `ToolsPanel`: new "Color Mixer" section holding one `HslMixerPanel`.
  `_hsl_params: Dict[str, float]` (24 keys, default 0), `get_hsl_params()`
  getter mirroring `get_wb_params()`. Threaded through
  `set_adjustments()`/`reset_all()`/`set_enabled()`. A new
  `hsl_changed = pyqtSignal(dict)` output signal (parallel to
  `curve_changed`, since -- like the curve -- this is not part of the
  main flat `_adjustments` dict/`adjustments_changed` signal: 24 extra
  keys there would bloat every consumer of that signal for no benefit,
  whereas a dedicated signal keeps the existing float-only contract
  untouched, same reasoning as the curve's dedicated signal).
- `ImageController`: `_hsl_processor` + `_hsl_params: Dict[str, float]`
  (defaults to a 24-zero dict via a new `_HSL_DEFAULTS` class constant),
  a new `on_hsl_changed(values)` slot (parallel to `on_curve_changed`,
  reusing the same `ThrottledDebouncer` by adding an `"hsl"` key to the
  dict already passed to `_debouncer.call(...)`), threaded through every
  method that already threads `wb_params`
  (`apply_adjustments`, `get_export_image`, `restore_adjustment_state`,
  `reset_to_original`, `on_adjustments_changed` (must resend current HSL
  state, same reasoning `wb`/`curve` already documented),
  `_on_throttled_adjustment`, `_on_debounced_adjustment`,
  `_submit_delayed_final_render`, `_has_pending_adjustment_changes`,
  `commit_adjustments`, `get_adjustment_state`/`restore_adjustment_state`).
  A small shared helper, `_normalize_floats(raw, defaults)`, is factored
  out of the existing `_normalize_adjustment_state` so the new 24-key
  normalization does not duplicate that float-coercion logic.
- `ProcessingQueue.ProcessingRequest`/`create_request` and
  `ProcessingWorker.submit_request`/`submit_preview_request`/
  `submit_final_request`/`_apply_adjustments`/`_cache_key`/
  `_adjustment_signature` gain `hsl_params: Dict[str, float] = {}`,
  threaded exactly like `wb_params`.
- `CombinedAdjustmentCommand` gains `hsl_params` + an `HslMixerProcessor`,
  applied last (after color).
- `MainWindow._adjustment_values_from_payload`: add one new key, `"hsl"`
  (a nested flat dict, defaulted via the same 24-zero shape if missing or
  malformed -- tolerant, like every other restore path).
- `LibraryImagePreviewCacheService.build_cache_key`: no change needed --
  its `_format_adjustment_value` already special-cases any
  list/tuple/dict... actually it currently only special-cases
  list/tuple (for `tone_curve`); a nested dict value (`"hsl"`) needs the
  same treatment. Extend `_format_adjustment_value` to also handle a
  `dict` value (format via `repr` of its sorted items), so the "hsl" key
  does not hit the `float(...)` branch and raise.

## 4. API and data contracts

- `ImageController.get_adjustment_state()`/`restore_adjustment_state()`:
  one new key, `"hsl"`, holding a flat 24-key `Dict[str, float]`.
  Breaking change to the exact-dict-equality tests (updated in this
  slice, same pattern as the two prior slices).
- `ToolsPanel`: new `hsl_changed = pyqtSignal(dict)`; new
  `get_hsl_params() -> Dict[str, float]` (24 keys).
- `ProcessingRequest`/`ProcessingWorker`/`CombinedAdjustmentCommand`:
  additive `hsl_params: Dict[str, float] = {}`, default behaves as a
  no-op.
- Persisted JSON: one new key, `hsl`, additive, no schema version bump
  (same reasoning as the two prior slices).

## 5. Nuances and failure modes

- **Valid HSV round-trip:** unlike most processors, `HslMixerProcessor`
  must clamp `V` (and keep `S` clamped, as `ColorProcessor` already does)
  to `[0, 1]` before converting back from HSV to RGB -- an out-of-range
  `V` is not a "headroom" concept in HSV the way linear-light overshoot
  is; it is simply invalid input to the inverse conversion.
- **Partition of unity relies on exact band spacing/width.** If the band
  centers or window width are ever tuned away from "spacing == width/2",
  the COLA property (weights summing to 1) no longer holds automatically;
  a test pins this property explicitly so a future tuning change gets a
  loud, explicit failure instead of a silent brightness/saturation drift.
- **Hue wraparound:** the angular-distance helper must use the standard
  `((a - b + 180) % 360) - 180` signed-wrap trick; a naive `abs(a - b)`
  would break for the Red band (center 0), which is adjacent to Magenta
  (315) across the 360/0 boundary.
- **RGBA passthrough:** alpha untouched, mirrors every other processor's
  `TestRgbaPassthrough` pattern.
- **Identity fast path cost:** with 24 parameters, checking `all(v == 0
  ...)` before doing any HSV conversion matters more here than for
  2-parameter WB -- the HSV round-trip itself is not free, so an
  untouched mixer must cost nothing extra.

## 6. UI and reskin impact

- New "Color Mixer" section, positioned after "Color" (PDF/Lightroom
  order: Basic -> Curve -> Color -> Mixer -> Grading).
- New `HslMixerPanel` widget with a `QTabWidget` (Hue/Saturation/
  Luminance) -- the first tabbed control in this panel; follows the same
  dark-theme hex palette used everywhere else (no new design-token system,
  consistent with every prior slice's UI section).

## 7. Dependencies

- Builds on the same pipeline-threading pattern as every prior slice; no
  new third-party dependency (pure numpy + existing `cv2` HSV conversion,
  already a dependency via `ColorProcessor`).
- Independent of Color Grading (next slice).

## 8. Test plan

- `tests/unit/test_processors/test_hsl_mixer_processor.py` (new):
  identity is a true no-op; the 8-band weight function sums to exactly
  1.0 across a dense hue sweep (pins the COLA property from section 5);
  a Red-band hue shift rotates a pure-red pixel's hue and leaves a
  pure-green pixel unchanged (bands don't bleed into unrelated hues at
  full weight-1 distance); a Red-band saturation/luminance change matches
  the documented formula exactly (mirrors
  `TonalProcessor.test_matches_documented_formula`); RGBA alpha
  passthrough; dtype stays float32.
- `tests/unit/test_views/test_hsl_mixer_panel.py` (new): defaults to
  identity; moving one band's slider emits the full 24-key dict with only
  that key changed; `slider_released` fires on any band's release;
  switching tabs preserves values entered on other tabs; `set_values`
  restores state without emitting.
- `tests/unit/test_views/test_tools_panel.py`: extend with
  `TestToolsPanelHslMixer` mirroring `TestToolsPanelWhiteBalance` --
  `get_hsl_params()` identity default, `hsl_changed` emission, reset,
  enable/disable, non-interference with other `get_*_params()` getters.
- `tests/unit/test_controllers/test_image_controller.py`: update the two
  exact-dict-equality tests for the new `hsl` key; add
  `on_hsl_changed`/`restore_adjustment_state` round-trip coverage and
  that a non-identity mixer setting reaches `get_export_image()`.
- `tests/unit/test_processing/test_processing_queue.py` /
  `test_processing_worker.py`: extend with `hsl_params`.
- `tests/unit/test_commands/test_adjustment_commands.py`: extend
  `CombinedAdjustmentCommand` with an `hsl_params`-only case.
- `tests/unit/test_services/test_library_image_preview_cache_service.py`:
  extend `_format_adjustment_value` coverage for a dict-valued key.
- Full existing suite stays green.

## 9. Rollout and rollback

- Purely additive; default (all zeros) is a no-op. Rollback is a plain
  revert; extra `hsl` keys in already-saved catalogs are harmless to
  older code (ignored by its whitelist), same precedent as prior slices.

## 10. Acceptance criteria

- Moving any of the 24 sliders updates the live preview through the same
  throttled/debounced threaded path as every other control, with a
  full-res render + undo entry on release.
- HSL state round-trips through `get_adjustment_state()`/
  `restore_adjustment_state()`/persistence.
- Identity mixer costs no extra HSV conversion (fast-path test).
- The 8-band weight function's partition-of-unity property is pinned by
  a test.
- All new/updated tests pass; full existing suite stays green.

Plan approved -- implementation allowed: **Approved via autonomous continuation session (2026-09-30)**, continuing the roadmap slice sequence.

## 11. Implementation summary

Landed:

- `src/processors/hsl_mixer_processor.py`: 8 evenly spaced hue bands with
  a raised-cosine (Hann) falloff whose width exactly doubles the band
  spacing, giving weights that sum to exactly 1.0 at every hue (verified
  by a dedicated test sweeping 500 hues). Linear-light HSV math via
  `cv2`, matching `ColorProcessor`'s existing precedent rather than
  `CurveProcessor`'s sRGB one. Identity fast path, RGBA passthrough.
- `src/views/widgets/hsl_mixer_panel.py`: a `QTabWidget` with Hue/
  Saturation/Luminance tabs, 8 `AdjustmentSlider`s each, emitting the
  full 24-key dict via `values_changed`. No adjustment math in the
  widget -- band names/order come from the processor module.
- New "Color Mixer" `ToolsPanel` section (after "Color", matching PDF/
  Lightroom order); `get_hsl_params()`; a dedicated `hsl_changed` signal
  (kept out of the main flat `adjustments_changed` dict, same reasoning
  as the tone curve's dedicated signal).
- HSL threaded as a 6th parameter category through `ImageController`
  (`on_hsl_changed`, `_HSL_DEFAULTS`, `_normalize_hsl_state`),
  `ProcessingQueue`/`ProcessingWorker` (pipeline order: ... -> color ->
  hsl mixer, last), and `CombinedAdjustmentCommand`.
- Factored `_normalize_adjustment_state`'s float-coercion logic into a
  shared `_normalize_floats(values, defaults)` static helper, reused for
  the new 24-key HSL normalization, per the plan.
- `MainWindow._adjustment_values_from_payload` and `get_adjustment_state`
  both gained the new `"hsl"` key from the start (no repeat of the Tone
  Curve slice's whitelist bug).
- Confirmed no change was needed in `LibraryImagePreviewCacheService.
  _format_adjustment_value`: its existing `except (TypeError, ValueError):
  return repr(value)` fallback already handles a dict value safely and
  deterministically (a dict doesn't support `float()`, so it falls
  straight through to `repr()`), verified directly rather than adding a
  redundant explicit branch the plan had assumed would be needed.
- **Bug found and fixed while writing tests, not part of the original
  plan:** the new shared `_normalize_floats` helper assumed its `values`
  argument was always dict-like (calling `.get()` on it unconditionally).
  Every existing caller always passed a real dict or `None`, so this was
  never exercised -- but `restore_adjustment_state`'s `adjustments.get
  ("hsl")` can return *anything* a malformed/hand-edited catalog file
  contains (a string, a list, ...), and passing a non-dict truthy value
  crashed with `AttributeError: 'str' object has no attribute 'get'`
  instead of degrading to the identity default like every other
  malformed-input path in this codebase. Fixed with an
  `isinstance(values, dict)` guard, caught only because the regression
  test actually exercised a malformed "hsl" payload rather than only
  well-formed ones.

Verified: full suite (542 tests, up from 503) passes, including the
COLA/partition-of-unity pin, band-isolation tests (a Red-band hue shift
does not bleed into a Green pixel), and exact-formula tests for
saturation/luminance mirroring the existing `TonalProcessor` precedent.

Deferred exactly as planned: Color Grading wheels, Lightroom's exact
non-uniform band centers/widths.
