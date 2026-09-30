# 2026-09-30 -- Fix: per-pixel power() on every image decode, replaced with an exact LUT

Related plan: [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) sections 4, 5.1. Bug fix, not a roadmap phase slice -- surfaced while reproducing the user's follow-up report that a load/switch "freeze" happens specifically when clicking during the loading spinner, and that it is intermittent.

## 1. Problem and goal

The user reported a freeze on image load/switch and confirmed the trigger
was clicking during the loading spinner, and that it does not happen
every time. Intermittent, click-during-load behavior is the signature of
the zoom race already fixed in
[2026-09-30-image-load-responsiveness-and-zoom-fixes.md](2026-09-30-image-load-responsiveness-and-zoom-fixes.md).
While building a reproduction for that report (rapid successive
`load_image_async` calls, simulating fast library clicking), a single
6-megapixel JPEG load measured **~3.4 seconds** in profiling -- all of it
in `color_pipeline.srgb_to_linear`, called by `pil_to_linear`, called by
every single non-RAW image load and every embedded-RAW-thumbnail JPEG
decode in the app.

**Goal:** eliminate the per-pixel `power()` pass this function does on
every image load, the same way the codebase already eliminated it for
two other conversions (`ExposureProcessor`'s contrast LUT,
`display_frame.linear_to_display_rgb`'s display LUT) -- by precomputing
an exact lookup table once and indexing into it, rather than recomputing
the transcendental math per pixel per load.

**Honesty about the measured magnitude:** a plain `float32` multiply over
the same 18-million-element array *also* measured ~0.9s in this
environment's own profiling, and fancy-indexing a 256-entry LUT measured
~0.48s -- both far slower than a normal desktop CPU should need for such
basic vectorized numpy work. This points at this specific sandboxed
profiling environment being unusually slow/CPU-constrained (likely
throttled or oversubscribed vCPU), not that 3.4s is what a real user's
machine necessarily experiences. What the profiling *does* prove
reliably is the **relative** cost: `srgb_to_linear`'s `np.power()`-based
path does meaningfully more computational work (two full transcendental
branches evaluated via `np.where`, for every pixel, every load) than a
single LUT lookup does, on any machine. This fix is worth landing
regardless of the exact wall-clock number, both because it shrinks the
window during which the already-fixed click-during-load race could be
hit, and because it removes real, unnecessary per-load work following the
exact precedent this codebase already established twice elsewhere.

## 2. Current behavior

- `color_pipeline.srgb_to_linear(arr)` computes the full piecewise sRGB
  EOTF via `np.power(abs_arr, 2.4)` (and its `low`/`high` companion
  branch) over the entire input array, then selects per-element via
  `np.where`. It is the generic function, correctly used elsewhere for
  arbitrary continuous float input (`CurveProcessor`, `RawService`'s
  uint16 path before this fix) where a small fixed-size LUT cannot losslessly
  represent every possible input value.
- `pil_to_linear` -- the single chokepoint for every non-RAW image load,
  per this module's own docstring -- converts a `uint8` array (each
  channel only ever 0-255, 256 possible values) via
  `arr_u8.astype(np.float32) / 255.0` then `srgb_to_linear(...)`,
  needlessly paying the continuous-domain cost for an input that only
  ever takes 256 discrete values.
- `RawService._uint16_srgb_to_linear` (RAW full-resolution demosaic and
  half-size fallback) and `RawService._decode_thumbnail_object`'s BITMAP
  branch (embedded RAW thumbnail, non-JPEG format) have the exact same
  shape of avoidable cost, for `uint16` (65536 possible values) and
  `uint8` inputs respectively.
- `ExposureProcessor` and `display_frame.linear_to_display_rgb` already
  solved this exact problem for their own call sites with a 65536-entry
  cached LUT each -- an established, working precedent in this codebase
  that was simply never applied to the *decode* path.

## 3. Proposed design

