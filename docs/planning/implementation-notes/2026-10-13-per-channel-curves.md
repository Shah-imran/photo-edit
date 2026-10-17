# Per-channel (R/G/B) Tone Curve editing

Related roadmap: Phase E ("Light, Tone curve, Color", PDF sections
11-13), `docs/planning/PRODUCT_ROADMAP.md`'s row 12. Related prior
slices: `docs/planning/implementation-notes/2026-09-29-tone-curve.md`
(the master-curve slice this one builds directly on top of -- the
sRGB-domain LUT math, the `CurveEditor` widget, and the controller's
`_curve_params`/`"points"` wiring this slice extends rather than
replaces) and `docs/planning/implementation-notes/
2026-10-13-geometry-processor.md` (the most recently completed example
of threading a new multi-key parameter through every pipeline/
controller/UI call site, whose checklist this slice follows for
`_curve_params`'s 3 new optional keys).

## 1. Problem, goal, and non-goals

PDF section 12 lists "Point curve, **RGB, R/G/B channels**, histogram"
for the Tone Curve panel. Before this slice, PhotoEdit had exactly one
curve -- `CurveProcessor` applied a single LUT identically to R/G/B, and
`CurveEditor` edited that one curve only. The histogram backdrop (the
other half of PDF Sec.12's wording) was, in fact, already fully wired
since the master-curve slice (`CurveEditor._paint_histogram`, fed by
`ToolsPanel.update_curve_histogram`/`MainWindow._refresh_curve_histogram`)
-- the roadmap's row 12 had gone stale claiming otherwise, and is
corrected alongside this slice (see section 6).

**Goal:** add 3 more independent curves -- Red, Green, Blue -- each
editable on its own, composing with the master curve and with each
other, with a channel selector in the UI to switch which one responds
to the mouse.

**Explicitly NOT built here:**

- **Preset/named curves** (e.g. Lightroom's "Medium Contrast"/"Strong
  Contrast" point-curve presets). PDF Sec.12 does not call these out by
  name the way it calls out "RGB, R/G/B channels"; a preset system is a
  separate, additive feature on top of this slice's 4-curve data model,
  not a prerequisite for it.
- **Numeric point-position entry** (typing exact x/y values for a
  selected point). Lightroom's own point curve is mouse-only; this
  slice keeps that precedent.
- **A per-channel "Reset All" that also resets other tools.** The new
  "Reset All Channels" button (see section 4) only touches the 4 curves,
  mirroring every other section's own self-scoped reset button.

## 2. Design

### 2.1 Composition model

Each of the 4 curves -- `master`, `red`, `green`, `blue` -- is its own
independent list of `(x, y)` control points, defaulting to the identity
diagonal (`DEFAULT_CURVE_POINTS`). They compose in a fixed order inside
`CurveProcessor.process`:

1. The master curve's LUT, if non-identity, is built once and applied to
   **all 3 channels identically** -- exactly what the processor already
   did before this slice.
2. Each of the 3 per-channel LUTs, if non-identity, is then applied to
   **that one channel alone**.

This mirrors a real-world point-curve pipeline (a global contrast move
first, then per-channel color-balance tweaks on top of it) and is the
only order that makes "change the red channel's curve" provably isolated
from green/blue: the master step touches every channel identically, so
it cannot itself introduce cross-channel differences, and each
per-channel step is a `srgb[..., channel_index] = apply_curve_lut(...)`
assignment that writes to one channel's array slice only.

All-4-curves-identity remains a true, zero-LUT-work no-op, mirroring
`StraightenProcessor`/`GeometryProcessor`'s own "all defaults => identity
copy" convention: `CurveProcessor.process` checks
`is_identity_curve(points) and is_identity_curve(red_points) and
is_identity_curve(green_points) and is_identity_curve(blue_points)`
up front and returns a plain copy before building any LUT or doing the
sRGB round-trip at all.

### 2.2 `CurveProcessor.process`'s new signature

```python
def process(
    self,
    image: LinearImage,
    points: CurvePoints = None,
    red_points: CurvePoints = None,
    green_points: CurvePoints = None,
    blue_points: CurvePoints = None,
) -> LinearImage:
```

Four separate optional kwargs, not one nested `curves: dict` parameter.
This was a deliberate choice between two precedents already in the
codebase:

- `MaskProcessor.process(image, mask: Optional[Dict] = None)` -- one
  structured dict for a genuinely single, cohesive concept (one mask's
  several fields, which only make sense together).
- Every other processor with multiple independent numeric knobs
  (`GeometryProcessor.process(image, distortion=0.0, vertical=0.0,
  horizontal=0.0, scale=100.0, offset_x=0.0, offset_y=0.0)`,
  `TonalProcessor`'s 4 kwargs, etc.) -- flat kwargs, one per knob.

The 4 curves are independent (any subset can be identity while others
are not) rather than one cohesive structure the way a mask's
`{type, geometry, adjustments}` is, so the flat-kwargs precedent fits
better. It also threads through the rest of the codebase for free:
`ImageController`, `ProcessingWorker`, and `CombinedAdjustmentCommand`
already call every processor as `processor.process(result,
**self._xxx_params)`, spreading a plain dict as kwargs -- so
`_curve_params` simply grows 3 more *optional* keys
(`"red_points"`/`"green_points"`/`"blue_points"`) alongside its existing
`"points"` key, and every one of those existing `**self._curve_params`
call sites (there are over a dozen, in `ImageController.get_export_image`,
`restore_adjustment_state`, `apply_adjustments`, and
`ProcessingWorker._apply_adjustments`) needed **no changes at all** --
they were already generic over whatever keys the dict happens to carry.
Matching `_curve_params`'s existing falsy-skip convention, a channel's
key is only present in the dict when that channel is non-identity, so
`CurveProcessor` only builds a LUT for a channel that actually needs
one.

### 2.3 `CurveEditor` widget

`CurveEditor` grew a `_channel_points: Dict[str, List[Point]]` (keyed by
`"master"/"red"/"green"/"blue"`) and an `_active_channel` field. Every
existing paint/mouse-handling method (`_paint_curve`, `_paint_points`,
`_nearest_point_index`, `_clamp_drag`, the 4 mouse-event handlers) still
reads and mutates a single `self._points` list exactly as before --
`self._points` is now a Python `property` that gets/sets
`self._channel_points[self._active_channel]` by reference, so none of
that interaction code needed to change at all.

A small channel-selector bar ("RGB"/"R"/"G"/"B", 4 checkable
`QPushButton`s in a `QButtonGroup`) sits above the curve canvas;
clicking one calls `set_active_channel`, which switches
`_active_channel` and repaints -- it does not itself change any curve's
shape. The other 3 (non-active) channels' curves are drawn faintly,
tinted in their own channel color (`#ff5a5a`/`#5adc5a`/`#5a96ff` at low
alpha), behind the active curve -- a deliberately modest nice-to-have
(not a full Lightroom-style precise overlay) that is enough to tell at a
glance which channels have been touched and which one the mouse
currently edits.

**API compatibility decision:** `get_points()`/`set_points()` **keep
their original, pre-channel meaning** -- with no `channel` argument,
they read/write whichever channel is currently active (`"master"`,
right after construction, since that is the widget's initial active
channel). This is what lets every pre-existing caller
(`tests/unit/test_views/test_curve_editor.py`,
`tests/unit/test_views/test_tools_panel.py`'s master-curve assertions)
keep passing completely unchanged -- confirmed by running both files
with zero edits (see section 5). Both methods also accept an optional
`channel` argument for the other 3 channels. Two new channel-aware
entry points, `get_all_points()`/`set_all_points()`, round-trip all 4
curves at once (used by `ToolsPanel.set_adjustments`/`reset_all`).

Two new signals were added rather than changing `curve_changed`'s
payload shape (which would have broken every existing connection):

- `channel_curve_changed = pyqtSignal(str, list)` -- `(channel, points)`,
  emitted alongside `curve_changed` on every point mutation (drag,
  add, delete, reset). This is what `ToolsPanel` connects to for the
  real multi-channel wiring, since `curve_changed` alone reports the
  active channel's points without saying *which* channel that is.
- `active_channel_changed = pyqtSignal(str)` -- emitted when the
  channel-selector bar switches channels (not on a curve-shape change).

`reset()` resets only the **active** channel (the standard curve-editor
convention -- Lightroom's own per-channel "Reset" works the same way).
A new `reset_all_channels()` resets all 4 at once, for the optional
"Reset All Channels" affordance.

### 2.4 `ToolsPanel`

Mirrors `CurveEditor`'s own compatibility approach: `self._curve_points`
(a flat list) became `self._channel_curve_points` (a dict of 4 lists,
keyed the same way), and `get_curve_params()` still always returns a
`"points"` key for the master curve (unchanged shape for that one key),
now joined by `"red_points"`/`"green_points"`/`"blue_points"` whenever
that one channel is non-identity -- matching
`ImageController._curve_params`'s own falsy-skip convention exactly, so
`get_curve_params()`'s result can be spread straight into
`CurveProcessor.process`/`ImageController.apply_adjustments` unchanged.

`_on_curve_editor_changed(points, channel="master")` gained an optional
`channel` parameter (defaulting to `"master"` so every existing direct
call -- including the test suite's -- keeps editing the master curve).
It is connected to `CurveEditor.channel_curve_changed` (not the legacy
`curve_changed`), so a real widget-driven edit always arrives with an
explicit channel. A new `curve_channel_changed = pyqtSignal(str, list)`
signal on `ToolsPanel` itself re-emits `(channel, points)` to
`MainWindow`; the old `curve_changed = pyqtSignal(list)` signal is kept,
still firing only for `channel == "master"`, with its original payload
shape, purely for backward compatibility with any existing listener
that only ever cared about the master curve.

The "Reset Tone Curve" header button is unchanged (`self._curve_editor.
reset`, which -- now that `reset()` is channel-aware -- resets only the
active channel). A new "Reset All Channels" header button
(`self._curve_editor.reset_all_channels`) was added next to it for the
"reset everything" case.

### 2.5 `ImageController`

`_curve_params: Dict[str, Any]` grows the same 3 optional keys as
`CurveProcessor`'s kwargs (`"points"`/`"red_points"`/`"green_points"`/
`"blue_points"`), each present only when that channel is non-identity.
A new `_CURVE_CHANNEL_KEYS = {"master": "points", "red": "red_points",
"green": "green_points", "blue": "blue_points"}` maps the UI's channel
name to the `_curve_params` key it owns.

`on_curve_changed(points, channel="master")` gained the same
backward-compatible `channel` parameter as `ToolsPanel`'s handler, and
now **merges** into `self._curve_params` (updating or removing only the
one key the changed channel owns) instead of replacing the whole dict --
unlike the pre-slice version, which only ever had one key to replace,
so "replace the dict" and "update one key" were the same operation.

`get_adjustment_state()` gained 3 new top-level keys --
`"tone_curve_red"`/`"tone_curve_green"`/`"tone_curve_blue"` -- with the
exact same JSON-plain `[[x, y], ...]` shape as the existing
`"tone_curve"` key, each defaulting to the identity curve.
`_apply_state_params()` normalizes and stores all 4 the same way it
already did for the master curve, and returns all 4 normalized point
lists so `restore_adjustment_state`'s `has_changes` check can test each
one for identity (mirroring the existing `not is_identity_curve
(curve_points)` check, now joined by 3 more). `_has_pending_adjustment_
changes()` gained the same 3 additional identity checks.

No other `_xxx_params`-adjacent call site (`get_export_image`,
`apply_adjustments`, `ProcessingRequest`/`ProcessingWorker`,
`CombinedAdjustmentCommand`, the throttled/debounced dicts in
`on_adjustments_changed`/`_on_throttled_adjustment`/
`_on_debounced_adjustment`/`on_slider_released`/
`_submit_delayed_final_render`/`commit_adjustments`) needed any change:
every one of them already passes `self._curve_params` through generically
as `**self._curve_params` or `curve_params=self._curve_params`, so the
dict simply carries more optional keys now.

### 2.6 `MainWindow`

`_connect_signals` now connects `ToolsPanel.curve_channel_changed`
(not the legacy `curve_changed`) to `_on_curve_changed`, which gained a
`channel` parameter and forwards it to `ImageController.on_curve_changed
(points, channel=channel)`. `_adjustment_values_from_payload` (the
library-catalog restore whitelist) gained the same 3 new
`"tone_curve_red"`/`"tone_curve_green"`/`"tone_curve_blue"` keys
alongside the existing `"tone_curve"`.

## 3. Test plan

- `tests/unit/test_processors/test_curve_processor.py`
  (`TestPerChannelIdentity`/`TestPerChannelIsolation`, new): all-4-
  curves-identity is a true no-op (both implicit and with every channel
  passed explicitly as identity) and still returns a new array object;
  a red-only/green-only/blue-only curve change leaves the other 2
  channels' pixels unchanged (within ~1e-6 sRGB round-trip float32
  noise) while demonstrably changing its own channel -- the clean,
  decisive way to prove channel isolation; master+per-channel
  composition (a red-raising master plus a red-lowering per-channel
  curve differs from a master-only render on red, while green/blue
  match the master-only render exactly); endpoints stay black/white
  with all 3 per-channel curves active; shape/dtype/alpha-passthrough
  preserved with all 4 curves active together.
- `tests/unit/test_controllers/test_image_controller.py`: the 2
  existing exact-dict `get_adjustment_state()` assertions were updated
  to include the 3 new `"tone_curve_red"`/`"tone_curve_green"`/
  `"tone_curve_blue"` identity-default keys; the full existing
  master-curve round-trip/undo-redo coverage (`on_curve_changed`,
  `restore_adjustment_state`) was re-run unchanged to confirm no
  regression.
- `tests/unit/test_views/test_curve_editor.py`: the entire existing
  8-test file passes **completely unchanged** against the refactored
  widget, confirming `get_points()`/`set_points()`/`curve_changed`/
  `curve_released` kept their exact pre-channel meaning and payload
  shapes.
- `tests/unit/test_views/test_tools_panel.py`: the entire existing
  `TestToolsPanelToneCurve` class (and the rest of the 100-test file)
  passes unchanged for the same reason -- `get_curve_params()`,
  `_on_curve_editor_changed`, `set_adjustments`, and `reset_all` all
  default to the master channel exactly as before when no channel is
  specified.
- Full suite re-run end to end (`pytest`, offscreen Qt platform) to
  confirm no regression elsewhere; see section 6 of this note's sibling
  slices for the one known, pre-existing, unrelated flaky test
  (`test_geometry_is_restored_on_next_launch`, a native window-geometry
  timing flake under `QT_QPA_PLATFORM=offscreen`, not something this
  slice touches).

## 4. Rollout

Additive and backward-compatible on every axis:

- A persisted adjustment-state dict (an old catalog entry, an exported
  preset, a Copy/Paste Edit Settings clipboard entry) with no
  `"tone_curve_red"`/`"tone_curve_green"`/`"tone_curve_blue"` keys at
  all restores all 3 to their identity default via `normalize_points`'
  existing "falls back to the default curve" tolerance -- old saved
  edits render identically to before this slice.
- Every pre-existing `CurveProcessor.process(image, points=...)` call
  (positional-or-keyword `points` only) behaves identically: the 3 new
  kwargs default to `None`, which `is_identity_curve` treats as
  identity.
- Every pre-existing `CurveEditor`/`ToolsPanel` caller that only ever
  touched the master curve (`get_points()`, `set_points()`,
  `get_curve_params()`, `_on_curve_editor_changed(points)`,
  `on_curve_changed(points)`) keeps working with no changes, since each
  method's `channel` parameter defaults to `"master"`.

## 5. Summary

The Tone Curve panel now matches PDF Sec.12's "Point curve, RGB, R/G/B
channels, histogram" in full: 4 independent point curves (master +
Red/Green/Blue), a channel selector to switch between them, all 4
composing correctly (master first, applied to all 3 channels; then each
channel's own curve, applied to that channel alone), and the
curve-overlaid histogram backdrop that had already existed since the
first Tone Curve slice (the roadmap row claiming it as a gap was itself
stale, and is corrected alongside this slice). `CurveProcessor`,
`CurveEditor`, `ToolsPanel`, `ImageController`, and `MainWindow` were all
extended using the same "new parameter/key defaults to the old,
single-curve behavior" compatibility discipline, so every pre-existing
call site, signal connection, and test needed either no change or a
narrowly-scoped one.
