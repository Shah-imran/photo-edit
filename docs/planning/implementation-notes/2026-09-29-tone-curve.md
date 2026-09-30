# 2026-09-29 -- Tone Curve (Phase E, PDF section 12)

Related plan: [PRODUCT_ROADMAP.md](../PRODUCT_ROADMAP.md) Phase E; [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) sections 4, 5.1; follows the Highlights/Shadows/Whites/Blacks slice (`123ae84`, `d94567d`, `8cb2575`, `f365b75`).

## 1. Problem and goal

The Basic panel (Exposure/Contrast/Highlights/Shadows/Whites/Blacks/Saturation/
Vibrance) is now complete. The next PDF-ordered gap (section 12) is the **Tone
Curve**: an interactive point curve with a histogram backdrop that remaps
tones after the Basic adjustments and before Color.

**Goal (this slice):** a single master RGB point curve -- add/drag/delete
control points on a curve widget with a histogram backdrop, wired end-to-end
through the same threaded preview/undo/persistence pipeline the Basic panel
uses.

**Non-goals (explicit deferral, future slices per the roadmap):**

- Per-channel R/G/B curves (PDF section 12 also lists these; tracked as a
  follow-up slice once the master curve's plumbing is proven).
- White Balance temperature/tint (PDF section 13; next slice per the roadmap).
- Curve presets (linear/medium/strong contrast one-click curves).
- Live histogram updates on every drag frame (see section 5 -- histogram is
  refreshed on settle, not per-frame, to avoid a full-image histogram pass on
  every mouse-move).

## 2. Current behavior

- `ImageController` threads three named parameter dicts end-to-end:
  `exposure_params`, `tonal_params`, `color_params`. They flow through
  `ToolsPanel.get_*_params()` -> `on_adjustments_changed`/`apply_adjustments`
  -> `ThrottledDebouncer` -> `ProcessingWorker`/`ProcessingQueue`
  (`ProcessingRequest`) -> `CombinedAdjustmentCommand` (undo/redo) ->
  `get_adjustment_state()`/`restore_adjustment_state()` (persistence via
  `MainWindow._persist_current_adjustments()` ->
  `LibraryCatalogService`/`LibraryImagePreviewCacheService`).
- Every one of those dicts is `Dict[str, float]`; several call sites assume
  that shape directly: `ImageController._normalize_adjustment_state` does
  `float(value)` per key, `_submit_delayed_final_render`/
  `_commit_rendered_adjustment`/`commit_adjustments` do
  `any(v != 0 for v in params.values())`, and
  `LibraryImagePreviewCacheService.build_cache_key` does
  `float(adjustment_values.get(key, 0.0))` for **every** key in the persisted
  `values` dict.
- **Pre-existing gap found while reading this path:** `MainWindow.
  _adjustment_values_from_payload` (the function that turns a saved payload
  back into the dict passed to `restore_adjustment_state`) only whitelists
  `exposure/contrast/brightness/saturation/vibrance` -- it silently drops
  `highlights/shadows/whites/blacks` on reload even though they are
  persisted. This predates this slice (the whitelist was never updated when
  Highlights/Shadows/Whites/Blacks landed) but sits in the exact function this
  slice must edit to add curve restoration, so it is fixed in the same
  function change rather than left half-broken. Called out explicitly in the
  commit message as a bundled adjacent fix rather than split into a separate
  commit: every other new tone-curve source file has to land together for
  a standalone-bugfix commit's own tests to be meaningful, so splitting the
  diff further would have produced a same-function partial change, not a
  genuinely isolated one.
- Tone curve control points are not a float, so they cannot be merged into
  those three existing dicts without breaking every one of the call sites
  above.

## 3. Proposed design

Add a **fourth, parallel parameter category**, `curve_params`, following the
exact shape/threading pattern of `exposure_params`/`tonal_params`/
`color_params`, but kept out of the flat float dicts so none of the
float-only call sites need special-casing:

- `curve_params: Dict[str, Any]` with a single key, `"points"`, holding a
  tuple of `(x, y)` float pairs in `[0, 1]`, sorted by `x`, first point's `x`
  pinned to `0.0`, last point's `x` pinned to `1.0` (matches Lightroom: only
  interior points move in `x`). Default/identity is `((0.0, 0.0), (1.0,
  1.0))` -- a straight line, i.e. a no-op.
