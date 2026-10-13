# Profile selector (built-in looks)

Related roadmap: Phase D, "Profiles and presets" (PDF section 10) in
`docs/planning/PRODUCT_ROADMAP.md` -- specifically the first bullet,
"Profile selector (start with built-in looks analogous to Adobe
Standard / Monochrome / etc.)." Like Copy/Paste Edit Settings and
Export with Previous, this is UI + data plumbing on top of an existing
whole-state-apply mechanism, not a new image processor, so this note
follows that adapted (non-processor) section structure.

## 1. Problem, goal, and non-goals

**Problem.** There was no quick way to jump an image's adjustments to
one of a small set of named starting looks (Lightroom's "Profiles":
Adobe Standard, Monochrome, Vivid, Landscape, Portrait, etc.) without
manually dragging every slider.

**Goal.** Add five built-in named profiles (`BUILTIN_PROFILES` in
`src/models/builtin_profiles.py`), a compact "Profile" combo box + Apply
button at the top of `ToolsPanel`'s scrollable adjustments area (above
"Light"), and `MainWindow._apply_profile(name)`, wired to the combo's
Apply button, which replaces the current image's entire adjustment
state with the chosen profile's predefined values -- reusing exactly
the `set_adjustments(...)` / `restore_adjustment_state(...)` /
`_adjustment_persist_timer.start()` pattern that
`_reset_adjustments()` and `_paste_edit_settings()` already established.

**Honest scope boundary -- this is NOT real Lightroom Profiles.** Real
Lightroom Profiles are a distinct, persistent pipeline stage: a profile
is a baseline rendering intent applied *before* the Develop module's
sliders, with slider adjustments stacking on top of whichever profile
is active, and the profile choice remembered separately from the
slider values (so switching profiles later re-renders through the new
baseline without disturbing the slider values on top of it). Building
that would mean a new, separate pipeline stage, new persisted state
(the "which profile is active" fact, independent of the adjustment
dict), and reworking how Reset/Paste/Copy interact with a profile
baseline underneath them -- a bigger, riskier architectural change than
this slice should attempt.

What is actually built instead is a **"Profile" preset-apply action**:
selecting a named profile and clicking Apply immediately sets the
current image's adjustment sliders to that profile's predefined
starting values, through the exact same whole-state-replace mechanism
Reset and Paste Edit Settings already use. This is "apply this
preset's starting values now, as if you had dragged the sliders there
yourself," not a persistent separate baseline layer:

- There is no "active profile" state remembered anywhere. After
  clicking Apply, the image's state is indistinguishable from a user
  who manually set those same slider values -- there is no way to later
  ask "what profile is this image on" or "re-apply the current profile
  after I nudge a slider," because no such fact is stored.
- Applying "Standard" is equivalent to Reset (see Design below), not a
  separate no-op baseline choice.
- A profile's values are **not** layered underneath manual slider
  edits; clicking Apply overwrites the current slider values entirely,
  same as Paste Edit Settings does.

**Also explicitly out of scope: "Import presets."** The roadmap's
second Phase D bullet, "Import presets subset (e.g. JSON or LUT-based)
-- full 'Import Profiles & Presets' parity can grow incrementally," is
a separate, larger feature (reading externally-authored preset files,
likely a different on-disk format, a file-picker/import flow, and
probably its own storage of user-imported presets alongside the five
built-in ones here). It is documented here as **the next slice**, not
attempted in this one. `BUILTIN_PROFILES`'s dict shape was deliberately
kept as a plain partial adjustment-state dict so that a later "import"
feature could plausibly produce the same shape and feed it through the
same `_apply_profile`-style call path, but no import mechanism,
external file format, or extra persistence was built now.

**Other non-goals:**

- No multi-profile stacking or blending between profiles.
- No per-profile strength/amount slider (real Lightroom profiles have
  an "Amount" slider controlling how strongly the profile is applied;
  these built-in presets are all-or-nothing).
- No undo/redo command for Apply, matching `_reset_adjustments()`'s and
  `_paste_edit_settings()`'s existing precedent exactly (this codebase's
  adjustment undo/redo is already documented elsewhere as
  "image-buffer-only," an acknowledged interim implementation).
