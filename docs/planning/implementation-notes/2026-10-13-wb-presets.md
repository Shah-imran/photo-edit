# White-balance (WB) presets

Related roadmap: Phase E, "Light, Tone curve, Color" (PDF sections
11-13) in `docs/planning/PRODUCT_ROADMAP.md` -- specifically the third
bullet, "**Temperature/Tint** + WB presets." Temperature/Tint sliders
themselves already existed and were already fully wired (confirmed
before starting this slice by reading `src/views/tools_panel.py` and
the white-balance processor); this slice builds only the missing WB
presets half. Like the Profile selector, this is UI plumbing on top of
existing slider machinery, not a new image processor, so it follows
that same adapted (non-processor) note structure.

## 1. Problem, goal, and non-goals

**Problem.** There was no quick way to jump Temperature/Tint to a named
starting point (Lightroom's own "As Shot / Auto / Daylight / Cloudy /
Shade / Tungsten / Fluorescent / Flash / Custom" WB preset list)
without manually dragging both sliders by hand.

**Goal.** Add seven built-in named WB presets (`WB_PRESETS` in
`src/models/wb_presets.py`), and a compact "White Balance" preset combo
box + Apply button inside `ToolsPanel`'s existing "Color" section
(immediately above the Temperature/Tint sliders), wired to a new
`ToolsPanel._apply_wb_preset(name)` method that sets exactly those two
sliders to the chosen preset's values and nothing else.

**Non-goal 1 -- no "Auto" white balance.** Real Auto WB requires an
actual gray-world/illuminant-estimation algorithm that examines the
image's pixel data to compute a correction. That is a new
image-processing feature -- it needs code that looks at pixels, not a
preset lookup -- and is explicitly out of scope for this slice. It is
documented here as a **durable, separate future gap**, the same way
lens profiles and interactive crop were documented as durable gaps in
earlier slices (Phase H/I implementation notes).

**Non-goal 2 -- no literal "Custom" entry.** In real Lightroom,
"Custom" in the WB preset list isn't a value you pick; it is simply
what the preset indicator shows once Temperature/Tint have been
manually moved away from any preset's exact values. That state already
exists implicitly in this app the moment a user drags either slider --
there is nothing to compute or store, so no "Custom" button or combo
entry was added. (This mirrors how the Profile selector slice reasoned
about not needing a stored "which profile is active" fact.)

**Non-goal 3 -- these are not calibrated Kelvin values.** This is
stated prominently because it is the single easiest thing to get wrong
later: the Temperature and Tint sliders are this app's own arbitrary UI
units (`-100.0..100.0`, re-confirmed directly from
`AdjustmentSlider(...)` in `src/views/tools_panel.py`, not trusted from
a stale number recalled from a previous slice). "Daylight," "Cloudy,"
"Shade," "Tungsten," "Fluorescent," and "Flash" below are
**representative directional placements** within that arbitrary scale
-- chosen so their *relative* warmth/coolness relationships mirror the
real world -- not a physically-calibrated Kelvin-to-slider-unit
conversion. Nobody should read `WB_PRESETS["Tungsten"]["temperature"]
== -40.0` as "tungsten light is -40 Kelvin" or any such claim; it only
means "noticeably cooler on this slider than every other preset here."

**Other non-goals (same spirit as the Profile selector slice):**

- No per-preset strength/amount slider -- presets are all-or-nothing.
- No undo/redo command for Apply (same acknowledged image-buffer-only
  history as every other adjustment in this app).
- No persistence of "which WB preset was last applied" -- there is no
  such fact to persist, since (per non-goal 2) no "active preset" state
  is ever computed or stored in the first place.

## 2. Current behavior (before this slice)

Temperature and Tint sliders (`self._temperature_slider`,
`self._tint_slider` in `ToolsPanel._setup_ui`, both
`AdjustmentSlider("...", min_value=-100.0, max_value=100.0,
default_value=0.0, step=1.0, decimals=0, ...)`) already existed inside
the "Color" section, already wired through
`value_changed.connect(lambda v: self._on_adjustment_changed('temperature'|'tint', v))`
and `slider_released.connect(self._on_slider_released)`, and the
white-balance processor downstream (via `ImageController`/the
processing queue) already applied both. Nothing about that existing
wiring needed to change.

`AdjustmentSlider.set_value(value: float) -> None` (in
`src/views/widgets/adjustment_slider.py`) already existed too: it
clamps to the slider's own `min_value`/`max_value` and calls
`self._spin_box.setValue(value)`. Tracing `_connect_signals` in
`AdjustmentSlider` confirms `self._spin_box.valueChanged` is connected
to `self._on_spinbox_changed`, which re-syncs the internal `QSlider`
and then emits `self.value_changed.emit(value)` -- so calling
`.set_value(...)` on a slider from outside code is equivalent to the
user dragging it, exactly as several earlier slices (Profile selector,
Copy/Paste Edit Settings) already relied on for other sliders. This
slice re-confirmed that chain by reading it directly rather than
assuming it still held.

## 3. Design

### `WB_PRESETS` (`src/models/wb_presets.py`)

A plain `Dict[str, Dict[str, float]]` (seven entries, "As Shot" first,
matching Python 3.7+ dict insertion order -- no extra bookkeeping
needed for display order), each value a partial dict of exactly
`{"temperature": ..., "tint": ...}`:

| Preset | temperature | tint | Real-world relative-warmth reasoning |
|---|---|---|---|
| As Shot | 0.0 | 0.0 | Neutral baseline -- leaves the image's existing Temperature/Tint untouched, analogous to "use the camera's own as-recorded white balance." |
| Daylight | 10.0 | 0.0 | Reference midday sunlight; treated as the slightly-warm-of-neutral baseline every other outdoor preset below is measured against. |
| Cloudy | 20.0 | 0.0 | Overcast skies filter out some direct warm sunlight, so ambient light is bluer than daylight -- correction adds more warmth than Daylight. |
| Shade | 30.0 | 5.0 | Open shade is bluer still (no direct sun at all, more blue sky light), needing the warmest Temperature correction of the outdoor presets, plus a small Tint nudge. |
| Tungsten | -40.0 | 10.0 | Incandescent/tungsten bulbs are strongly orange; neutralizing that calls for a strongly cool/blue-shifted correction -- by far the most negative Temperature value, clearly apart from every outdoor preset. |
| Fluorescent | -20.0 | 25.0 | Fluorescent tubes commonly cast green; the Tint slider's own green(-)/magenta(+) gradient (confirmed from its `color_gradient` construction: `stop:0 #36b94c` green -> `stop:1 #d52ac8` magenta) corrects that with the largest positive (magenta) Tint value here, alongside a moderate cool Temperature shift. |
| Flash | 5.0 | 0.0 | Camera flash is close to daylight-balanced, often marginally warmer in practice -- a small positive Temperature nudge, no Tint shift. |

Every value is well inside the real, source-confirmed `-100.0..100.0`
range for both keys. The relative ordering that matters -- Tungsten
coolest by a wide margin; Daylight < Cloudy < Shade warming
progressively; Fluorescent leaning hardest on Tint -- is pinned
directly by tests (see Test plan), not left as an unverified claim in
prose only.

### `ToolsPanel` UI (`src/views/tools_panel.py`)

A `QComboBox` (`self._wb_preset_combo`, populated from
`WB_PRESETS.keys()`) and an "Apply" `QPushButton`
(`self._wb_preset_apply_button`) are added as one row *inside the
existing* "Color" `CollapsibleSection`, immediately above the
Temperature slider -- no new top-level section was created, since the
roadmap bullet groups Temperature/Tint and WB presets together and
they already share a section. This mirrors the Profile section's own
"selecting the combo alone does nothing, only Apply acts" pattern:
there is no `currentTextChanged`/`currentIndexChanged` handler at all,
so browsing the dropdown has zero effect until Apply is clicked.

`_apply_wb_preset(self, preset_name: str) -> None`, called from the
Apply button's `clicked` handler (reading the combo's current
selection at click time, same as Profile):