- New pure-math module `src/utils/curve_math.py` (no Qt/PIL dependency, same
  "chokepoint" spirit as `color_pipeline.py`): point normalization/
  validation, an `is_identity_curve()` check, a monotonic cubic (PCHIP /
  Fritsch-Carlson) spline sampled into a 256-entry LUT, LUT application via
  `np.interp`, and a luminance-histogram helper. Both the processor and the
  UI widget import this so the widget's drawn curve and the processor's
  applied curve are mathematically identical.
- New `src/processors/curve_processor.py` (`CurveProcessor(BaseProcessor)`):
  converts linear -> sRGB-encoded (`color_pipeline.linear_to_srgb`), applies
  the LUT to R/G/B identically (master curve), converts back
  (`srgb_to_linear`). Curves are applied in the sRGB-encoded domain because
  that is the domain the curve grid visually represents to the user (a
  0.5/0.5 point should look like "middle gray up", not a linear-light
  midpoint); `ColorProcessor` already establishes the precedent of
  clipping to `[0,1]` before a nonlinear conversion, so `CurveProcessor` does
  the same and is documented accordingly.
- Pipeline order: exposure -> tonal -> **curve** -> color, matching the PDF's
  own section ordering (11 Light, 12 Tone curve, 13 Color) and Lightroom's
  Basic -> Tone Curve -> Color/Presence panel order.
- New `src/views/widgets/curve_editor.py` (`CurveEditor(QWidget)`): custom
  `paintEvent`-drawn curve grid with an optional histogram backdrop,
  draggable/addable/deletable control points. Signals mirror
  `AdjustmentSlider`: `curve_changed(list)` (continuous, during drag) and
  `curve_released()` (on mouse release / discrete point add-delete / reset),
  matching the `value_changed`/`slider_released` pattern `ToolsPanel` already
  wires into `adjustments_changed`/`slider_released`.
- `ToolsPanel` gains a new "Tone Curve" section (between "Light" and
  "Color", matching PDF order) holding one `CurveEditor`, a new
  `get_curve_params()` getter (mirrors `get_exposure_params()` etc.), a new
  `curve_changed = pyqtSignal(list)` output signal, and threads curve state
  through `set_adjustments()`/`reset_all()`/`set_enabled()`. The existing
  `get_adjustments()`/`adjustments_changed` float-only contract is
  unchanged -- curve state travels on its own signal/getter, exactly the way
  `get_tonal_params()` is a separate getter rather than a new key jammed into
  the same float dict.
- `ImageController` gains `_curve_params`, a `CurveProcessor` instance, a new
  `on_curve_changed(points)` slot (parallel to `on_adjustments_changed`,
  reusing the same `ThrottledDebouncer` by adding a `"curve"` key to the dict
  already passed to `_debouncer.call(...)`), and curve threading through
  every method that currently touches
  `exposure_params`/`tonal_params`/`color_params`:
  `apply_adjustments`, `get_export_image`, `restore_adjustment_state`,
  `reset_to_original`, `_on_throttled_adjustment`, `_on_debounced_adjustment`,
  `_submit_delayed_final_render`, `_commit_rendered_adjustment`,
  `commit_adjustments`, `get_adjustment_state`/`_normalize_adjustment_state`.
  `get_adjustment_state()` gains one extra key, `"tone_curve"` (a
  JSON-plain `list[list[float, float]]`), alongside the nine existing float
  keys -- a documented, test-updating contract change (see section 4).