- No persistence of "which profile was last applied" across app
  restarts or image switches -- there is no such fact to persist, per
  the scope boundary above.

## 2. Current behavior (before this slice)

`ToolsPanel.set_adjustments(adjustments, emit_signal=False)` and
`ImageController.restore_adjustment_state(adjustments)` already
existed and already tolerated a **partial** dict: both only ever read
via `adjustments.get(key, default)` (confirmed by direct re-reading of
both methods in full), defaulting any omitted key to neutral. Nothing
needed to change in either method, or in
`ImageController._ADJUSTMENT_DEFAULTS`, to support a profile dict that
only specifies the keys it actually wants to change.

The full, current set of flat adjustment keys (confirmed by reading
`ImageController._ADJUSTMENT_DEFAULTS` directly, not from memory, since
new keys have been added across many prior slices this session):
`exposure`, `contrast`, `brightness`, `highlights`, `shadows`,
`whites`, `blacks`, `temperature`, `tint`, `saturation`, `vibrance`,
`texture`, `clarity`, `dehaze`, `vignette`, `grain`, `sharpening`,
`luminance_nr`, `color_nr`, `remove_ca`, `defringe`, `straighten` (plus
the three non-flat keys `tone_curve`/`hsl`/`color_grading`, not used by
any built-in profile here).

## 3. Design

### `BUILTIN_PROFILES` (`src/models/builtin_profiles.py`)

A plain `dict[str, dict]` (Python 3.7+ dicts are insertion-ordered, so
display order -- Standard first -- falls out of definition order with
no extra bookkeeping needed), mapping profile name to a **partial**
adjustment-state dict of only the keys that profile changes from
neutral. Every value was checked against that key's real valid range,
as constructed in `src/views/tools_panel.py`'s `AdjustmentSlider(...)`
calls (`ImageController` itself does not clamp; the UI-level slider
range is the real contract users experience):

- **Standard** -- `{}` (empty). Treated as equivalent to the neutral
  baseline / Reset, analogous to Adobe Standard being Lightroom's own
  neutral default profile. An empty dict was chosen over a dict that
  redundantly spells out every key at its own default, since
  `restore_adjustment_state`/`set_adjustments` already default every
  omitted key to neutral -- `{}` is shorter and makes the "this is the
  no-op profile" intent explicit at a glance.
- **Vivid** -- `contrast: +15.0`, `vibrance: +25.0`, `saturation:
  +10.0` (all well inside the shared `-100.0..100.0` range for these
  three keys). Vibrance was pushed harder than flat saturation
  deliberately: vibrance protects already-saturated colors and skin
  tones from clipping while still reading as punchier, whereas pushing
  flat saturation as hard looks garish (oversaturated, posterized skin
  tones) much sooner. +15 contrast adds visible punch without crushing
  shadow/highlight detail the way +50 or more would.