```python
def _apply_wb_preset(self, preset_name: str) -> None:
    preset = WB_PRESETS.get(preset_name)
    if preset is None:
        return
    self._temperature_slider.set_value(preset["temperature"])
    self._tint_slider.set_value(preset["tint"])
    self.slider_released.emit()
```

This is **entirely self-contained inside `ToolsPanel`**: it reuses the
sliders' own existing `value_changed` -> `_on_adjustment_changed` path
(already wired; fires `adjustments_changed` for each slider exactly as
a live drag would) and manually emits the existing `slider_released`
signal afterward, the same signal a real slider release already
emits, already connected to `self._on_slider_released` -> triggers the
final high-quality render path.

### Why this needed zero `MainWindow`/`ImageController` changes (traced)

Unlike the Profile selector (which replaces the *entire* adjustment
state and therefore needs `MainWindow._apply_profile` to call
`ImageController.restore_adjustment_state`), a WB preset only ever
needs to move two already-wired sliders. Tracing the full chain
confirms it:

1. `AdjustmentSlider.set_value(preset["temperature"])` ->
   `self._spin_box.setValue(...)` -> (if the value actually changed)
   `self._spin_box.valueChanged` -> `_on_spinbox_changed` -> re-syncs
   the internal `QSlider` and emits `self.value_changed.emit(value)`.