- `ProcessingQueue.ProcessingRequest`/`create_request` and
  `ProcessingWorker.submit_request`/`submit_preview_request`/
  `submit_final_request`/`_apply_adjustments`/`_cache_key`/
  `_adjustment_signature` gain a fourth `curve_params` argument, threaded the
  same way `tonal_params` was added alongside `exposure_params`/
  `color_params`. `curve_params["points"]` is stored as a tuple of 2-tuples
  (hashable) so `tuple(sorted(request.curve_params.items()))` used for the
  cache key works unchanged.
- `CombinedAdjustmentCommand` gains `curve_params` + a `CurveProcessor`,
  applied in the same exposure -> tonal -> curve -> color order.
- `MainWindow`: wires `ToolsPanel.curve_changed` -> a new
  `_on_curve_changed` -> `ImageController.on_curve_changed` (mirrors
  `_on_adjustments_changed`); fixes and extends
  `_adjustment_values_from_payload` to restore
  highlights/shadows/whites/blacks (bugfix, see section 2) and the new
  `tone_curve` key; refreshes the curve editor's histogram backdrop on
  initial image load and on slider/curve release (see section 5 for why not
  every frame).
- `LibraryImagePreviewCacheService.build_cache_key`'s per-key signature
  formatter is changed to special-case a list/tuple value (the curve points)
  instead of blindly calling `float(...)` on every persisted value, which
  would otherwise raise on the new `tone_curve` key. Existing float keys
  format identically to today (`f"{float(v):.4f}"`), so previously-cached
  preview keys for images with no curve edit do not change.

## 4. API and data contracts

- `ImageController.get_adjustment_state()` return shape changes from 9 float
  keys to 9 float keys + `"tone_curve": list[list[float]]` (e.g. `[[0.0,
  0.0], [1.0, 1.0]]` at identity). This is a breaking change to the exact
  dict equality asserted in
  `tests/unit/test_controllers/test_image_controller.py::
  test_get_adjustment_state_returns_normalized_defaults` and
  `test_restore_adjustment_state_applies_saved_values` -- both are updated in
  this slice.
- `ImageController.restore_adjustment_state(adjustments)` accepts an optional
  `"tone_curve"` key (list of `[x, y]` pairs); missing/malformed input falls
  back to the identity curve rather than raising, matching the existing
  float-normalization tolerance (`_normalize_adjustment_state` already
  swallows bad float input the same way).
- `ToolsPanel`: new `curve_changed = pyqtSignal(list)` signal; new
  `get_curve_params() -> Dict[str, Any]` (`{"points": [[x, y], ...]}`); new
  `set_adjustments(..., )` accepts an optional `"tone_curve"` key (same
  fallback-to-identity tolerance).
- `ProcessingRequest`/`ProcessingWorker`/`CombinedAdjustmentCommand`: new
  `curve_params: Dict[str, Any] = {}` parameter, additive and optional
  everywhere (default `{}` behaves as identity, matching how empty
  `tonal_params`/`color_params` already behave as no-ops).
- Persisted JSON (`library_catalog.json`, `adjustment_state.values`): gains
  one new key, `tone_curve`. No schema version bump -- `AdjustmentStack`
  (the separate, not-yet-wired `SCHEMA_VERSION`-tracked model in
  `src/models/adjustment_layer.py`) is untouched; the catalog's
  `adjustment_state` dict has always been an open, additive `Optional[dict]`
  with no version field of its own, and old catalogs without `tone_curve`
  already fall back correctly (`.get("tone_curve")` -> `None` -> identity).
- `curve_math.normalize_points()` is the single validation chokepoint: any
  malformed/out-of-range/unsorted input from disk or from the widget is
  clamped into a valid, sorted, endpoint-pinned tuple rather than raising.

## 5. Nuances and failure modes