- **Monochrome** -- `saturation: -100.0` (confirmed as the Saturation
  slider's actual `min_value` in `tools_panel.py`, not assumed), plus
  `contrast: +20.0` (inside `-100.0..100.0`) for the classic "a bit more
  punch" black & white look. No new "monochrome mode" flag was
  invented; this uses only the pre-existing `saturation`/`contrast`
  keys, which is sufficient since full desaturation at -100 already
  removes all color.
- **Landscape** -- `clarity: +20.0`, `vibrance: +20.0`, `dehaze: +10.0`,
  `vignette: -15.0` (all inside `-100.0..100.0`). Clarity and vibrance
  give scenic shots local-contrast "bite" and color pop (foliage, sky)
  without the +20 values looking HDR-processed. A light +10 dehaze cuts
  atmospheric haze typical of wide landscape shots. A small *negative*
  vignette (-15, which darkens the edges per the Vignette slider's
  existing sign convention) draws the eye toward the frame's center,
  a classic landscape-grading touch, kept subtle rather than a heavy-
  handed -50+.
- **Portrait** -- `temperature: +10.0`, `shadows: +10.0`, `texture:
  -10.0`, `clarity: -5.0` (all inside `-100.0..100.0`). A small warm
  temperature shift flatters skin tones; a touch of positive shadows
  opens up shadow detail on faces without flattening the whole image; a
  small negative texture plus a smaller negative clarity softens fine
  skin detail and local contrast slightly, without going so negative
  that the image looks smeared or out of focus (a common failure mode
  of overly aggressive "portrait" presets this slice deliberately
  avoided by keeping both values small).

### `ToolsPanel` UI (`src/views/tools_panel.py`)

A new "Profile" `CollapsibleSection` (matching the same
`_create_section(...)` helper every other section already uses) is
inserted into `_setup_ui` immediately before the existing "Light"
section is created, so it sits at the very top of the scrollable
adjustments area. Its content is one row (`QHBoxLayout`): a `QComboBox`
(`self._profile_combo`), populated from `BUILTIN_PROFILES.keys()` (so
"Standard" is first, matching dict insertion order), and an "Apply"
`QPushButton` (`self._profile_apply_button`) beside it.

A new signal, `profile_apply_requested = pyqtSignal(str)`, is emitted
only from the Apply button's `clicked` handler, reading
`self._profile_combo.currentText()` at click time:

```python
self._profile_apply_button.clicked.connect(
    lambda: self.profile_apply_requested.emit(self._profile_combo.currentText())
)
```

Critically, **changing the combo selection alone connects to nothing**
-- there is no `currentTextChanged`/`currentIndexChanged` handler at
all, so idly browsing the dropdown's entries never applies anything.
Only clicking Apply emits the signal, and the signal carries just the
profile's name, not its values.

### Separation of concerns (`ToolsPanel` emits intent; `MainWindow` acts)

This follows the exact pattern already used by every other
`ToolsPanel` signal (`adjustments_changed`, `curve_changed`,
`hsl_changed`, `color_grading_changed`, `slider_released`): `ToolsPanel`
emits a signal describing *what the user asked for*, and
`MainWindow` is the one that calls into `ImageController`.
`ToolsPanel` imports `BUILTIN_PROFILES` only to populate the combo
box's list of names -- it never reads a profile's adjustment-value
dict, never calls `restore_adjustment_state` or any other
`ImageController` method, and `profile_apply_requested` carries only
the profile's `str` name, not its values. This separation is pinned by
`test_tools_panel_does_not_itself_apply_profile_values` (wraps
`set_adjustments` in a `MagicMock` and asserts it is never called when
Apply is clicked).

### `MainWindow._apply_profile` (`src/views/main_window.py`)

Wired via `self._tools_panel.profile_apply_requested.connect(self._apply_profile)`
alongside the other `ToolsPanel` signal connections:

```python
def _apply_profile(self, profile_name: str):
    if not self._image_controller.has_image():
        self._status_bar.showMessage("No image to apply a profile to", 2000)
        return
    profile_state = BUILTIN_PROFILES.get(profile_name)
    if profile_state is None:
        self._status_bar.showMessage(f"Unknown profile: {profile_name}", 2000)
        return

    state_for_tools_panel = copy.deepcopy(profile_state)
    state_for_controller = copy.deepcopy(profile_state)
    self._tools_panel.set_adjustments(state_for_tools_panel, emit_signal=False)
    self._image_controller.restore_adjustment_state(state_for_controller)
    self._adjustment_persist_timer.start()
    self._status_bar.showMessage(f"Applied profile: {profile_name}", 2000)
```

This is byte-for-byte the same shape as `_paste_edit_settings()`, with
`BUILTIN_PROFILES.get(profile_name)` standing in for the clipboard.
Per the Copy/Paste slice's own established reasoning (re-confirmed by
re-reading `set_adjustments`/`restore_adjustment_state` again for this
slice -- neither mutates its input, both only read via `.get(...)` and
build fresh dicts of their own), two independent `copy.deepcopy` calls
are used rather than one shared copy, so the stored `BUILTIN_PROFILES`
dict -- itself a second "clipboard"-like source, shared across every
image and every future Apply click in the session -- is never at risk
of being corrupted by either downstream call, now or if either
method's internals change later.

## 4. Contracts

