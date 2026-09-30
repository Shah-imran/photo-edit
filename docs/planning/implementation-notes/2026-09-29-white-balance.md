# 2026-09-29 -- White Balance: Temperature/Tint (Phase E, PDF section 13)

Related plan: [PRODUCT_ROADMAP.md](../PRODUCT_ROADMAP.md) Phase E; [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) sections 4, 5.1; follows the Tone Curve slice (`8ebc64d`).

## 1. Problem and goal

PDF section 13 ("Color") groups WB Temperature/Tint, Vibrance, Saturation,
and WB presets. Vibrance/Saturation already exist (`ColorProcessor`). This
slice adds the remaining always-visible controls: **Temperature** and
**Tint** sliders.

**Goal:** Temperature and Tint sliders in the existing "Color" panel
section (above Saturation/Vibrance, matching PDF/Lightroom order), wired
through the same threaded preview/undo/persistence pipeline every other
Basic-panel control already uses.

**Non-goals (explicit deferral):**

- WB presets (As Shot, Auto, Daylight/Cloudy/Shade/Tungsten/Fluorescent,
  Custom) -- these need either EXIF "as-shot" WB metadata or an
  auto-white-balance algorithm, neither of which exists yet; a follow-up
  slice.
- Reading/exposing the camera's as-shot WB coefficients from RAW files
  (`rawpy` already applies camera WB during demosaic -- see
  `src/services/raw_service.py`'s own "custom WB UI ... separate slices"
  note). This slice is a purely editorial, relative adjustment on top of
  whatever WB the source pixels already have, exactly like Highlights/
  Shadows/Whites/Blacks are relative adjustments rather than absolute
  physical ones.
- HSL Mixer / Color Grading (next slices per the roadmap).

## 2. Current behavior

- `ColorProcessor` handles Saturation/Vibrance only (HSV-domain).
- The Basic-panel pipeline order is exposure -> tonal -> curve -> color
  (saturation/vibrance) (see `ImageController.apply_adjustments`,
  `ProcessingWorker._apply_adjustments`, `CombinedAdjustmentCommand`).
- All existing Basic-panel parameters (`exposure`, `contrast`,
  `brightness`, `highlights`, `shadows`, `whites`, `blacks`,
  `saturation`, `vibrance`) are plain floats living together in one flat
  `Dict[str, float]` (`ImageController._ADJUSTMENT_DEFAULTS`,
  `ToolsPanel._adjustments`). The Tone Curve slice had to build a
  *parallel* non-float parameter category specifically because curve
  points are not floats; Temperature/Tint **are** plain floats, so this
  slice reuses the existing flat-dict plumbing directly -- no
  `curve_math.py`-style special-casing needed anywhere in this pipeline.

## 3. Proposed design