- **Histogram cost/timing:** computing a 256-bin luminance histogram over a
  full preview frame on every mouse-move would compete with the existing
  60fps preview-present budget. The histogram is refreshed only on
  `image_load_finished` (initial) and on `slider_released`/`curve_released`
  (settle), using whatever `ImageController.get_current_image()` currently
  holds -- which may be an interactive-tier preview frame, not the final
  full-resolution render, immediately after a release. Documented as a known
  simplification; visually irrelevant since the histogram is a coarse
  backdrop reference, not a precision tool in this slice.
- **Point x-ordering:** dragging an interior point must not let it cross a
  neighbor's `x` (would make the mapping non-a-function and break the
  monotonic-spline assumption). `CurveEditor` clamps drag `x` to
  `(neighbor_left.x + MIN_GAP, neighbor_right.x - MIN_GAP)`; endpoints (index
  0 and -1) are clamped to `x == 0.0`/`x == 1.0` exactly and can only move in
  `y`.
  `curve_math.normalize_points()` re-clamps defensively on every entry point
  (widget restore, controller restore-from-disk) so a corrupted/hand-edited
  catalog file cannot produce a non-monotonic spline.
- **Degenerate single-point spline:** if normalization ever collapses to one
  point (should not happen given the two pinned endpoints, but guarded
  anyway), the LUT is a flat line at that point's `y` rather than raising.
- **Identity fast-path:** `CurveProcessor.process()` and the worker/queue
  `has_changes` checks special-case `is_identity_curve()` so an untouched
  curve costs nothing extra (no spline build, no sRGB round-trip) --
  mirrors how `tonal_params`/`color_params` already skip processing when all
  values are zero.
- **Cache key hashability:** `curve_params["points"]` must be a tuple of
  2-tuples (not lists) by the time it reaches `ProcessingQueue`/
  `ProcessingWorker`, since the preview cache key is built from
  `tuple(sorted(request.curve_params.items()))`. `curve_math.
  normalize_points()` always returns tuples, and `ImageController` is the
  only place that constructs `curve_params`, so this is enforced at a single
  chokepoint rather than at every call site.
- **RGBA passthrough:** `CurveProcessor`, like `TonalProcessor`, must only
  touch the first 3 channels; a regression test mirrors the existing
  `TestRgbaPassthrough` pattern in `test_tonal_processor.py`.
- **Existing preview-cache keys unaffected:** `build_cache_key`'s float
  formatting for pre-existing keys is byte-identical to before this change,
  so no user's on-disk cache is invalidated by this slice alone (only images
  that actually get a non-identity curve applied produce new cache keys).

## 6. UI and reskin impact

- New "Tone Curve" section in `ToolsPanel`, inserted between "Light" and
  "Color" (PDF order). Follows the existing dark-theme hex palette already
  hard-coded per-widget in this codebase (`#2d2d2d`/`#3a3a3a`/`#0078d4`) --
  no new design-token system introduced (that gap is tracked separately per
  INCREMENTAL_WORKFLOW.md section 5.1, out of scope here).
- `CurveEditor` is a self-contained widget with its own `paintEvent`; no
  adjustment math lives in the view layer (spline evaluation is imported
  from `curve_math.py`, consistent with "no adjustment math in widgets" in
  INCREMENTAL_WORKFLOW.md section 5.1). `CurveEditor` emits plain
  `list`/no-arg signals only, same as `AdjustmentSlider`.
- Double-click anywhere on the curve resets it to identity, mirroring
  `AdjustmentSlider.mouseDoubleClickEvent`'s existing reset-on-double-click
  convention elsewhere in the same panel.

## 7. Dependencies

- Builds directly on the Basic-panel slice's threading pattern; no new
  third-party dependency (monotonic spline implemented directly with numpy,
  no scipy in `Pipfile`).
- Blocks nothing else in Phase E; White Balance (temp/tint) and HSL
  Mixer/Color Grading remain independent, later slices per the roadmap.