- `src/models/builtin_profiles.py`: `BUILTIN_PROFILES: Dict[str, Dict[str, float]]`
  -- exactly five entries (`Standard`, `Vivid`, `Monochrome`,
  `Landscape`, `Portrait`), each a partial adjustment-state dict using
  only keys from `ImageController._ADJUSTMENT_DEFAULTS`, each value
  within that key's real slider range in `tools_panel.py`.
- `ToolsPanel.profile_apply_requested: pyqtSignal(str)` -- new signal,
  emitted only on the Apply button's `clicked`, carrying the combo's
  current text.
- `ToolsPanel._profile_combo: QComboBox`, `ToolsPanel._profile_apply_button:
  QPushButton` -- new attributes, exercised directly by the new tests.
- `MainWindow._apply_profile(self, profile_name: str) -> None` -- new
  method, wired to `profile_apply_requested`.
- No existing method's signature or behavior changed.
  `ImageController.get_adjustment_state()`/`restore_adjustment_state()`
  and `ToolsPanel.set_adjustments()` are used exactly as
  `_reset_adjustments()`/`_paste_edit_settings()` already used them.

## 5. Nuances and failure modes

**No image loaded.** Guarded the same way `_reset_adjustments()` and
`_paste_edit_settings()` are guarded (`has_image()`), with its own
status-bar message, so `_apply_profile` never calls into
`ImageController`/`ToolsPanel` when there is no image.

**Unknown/garbage profile name.** Handled explicitly rather than
raising: `BUILTIN_PROFILES.get(profile_name)` returning `None` (which
can only happen if `_apply_profile` is called directly with a name not
in the dict, since the combo box itself only ever offers real
`BUILTIN_PROFILES` keys) shows an `"Unknown profile: {name}"` message
and returns before touching `ImageController`/`ToolsPanel`.

**"Standard" is a full overwrite, same as Reset.** Applying "Standard"
onto an image with existing manual adjustments discards them entirely
(replaces the whole state with `{}` -> all neutral), exactly like
clicking Reset would. This is intentional and matches the "Standard"
value being deliberately empty rather than "no-op."

**Selecting without clicking Apply changes nothing.** Verified
directly: no signal is connected to the combo's own change signals, so
browsing the dropdown (even leaving it on a non-"Standard" entry and
switching to a different section) has zero effect on the image until
Apply is explicitly clicked.

**Interaction with the adjustment-persist timer.** Apply calls
`self._adjustment_persist_timer.start()` in the same place
`_reset_adjustments()`/`_paste_edit_settings()` do, so the applied
profile's state is written through to `LibraryCatalogService` on the
same debounced schedule as any other adjustment change.

**No "currently applied profile" state anywhere.** As documented in
the non-goals, nothing records which profile (if any) was last
applied. Switching images, reopening the app, or manually nudging a
slider afterward leaves no trace of which profile produced the current
starting point -- the combo box's selection is purely a pending choice
for the next Apply click, not a reflection of the image's actual
history.

## 6. Test plan

- `tests/unit/test_models/test_builtin_profiles.py` (new file; no
  `tests/unit/test_models/` directory existed to create -- it already
  held `test_adjustment_layer.py`/`test_image_model.py`/
  `test_project_model.py`, so this fits the existing layout):
  - Parses the real `min_value`/`max_value` out of every
    `AdjustmentSlider(...)` call in `src/views/tools_panel.py`'s source
    text directly (rather than hand-duplicating the numbers a second
    time, which could silently drift), and a sanity test confirms every
    slider key was actually matched.
  - Exactly five profiles with the expected names.
  - `"Standard"` is `{}`.
  - Every profile's keys are a subset of
    `ImageController._ADJUSTMENT_DEFAULTS.keys()`.
  - Every profile's values fall within that key's real, source-parsed
    range.
- `tests/unit/test_views/test_tools_panel.py` (`TestToolsPanelProfileSelector`):
  combo populated with all `BUILTIN_PROFILES` names in order (Standard
  first); selecting a different combo entry alone does not emit
  `profile_apply_requested`; clicking Apply after selecting a profile
  emits `profile_apply_requested` with the correct name; `ToolsPanel`
  never calls its own `set_adjustments` as a side effect of Apply
  (confirms the separation-of-concerns boundary, by wrapping
  `set_adjustments` in a `MagicMock` and asserting it is not called).