- New `color_pipeline.uint8_srgb_to_linear(arr_u8)` /
  `color_pipeline.uint16_srgb_to_linear(arr_u16)`: each backed by a
  cached, lazily-built LUT (`np.linspace(0, 1, 256 or 65536)` fed through
  the existing, unmodified `srgb_to_linear` **once** to build the table).
  Because the input domain is discrete and small, these tables are
  **exact**, not an approximation the way a display-side (float-to-byte)
  LUT necessarily is -- `np.linspace(0.0, 1.0, 256)[i] == i / 255.0`
  exactly for every integer `i`, so indexing the table by the raw byte
  value reproduces `srgb_to_linear(i / 255.0)` bit-for-bit (up to the
  same float32 rounding the direct call already had).
- `pil_to_linear`: replace the `astype(float32)/255.0` +
  `srgb_to_linear(...)` pair with a single `uint8_srgb_to_linear(arr_u8)`
  call.
- `RawService._uint16_srgb_to_linear`: same swap, `uint16_srgb_to_linear`.
- `RawService._decode_thumbnail_object`'s BITMAP branch: same swap,
  `uint8_srgb_to_linear`.
- `srgb_to_linear` itself is **untouched** -- still the correct, exact
  function for continuous-float callers (`CurveProcessor`, and the LUT
  builders above, which call it exactly once each at cache-build time).

## 4. API and data contracts

- Two new exported functions in `color_pipeline.py`
  (`uint8_srgb_to_linear`, `uint16_srgb_to_linear`), added to `__all__`.
  No existing signature changes.

## 5. Nuances and failure modes

- **Exactness, not approximation.** Unlike `linear_to_display_rgb`
  (necessarily lossy: continuous float input binned into a fixed-size
  table), these LUTs are lossless for their discrete input domains --
  pinned by a test asserting every one of the 256 uint8 LUT entries
  matches the direct formula exactly (and a sampled sweep for the 65536
  uint16 table).
- **Lazy, cached, module-level** -- same pattern as the two existing LUT
  precedents; built once on first use, shared across all subsequent
  calls and threads (numpy arrays are safe to read concurrently once
  built; the build itself races harmlessly onto the same values if two
  threads happen to trigger it simultaneously, same as the existing
  precedents already assume).

## 6. UI and reskin impact

None -- internal conversion-path change only.

## 7. Dependencies

None; reuses the existing `srgb_to_linear` to build the tables.

## 8. Test plan

- `tests/unit/test_utils/test_color_pipeline.py`: every one of the 256
  uint8 LUT entries matches `srgb_to_linear` directly; a sampled sweep
  for the uint16 table; shape/dtype preserved; `pil_to_linear` is
  confirmed (not assumed) to route through `uint8_srgb_to_linear`.
- `tests/unit/test_services/test_raw_service.py`: new BITMAP-thumbnail
  test asserting the uint8 path's output matches `uint8_srgb_to_linear`
  directly; existing `_uint16_srgb_to_linear` test continues to pass
  unchanged (same public behavior, faster internals).
- Full existing suite stays green.

## 9. Rollout and rollback

Purely an internal performance change with byte-identical output;
rollback is a plain revert.

## 10. Acceptance criteria

- `pil_to_linear` and both `RawService` uint8/uint16 conversion sites
  route through the new LUTs.
- LUT output is proven exact against the direct formula, not merely
  visually similar.
- All new/updated tests pass; full existing suite stays green.

Plan approved -- implementation allowed: **Approved via autonomous continuation session (2026-09-30)**, fixing a real per-load inefficiency surfaced while reproducing a user-reported intermittent freeze.

## 11. Implementation summary

Landed exactly as planned: `uint8_srgb_to_linear`/`uint16_srgb_to_linear`
added to `color_pipeline.py`, wired into `pil_to_linear` and both
`RawService` uint8/uint16 conversion sites, `srgb_to_linear` itself
untouched. New tests pin exactness against the direct formula.

Verified: full suite (556 tests) passes, plus the one pre-existing
offscreen-QPA geometry-restore failure already known unrelated. In this
profiling environment specifically, a single 6-megapixel JPEG load
dropped from ~3.4s to ~0.5s -- most of the residual cost in this
sandbox's own slow numpy fancy-indexing and JPEG decode, not this
function; see section 1 for why the absolute numbers should not be read
as a promise about the user's own machine.