## 8. Test plan

- `tests/unit/test_utils/test_curve_math.py` (new): point normalization
  (sorting, endpoint pinning, clamping, degenerate input), identity
  detection, LUT identity-passthrough for the 2-point default, monotonicity
  of the LUT for representative point sets, exact value at control points.
- `tests/unit/test_processors/test_curve_processor.py` (new): identity is a
  true no-op (byte-equal, mirrors `TestIdentity` in
  `test_tonal_processor.py`); a brightening curve increases a midtone pixel;
  a darkening curve decreases one; RGBA alpha passthrough untouched; dtype
  stays float32.
- `tests/unit/test_views/test_tools_panel.py`: extend with a `TestToneCurve`
  class mirroring the existing `TestTonalSliders`-style tests --
  `get_curve_params()` returns identity by default, `curve_changed` fires on
  programmatic point changes, `reset_all()` resets the curve, `set_enabled`
  disables the curve editor, curve changes do not perturb
  `get_exposure_params()`/`get_tonal_params()`/`get_color_params()`.
- `tests/unit/test_views/test_curve_editor.py` (new): click-to-add,
  drag-to-move (with neighbor-x clamping and endpoint x-pinning), right-click
  delete of an interior point (and that endpoints cannot be deleted),
  double-click reset, `curve_changed` vs `curve_released` signal timing.
- `tests/unit/test_controllers/test_image_controller.py`: update the two
  existing exact-dict-equality tests for the new `tone_curve` key; add
  curve-specific coverage of `on_curve_changed`/`restore_adjustment_state`
  round-tripping curve points, and that a non-identity curve reaches
  `get_export_image()`.
- `tests/unit/test_processing/test_processing_queue.py` /
  `test_processing_worker.py`: extend request creation/cache-key tests with
  `curve_params`.
- `tests/unit/test_commands/test_adjustment_commands.py`: extend
  `CombinedAdjustmentCommand` tests with a `curve_params`-only case.
- `tests/unit/test_views/test_main_window.py` (existing file, if present) or
  a focused new test: `_adjustment_values_from_payload` now restores
  highlights/shadows/whites/blacks/tone_curve (regression test for the
  pre-existing bugfix from section 2).
- `LibraryImagePreviewCacheService.build_cache_key`: regression test that a
  `tone_curve` list value in `adjustment_values` does not raise and that
  pre-existing float-only signatures are unchanged.
- Manual smoke (since this is UI-heavy): load an image, drag a curve point
  up (brightens), drag one down (darkens), delete an interior point, reset
  via double-click, release and confirm the full-res render lands and undo
  restores the pre-curve image, switch to another library image and back and
  confirm the curve is restored from disk.

## 9. Rollout and rollback

- Purely additive/threaded through existing optional-dict parameters;
  default value is the identity curve, so existing images/behavior are
  unaffected until a user actually touches the new control.
- Rollback: revert this slice's commit(s); `tone_curve` keys left in
  already-saved `library_catalog.json` files are harmless extra data that
  older code ignores (the old `_adjustment_values_from_payload` whitelist
  already ignores unknown keys).

## 10. Acceptance criteria

- Dragging a curve point updates the live preview through the same
  throttled/debounced threaded path as the Basic sliders, and a full-res
  render + undo entry lands on release.
- The curve is included in `get_adjustment_state()`/
  `restore_adjustment_state()`, persists across image switches and app
  restarts via the library catalog, and round-trips exactly.
- Highlights/Shadows/Whites/Blacks now also round-trip correctly through
  `_adjustment_values_from_payload` (bugfix verified by a regression test).
- Identity curve costs no extra processing (verified by the fast-path test).
- All new and updated unit tests pass; full existing suite stays green.

Plan approved -- implementation allowed: **Approved via autonomous continuation session (2026-09-29)**, per the user's request to continue the roadmap's next slice after Basic-panel completion.