- `tests/ui/test_main_window.py` (`TestApplyProfile`, mirroring
  `TestCopyPasteEditSettings`'s style): no image loaded shows the
  right message and does not call `restore_adjustment_state`; an
  unknown profile name shows the right message, does not crash, and
  does not call `restore_adjustment_state`; applying a known profile
  with an image loaded calls `set_adjustments`/`restore_adjustment_state`
  once each with values equal to (but not the same object as) the
  stored `BUILTIN_PROFILES` entry, and the two call arguments are not
  the same object as each other either (two independent deepcopies);
  an end-to-end check that applying "Monochrome" actually lands the
  expected `saturation`/`contrast` values in
  `get_adjustment_state()`; a mutation-safety test (the mocked
  `restore_adjustment_state` mutates the dict it receives) confirming
  `BUILTIN_PROFILES["Vivid"]` itself is untouched afterward.

## 7. Rollout

Purely additive: one new module (`src/models/builtin_profiles.py`), one
new `ToolsPanel` section/signal, and one new `MainWindow` method plus
its wiring. No existing method's signature or behavior changed, and no
processor was added or touched. A plain revert removes the feature
entirely with no migration in either direction, since nothing new is
persisted to disk (profiles are a static, in-code dict; the result of
clicking Apply is persisted only as an ordinary adjustment-state dict,
indistinguishable from manually-set sliders, through the pre-existing
persistence path).

## 8. Implementation summary

Added `src/models/builtin_profiles.py` with `BUILTIN_PROFILES`, a
five-entry `dict[str, dict]` (Standard/Vivid/Monochrome/Landscape/Portrait),
each value checked against its key's real slider range in
`tools_panel.py`. Added a "Profile" `CollapsibleSection` to
`ToolsPanel._setup_ui` (above "Light"), containing a `QComboBox`
populated from `BUILTIN_PROFILES` and an "Apply" `QPushButton`, plus
the new `profile_apply_requested = pyqtSignal(str)` emitted only from
the Apply button's `clicked`. Added `MainWindow._apply_profile(name)`,
wired to that signal, which mirrors `_paste_edit_settings()`'s exact
`set_adjustments(...)` / `restore_adjustment_state(...)` /
`_adjustment_persist_timer.start()` pattern with two independent
`copy.deepcopy`s of the looked-up `BUILTIN_PROFILES` entry.

No changes were made to any processor, `ImageController`'s core
adjustment pipeline, or `ToolsPanel.set_adjustments`/
`ImageController.restore_adjustment_state` themselves -- this feature
composes existing adjustment keys into named preset dicts and applies
them through the existing whole-state-apply mechanism, exactly as
scoped.

**Deviation note.** None of substance. One naming choice worth calling
out: `"Standard"`'s dict is empty (`{}`) rather than a dict that
explicitly repeats every key at its default value -- documented above
as a deliberate choice (shorter, and makes the "no-op profile" intent
explicit) rather than an oversight.

Verification: new tests -- `tests/unit/test_models/test_builtin_profiles.py`
**13 passed**, `TestToolsPanelProfileSelector` in
`tests/unit/test_views/test_tools_panel.py` **4 passed**,
`TestApplyProfile` in `tests/ui/test_main_window.py` **5 passed** (22
new tests total); complete suite run via
`QT_QPA_PLATFORM=offscreen python3 -m pytest -q --deselect tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::test_geometry_is_restored_on_next_launch`
**920 passed, 1 skipped, 1 deselected in 125.33s** (898 pre-existing +
22 new; the deselected test is the same pre-existing
offscreen-rendering flake noted in prior implementation notes,
unrelated to this slice; the 1 skipped test is pre-existing and
unrelated to this work). No other failures or flakes observed. A live
GUI smoke test (actually clicking the Profile combo/Apply button in
the real running app) was not performed in this non-interactive
environment; the behavior is instead pinned at the `ToolsPanel`- and
`MainWindow`-level unit tests above.