2. `ToolsPanel`'s own `self._temperature_slider.value_changed.connect(
   lambda v: self._on_adjustment_changed('temperature', v))` (already
   wired, unmodified) fires -> `_on_adjustment_changed` updates
   `self._adjustments['temperature']` and, since
   `self._suppress_adjustment_signal` is `False` during a normal Apply
   click (it is only ever set `True`/`False` inside
   `set_adjustments(...)`, which `_apply_wb_preset` never calls),
   emits `self.adjustments_changed.emit(self._adjustments.copy())`.
3. The same happens for `self._tint_slider.set_value(preset["tint"])`.
4. `self.slider_released.emit()` fires `ToolsPanel`'s own
   `slider_released` signal, already connected in `MainWindow` to
   whatever triggers the final high-quality render -- exactly the
   signal a real slider release already emits on mouse-up.

Every step reuses a connection that already existed before this slice;
none of it required a new `MainWindow` method, a new
`ImageController` method, or a new signal reaching outside
`ToolsPanel`. This claim is also pinned directly by
`test_apply_emits_adjustments_changed_touching_only_wb_keys` in the
test plan below, which asserts every *other* adjustment key is
unchanged after Apply.

## 4. Contracts

- `src/models/wb_presets.py`: `WB_PRESETS: Dict[str, Dict[str, float]]`
  -- exactly seven entries (`As Shot`, `Daylight`, `Cloudy`, `Shade`,
  `Tungsten`, `Fluorescent`, `Flash`), each a two-key
  `{"temperature": float, "tint": float}` dict, each value within the
  real Temperature/Tint slider range in `tools_panel.py`. `As Shot` is
  exactly `{"temperature": 0.0, "tint": 0.0}`.
- `ToolsPanel._wb_preset_combo: QComboBox`,
  `ToolsPanel._wb_preset_apply_button: QPushButton` -- new attributes,
  exercised directly by the new tests.
- `ToolsPanel._apply_wb_preset(self, preset_name: str) -> None` -- new
  method; unknown preset name is a silent no-op (returns before
  touching either slider).
- No existing method's signature or behavior changed. No new signal
  crosses `ToolsPanel`'s boundary; `MainWindow`/`ImageController` are
  untouched by this slice.

## 5. Nuances and failure modes

**Unknown/garbage preset name.** `WB_PRESETS.get(preset_name)`
returning `None` (only reachable if `_apply_wb_preset` is called
directly with a name not in the dict, since the combo only ever offers
real `WB_PRESETS` keys) returns immediately, touching neither slider
and emitting neither signal.

**Re-applying the same preset emits fewer signals, not none.**
`QDoubleSpinBox.setValue(...)` only emits `valueChanged` when the new
value actually differs from the current one. If, say, Temperature is
already at a preset's exact value and Apply is clicked again (or "As
Shot" is applied to an already-neutral image), that slider's
`value_changed`/`adjustments_changed` simply does not fire again for
that key -- `slider_released` is still always emitted unconditionally
at the end of `_apply_wb_preset`, so a final render is still triggered
even in that edge case.

**Selecting without clicking Apply changes nothing.** Verified
directly, matching the Profile section's own precedent: no signal is
connected to the combo's own change signals.

**No "currently applied WB preset" state anywhere.** As documented in
non-goal 2, nothing records which preset (if any) was last applied, or
whether Temperature/Tint are currently "at" any preset at all. This is
intentional, not a gap -- see non-goal 2's reasoning.

**Interaction with the adjustment-persist timer.** Unlike Profile
Apply, `_apply_wb_preset` does not itself call
`self._adjustment_persist_timer.start()` directly -- but it does not
need to: that timer is owned and started by `MainWindow`'s own
`adjustments_changed`/`slider_released` handlers (the same ones every
ordinary slider drag already triggers), and `_apply_wb_preset` emits
both of those exact signals through the exact same existing slider
path, so persistence already happens on the same debounced schedule as
any manual Temperature/Tint drag, with no new wiring needed.

## 6. Test plan

- `tests/unit/test_models/test_wb_presets.py` (new file, mirroring
  `test_builtin_profiles.py`'s style): parses the real
  Temperature/Tint `min_value`/`max_value` directly out of
  `tools_panel.py`'s source text (not hand-duplicated); exactly seven
  presets with the expected names; `"As Shot"` is exactly
  `{"temperature": 0.0, "tint": 0.0}`; every preset has exactly the
  `temperature`/`tint` keys; every value is within the real,
  source-parsed range; Tungsten is strictly the coolest (most negative
  Temperature) of all seven; Shade > Cloudy > Daylight > As Shot in
  Temperature (pinning the real-world relative-warmth ordering, not
  just prose).
- `tests/unit/test_views/test_tools_panel.py`
  (`TestToolsPanelWbPresets`): combo populated with all `WB_PRESETS`
  names in order (As Shot first); selecting a combo entry alone does
  not change either slider's value; clicking Apply sets both sliders
  to the selected preset's exact values; clicking Apply emits
  `adjustments_changed` with the updated temperature/tint while every
  *other* key in the emitted dict is confirmed unchanged from its
  value before Apply (the single most important test in this slice,
  confirming the "touches only WB, nothing else" claim); clicking
  Apply emits `slider_released`; calling `_apply_wb_preset` with an
  unknown name is a no-op.

## 7. Rollout

Purely additive: one new module (`src/models/wb_presets.py`), one new
row + two new attributes + one new method inside `ToolsPanel`. No
existing method's signature or behavior changed, no processor was
added or touched, and no `MainWindow`/`ImageController` wiring was
added. A plain revert removes the feature entirely with no migration
in either direction -- nothing new is persisted to disk; applying a
preset is indistinguishable, in persisted state, from a user manually
setting the same two slider values.

## 8. Implementation summary

Added `src/models/wb_presets.py` with `WB_PRESETS`, a seven-entry
`Dict[str, Dict[str, float]]` (As Shot/Daylight/Cloudy/Shade/
Tungsten/Fluorescent/Flash), each a `{"temperature", "tint"}` pair
chosen for real-world-relative directional warmth/coolness within the
existing `-100.0..100.0` Temperature/Tint slider range -- explicitly
not calibrated Kelvin values. Added a "White Balance" preset row
(`QComboBox` + "Apply" `QPushButton`) to `ToolsPanel._setup_ui`'s
existing "Color" section, directly above the Temperature slider, plus
`ToolsPanel._apply_wb_preset(preset_name)`, wired only to the Apply
button's `clicked`. Explicitly did not build an "Auto" preset (durable
future gap requiring real pixel-analysis white-balance estimation) or
a literal "Custom" entry (already implicit the moment Temperature/Tint
are manually moved).

This completes the Phase E roadmap bullet "Temperature/Tint + WB
presets" in full -- Temperature/Tint were already fully wired before
this slice, and WB presets are now added via this self-contained
`ToolsPanel` mechanism.

No changes were made to `MainWindow`, `ImageController`, any
processor, or any other existing `ToolsPanel` method/signal -- traced
and confirmed in section 3 above (Apply reuses the sliders' own
existing `value_changed`/`slider_released` wiring end-to-end; no new
signal crosses `ToolsPanel`'s boundary).

**Deviation note.** None of substance. The illustrative preset values
given in the task description were adopted as the final values after
independently re-deriving and confirming the same real-world relative
relationships (Tungsten coolest by a wide margin; Daylight < Cloudy <
Shade warming progressively; Fluorescent leaning hardest on Tint for
its green-cast correction) -- no numeric changes were made to them.

Verification: new tests -- `tests/unit/test_models/test_wb_presets.py`
**8 passed**, `TestToolsPanelWbPresets` in
`tests/unit/test_views/test_tools_panel.py` **6 passed** (14 new tests
total; full new-test-file run together with the rest of
`test_tools_panel.py` showed **104 passed** for those two files
combined); complete suite run via
`QT_QPA_PLATFORM=offscreen python3 -m pytest -q --deselect tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::test_geometry_is_restored_on_next_launch`
**1018 passed, 1 skipped, 1 deselected in 139.04s** (1004 pre-existing
+ 14 new; the deselected test is the same pre-existing
offscreen-rendering flake noted in prior implementation notes,
unrelated to this slice; the 1 skipped test is pre-existing and
unrelated to this work). No flakes observed, including no occurrence
of the previously-noted intermittent `TestLibraryPanel::test_clear_library`
flake. A live GUI smoke test (actually clicking the WB preset combo/
Apply button in the real running app) was not performed in this
non-interactive environment; the behavior is instead pinned at the
`ToolsPanel`-level unit tests above.