## 11. Implementation summary

Landed:

- `src/utils/curve_math.py`: point normalization/validation (sorting,
  endpoint pinning at x=0/x=1, clamping, degenerate-input fallback to
  identity), a Fritsch-Carlson monotonic cubic (PCHIP) LUT builder, LUT
  application, and a luminance-histogram helper. No scipy dependency.
- `src/processors/curve_processor.py`: master RGB curve applied in the
  sRGB-encoded domain, with an identity fast-path and RGBA passthrough.
- `src/views/widgets/curve_editor.py`: interactive curve widget (click to
  add, drag to move with endpoint-x pinning and neighbor-x clamping,
  right-click to delete an interior point, double-click to reset),
  histogram backdrop, `curve_changed`/`curve_released` signals mirroring
  `AdjustmentSlider`.
- New "Tone Curve" section in `ToolsPanel`, between "Light" and "Color";
  `get_curve_params()`, `update_curve_histogram()`, curve threading through
  `set_adjustments()`/`reset_all()`/`set_enabled()`.
- Curve threading through `ImageController` (`on_curve_changed`, all
  render/undo/persistence paths), `ProcessingQueue`/`ProcessingWorker`
  (fourth `curve_params` argument throughout, including the cache key),
  and `CombinedAdjustmentCommand`.
- `MainWindow` wiring: `curve_changed` -> `on_curve_changed`; histogram
  refresh on initial load and on settle (slider/curve release); fixed
  `_adjustment_values_from_payload`'s stale whitelist (the pre-existing
  Highlights/Shadows/Whites/Blacks restore bug from section 2) and
  extended it for `tone_curve`.
- `LibraryImagePreviewCacheService.build_cache_key` now formats a
  list-valued adjustment (the curve) instead of crashing on
  `float(list)`; existing float-only signatures are unchanged (regression
  tested).
- Found and fixed one bug during implementation, not scoped in the
  original plan: `CurveEditor._paint_histogram` initially did `if not
  self._histogram:` on a numpy array, which raises (`ValueError: the
  truth value of an array ... is ambiguous`) as soon as any image is
  loaded and a real histogram is set -- caught by the widget's own test
  suite, not a code-review pass. Fixed to an explicit `is None`/`len() ==
  0` check.
- Deferred exactly as planned: per-channel R/G/B curves, curve presets,
  live per-frame histogram updates, White Balance, HSL Mixer/Color
  Grading.

Verified: full existing suite plus ~90 new/updated tests across
`curve_math`, `CurveProcessor`, `CurveEditor`, `ToolsPanel`,
`ImageController`, `ProcessingQueue`/`ProcessingWorker`,
`CombinedAdjustmentCommand`, `LibraryImagePreviewCacheService`, and
`MainWindow` all pass (468 passed; one pre-existing, unrelated
`offscreen`-QPA geometry-restoration flake confirmed present before this
slice via `git stash`, left untouched).

## 12. Interaction clarification and deferred history work

The master curve intentionally follows the conventional professional point-
curve model: the black endpoint is pinned at input `x=0` and the white endpoint
at input `x=1`, so both endpoints move vertically only. Because the identity
curve starts at `(0, 0)` and `(1, 1)`, the black endpoint can initially move
only upward (lift blacks) and the white endpoint initially only downward
(compress whites). Interior points move in both axes subject to neighbor order.
This is expected behavior, not a drag bug. Separate input-level controls that
could move effective black/white inputs horizontally remain future scope.

Undo/redo has a separate known limitation: the current history entry restores
the rendered image buffer but not the curve points or other adjustment state in
the controller and tools UI. Export and a subsequent preview can therefore use
the still-current post-edit parameters after an undo. A future state-aware
history slice must restore the complete before/after payload, controls, render,
export state, and persistence together; this limitation is tracked in Phase B
of `PRODUCT_ROADMAP.md`.