- New `src/processors/white_balance_processor.py`
  (`WhiteBalanceProcessor(BaseProcessor)`): `process(image, temperature=0.0,
  tint=0.0)`. Operates in **linear light** (unlike `CurveProcessor`, which
  deliberately works in sRGB-encoded space) because white balance is a
  per-channel multiplicative gain (a diagonal/von Kries transform), and
  that operation is only physically meaningful on linear radiometric
  values -- gamma-encoded channels don't scale proportionally with light
  quantity, matching how `TonalProcessor`'s luminance-masked recovery is
  documented as "linear light or the physics breaks."
  - Both sliders use the existing -100..100 relative range (matching
    Highlights/Shadows/Whites/Blacks/Saturation/Vibrance), **not** an
    absolute Kelvin scale -- there is no reliable "as-shot" baseline
    temperature available for JPEGs, and RAW files already had camera WB
    applied by `rawpy` before this pipeline ever sees them, so an
    absolute-Kelvin slider would have no defined zero point. This mirrors
    the exact same design choice already made for Highlights/Shadows.
  - Formula (documented in the processor and tested exactly, the same way
    `TonalProcessor.test_matches_documented_formula` pins its whites/blacks
    math):
    ```
    t = temperature / 100.0   # -1..1
    n = tint / 100.0          # -1..1
    r_gain = 1.0 + t * TEMP_STRENGTH + n * TINT_STRENGTH * 0.5
    g_gain = 1.0 - n * TINT_STRENGTH
    b_gain = 1.0 - t * TEMP_STRENGTH + n * TINT_STRENGTH * 0.5
    ```
    Temperature rotates R against B (positive = warmer/more orange,
    negative = cooler/more blue) with G untouched. Tint rotates G against
    R+B together (positive = more magenta/less green, negative = more
    green), matching Lightroom's slider directionality. `TEMP_STRENGTH =
    TINT_STRENGTH = 0.35` -- chosen so a full-range slide is clearly
    visible without immediately clipping a channel, same order of
    magnitude as `TonalProcessor._RECOVERY_STRENGTH`.
- Pipeline order: exposure -> tonal -> **white balance** -> curve -> color.
  WB (a linear per-channel gain) runs before the Tone Curve (nonlinear,
  sRGB-domain) and before Saturation/Vibrance (HSV-domain, so it operates
  on the WB-corrected hue, not a stale one).
- `ToolsPanel`: add `_temperature_slider`/`_tint_slider` (range -100..100,
  step 1, decimals 0 -- identical shape to the Saturation/Vibrance
  sliders) to the top of the existing "Color" section, above
  Saturation/Vibrance (PDF/Lightroom order: WB, then Vibrance/Saturation).
  New `get_wb_params()` getter mirroring `get_tonal_params()`/
  `get_color_params()`. `temperature`/`tint` join the existing flat
  `_adjustments` dict and `adjustments_changed` signal payload --
  no new signal needed (unlike the curve, which needed its own).
- `ImageController`: `_wb_processor` + `_wb_params: Dict[str, float]`
  threaded through every method that already threads
  `exposure_params`/`tonal_params`/`color_params`
  (`apply_adjustments`, `get_export_image`, `restore_adjustment_state`,
  `reset_to_original`, `on_adjustments_changed`, `_on_throttled_adjustment`,
  `_on_debounced_adjustment`, `_submit_delayed_final_render`,
  `_has_pending_adjustment_changes`, `commit_adjustments`,
  `get_adjustment_state`/`_normalize_adjustment_state`/
  `_ADJUSTMENT_DEFAULTS`). Because `temperature`/`tint` are plain floats
  added to `_ADJUSTMENT_DEFAULTS`, the existing `any(v != 0 ...)`
  has-changes checks and `float(...)` normalization already cover them
  with no extra branching -- this is the main simplification versus the
  curve slice.
- `ProcessingQueue.ProcessingRequest`/`create_request` and
  `ProcessingWorker.submit_request`/`submit_preview_request`/
  `submit_final_request`/`_apply_adjustments`/`_cache_key`/
  `_adjustment_signature` gain a `wb_params: Dict[str, float] = {}`
  argument, threaded exactly like `tonal_params` was.
- `CombinedAdjustmentCommand` gains `wb_params` + a
  `WhiteBalanceProcessor`, applied in pipeline order.
- `MainWindow._adjustment_values_from_payload`: add `temperature`/`tint`
  to the whitelist **from the start** this time (the Tone Curve slice's
  section 2 bugfix was exactly a whitelist that fell out of sync -- this
  slice does not repeat that mistake).

## 4. API and data contracts

- `ImageController.get_adjustment_state()`/`restore_adjustment_state()`:
  two new float keys, `"temperature"` and `"tint"`, alongside the
  existing nine floats and `"tone_curve"`. Breaking change to the exact
  dict-equality tests in `test_image_controller.py` (updated in this
  slice, same as the Tone Curve slice's contract change).
- `ToolsPanel.get_wb_params() -> Dict[str, float]` returns
  `{"temperature": ..., "tint": ...}`.
- `ProcessingRequest`/`ProcessingWorker`/`CombinedAdjustmentCommand`:
  additive optional `wb_params` parameter, default `{}` behaves as a
  no-op (consistent with `tonal_params`/`color_params`).
- Persisted JSON (`library_catalog.json`): two new keys, additive, no
  schema version bump (same reasoning as the Tone Curve slice's section 4
  -- the catalog's `adjustment_state` dict has never had its own version
  field and already tolerates unknown/missing keys).

## 5. Nuances and failure modes

- **Linear vs. sRGB domain:** unlike the Tone Curve (deliberately applied
  in sRGB-encoded space), WB gain must be applied in linear light or the
  channel scaling is not physically meaningful. `WhiteBalanceProcessor`
  does **not** convert to sRGB at all -- it operates directly on the
  `LinearImage`, like `ExposureProcessor`/`TonalProcessor`.
- **No clipping inside the processor:** matches `BaseProcessor`'s
  documented convention ("out-of-gamut values are allowed to flow
  through; clipping happens at the boundary") -- a strong warm push on an
  already-bright red channel can legitimately exceed 1.0 until final
  encode, same as `ExposureProcessor`.
- **Order relative to Saturation/Vibrance:** WB must run before the
  HSV-domain color step so vibrance/saturation act on the
  white-balance-corrected hue; running it after would let a strong WB
  push fight with a hue-based saturation boost in a visually confusing
  way.
- **RGBA passthrough:** alpha (if present) must be untouched -- mirrors
  the `TestRgbaPassthrough` pattern already used for
  `TonalProcessor`/`CurveProcessor`.
- **Identity fast path:** `temperature == 0.0 and tint == 0.0` skips all
  work, matching every other processor's zero-is-a-no-op convention (this
  one doesn't need `curve_math`'s heavier "is this normalized-tuple the
  identity" check since a plain float equality is enough).

## 6. UI and reskin impact

- Two new sliders in the existing "Color" section using the exact same
  `AdjustmentSlider` widget and dark-theme styling already used
  everywhere else in `ToolsPanel` -- no new widget class needed (unlike
  the Tone Curve, which needed a bespoke `CurveEditor`).

## 7. Dependencies

- Builds on the same pipeline threading pattern as every prior Basic-panel
  slice. No new third-party dependency.
- Independent of HSL Mixer/Color Grading (next slices).

## 8. Test plan

- `tests/unit/test_processors/test_white_balance_processor.py` (new):
  zero-params identity (byte-equal), documented-formula exact match
  (mirrors `TonalProcessor.test_matches_documented_formula`), positive
  temperature increases R/decreases B, positive tint decreases
  G/increases R+B, RGBA alpha passthrough, dtype stays float32, no
  clipping inside the processor (values can exceed `[0, 1]`).
- `tests/unit/test_views/test_tools_panel.py`: extend with a
  `TestToolsPanelWhiteBalance` class mirroring `TestToolsPanelTonalSliders`
  -- defaults to zero, `get_wb_params()` returns only the two WB keys,
  slider moves update `_adjustments`/emit the full dict, `reset_all()`
  resets WB, `set_enabled` disables the WB sliders, WB changes don't
  perturb the other `get_*_params()` getters.
- `tests/unit/test_controllers/test_image_controller.py`: update the two
  exact-dict-equality tests for `temperature`/`tint`; add
  `on_adjustments_changed`/`restore_adjustment_state` coverage for WB,
  and that a non-zero WB reaches `get_export_image()`.
- `tests/unit/test_processing/test_processing_queue.py` /
  `test_processing_worker.py`: extend request creation/cache-key/apply
  tests with `wb_params`.
- `tests/unit/test_commands/test_adjustment_commands.py`: extend
  `CombinedAdjustmentCommand` tests with a `wb_params`-only case.
- Full existing suite stays green.

## 9. Rollout and rollback

- Purely additive; default value (0, 0) is a no-op, so existing images are
  unaffected until a user touches the new sliders.
- Rollback: revert this slice's commit; extra `temperature`/`tint` keys
  left in already-saved catalogs are harmless (old code's whitelist
  simply ignores unknown keys, same as the Tone Curve precedent).

## 10. Acceptance criteria

- Moving Temperature/Tint updates the live preview through the same
  throttled/debounced path as every other Basic slider, and a full-res
  render + undo entry lands on release.
- WB is included in `get_adjustment_state()`/`restore_adjustment_state()`
  and persists across image switches and app restarts.
- Zero-value WB costs no extra processing (fast-path test).
- All new/updated unit tests pass; full existing suite stays green.

Plan approved -- implementation allowed: **Approved via autonomous continuation session (2026-09-29)**, continuing the roadmap slice sequence.

## 11. Implementation summary

Landed:

- `src/processors/white_balance_processor.py`: linear-light per-channel
  gain (Temperature rotates R/B, Tint rotates G against R+B), identity
  fast-path, RGBA passthrough, no internal clipping.
- Two new sliders (Temperature, Tint) at the top of `ToolsPanel`'s
  existing "Color" section, above Saturation/Vibrance; `get_wb_params()`
  getter. Reused the existing flat `_adjustments` dict/`adjustments_changed`
  signal directly -- no new signal needed, unlike the Tone Curve slice.
- Threaded `wb_params` through `ImageController` (including the new
  `_has_pending_adjustment_changes` helper introduced by the Tone Curve
  slice, which already made this a one-line addition),
  `ProcessingQueue`/`ProcessingWorker` (pipeline order: exposure -> tonal
  -> white balance -> curve -> color), and `CombinedAdjustmentCommand`.
- `MainWindow._adjustment_values_from_payload`: added `temperature`/`tint`
  to the whitelist in the same change that introduced them, so this slice
  does not repeat the Tone Curve slice's bugfix mistake.
- Confirmed no change needed in `LibraryImagePreviewCacheService.
  build_cache_key`: its `_format_adjustment_value` fix from the Tone Curve
  slice already handles arbitrary new float keys via the existing
  `float(...)` branch.

Verified: full suite (498 tests, up from 468) passes; the two
`get_adjustment_state()` exact-dict-equality tests were updated for the
contract change (documented in section 4), same pattern as the Tone Curve
slice.

Deferred exactly as planned: WB presets (As Shot/Auto/Daylight/etc.),
reading as-shot RAW WB metadata, HSL Mixer/Color Grading.
