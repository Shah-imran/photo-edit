# State-aware undo/redo

Related roadmap: Phase B, the "Complete state-aware Undo/Redo" bullet in
`docs/planning/PRODUCT_ROADMAP.md`, and the "Coverage vs current
PhotoEdit" table's PDF row 2 ("History/Undo/Redo"). The roadmap bullet,
verbatim:

> Complete state-aware Undo/Redo: each history entry must retain
> before/after adjustment payloads as well as rendered results; undo and
> redo must atomically synchronize controller parameters, all
> sliders/curve controls, displayed image, export output, and persisted
> per-image state. The current image-buffer-only history is an
> acknowledged interim implementation.

## 1. Problem

`ImageController.undo()`/`redo()` called `HistoryService.undo()/redo()`,
which just calls a `Command`'s `undo()`/`execute()`. The two command
classes actually pushed onto the undo/redo stack
(`CombinedAdjustmentCommand` and `ImageStateChangeCommand`, in
`src/commands/adjustment_commands.py`) only swapped
`ImageModel.current_image` between a `previous_image`/`new_image` pixel
buffer. Neither:

1. Updated `ImageController`'s own ~18 internal per-category parameter
   dicts (`self._exposure_params`, `self._tonal_params`, ... plus
   `self._curve_params`, `self._hsl_params`, `self._color_grading_params`)
   -- so after an undo, touching any slider again recomputed the live
   pipeline from the STALE pre-undo params, producing a wrong result or a
   jarring snap-back on the next edit.
2. Notified the UI (`ToolsPanel`'s sliders/curve editor/HSL mixer/Color
   Grading panel) to resync -- so after an undo, the sliders visually
   still showed the pre-undo values even though the displayed image had
   reverted.
3. Re-persisted the (now-reverted) adjustment state to the library
   catalog -- so `get_adjustment_state()`/export/the persisted catalog
   entry all still reflected the pre-undo values after an undo.

## 2. Goal / non-goals

**Goal.** Undo and redo atomically restore the full (image,
adjustment-state) pair: controller params, all sliders/curve/HSL/Color
Grading UI, the displayed image, export output (which recomputes from
`_xxx_params`, so fixing (1) fixes export for free), and the persisted
per-image catalog state (via the same `_adjustment_persist_timer`
Paste/Profile/Reset already use).

**Non-goals.**

- Paste Edit Settings, Profile apply, and preset import remain NOT
  individually undoable. They still call `restore_adjustment_state()`,
  which still clears history by design -- a deliberate, separate scope
  boundary this slice does not touch.
- No change to `CombinedAdjustmentCommand`'s or `ImageStateChangeCommand`'s
  own public behavior as standalone classes. Only what `ImageController`
  pushes onto the undo/redo stack changed.
- No new processor, no new persisted-state shape. `get_adjustment_state()`
  already fully describes an image's adjustments; this slice reuses that
  shape as the undo/redo payload rather than inventing a new one.

## 3. Design

### 3.1 Capturing a "previous state" snapshot, not just a "previous image"

`ImageController` already had the pattern of capturing a
`_pending_history_previous_image` once per edit gesture, at the top of
five entry points (`apply_adjustments`, `on_adjustments_changed`,
`on_curve_changed`, `on_hsl_changed`, `on_color_grading_changed`),
*before* that method's own param-storing code ran later in the same
call. That ordering is exactly what makes capturing the "before" state
correct: `get_adjustment_state()` reads live from `self._xxx_params`, so
calling it at that exact point captures the state as it was immediately
before the gesture.

All five identical 4-line blocks were replaced with a call to one new
method, `_capture_pending_history_state()`, which now also snapshots
`self._pending_history_previous_state = self.get_adjustment_state()`
alongside the image. A new `self._pending_history_previous_state` field
is cleared in lockstep with `_pending_history_previous_image` everywhere
the latter was already being cleared: `__init__`, `_apply_loaded_image`,
`restore_adjustment_state`, `reset_to_original`,
`_submit_delayed_final_render` (the "no pending changes" early return),
and `_commit_rendered_adjustment`.

### 3.2 `_apply_state_params` -- extracting the pure param-assignment logic

`restore_adjustment_state` had two phases: (a) normalize an incoming
adjustment dict and assign it to all 18 `self._xxx_params` fields, and
(b) history-clearing, cancelling pending work, and recomputing-or-resetting
the image. Phase (a) was extracted verbatim into a new method,
`_apply_state_params(adjustments) -> Dict[str, Any]`, which does nothing
but the normalization + assignment and returns
`{"normalized", "curve_points", "hsl_values", "color_grading_values"}` so
callers that need to reason about "are there non-default changes" (as
`restore_adjustment_state` does, for its reset-to-original fast path)
don't have to recompute them. `restore_adjustment_state` now calls this
helper and uses its returned pieces instead of duplicating the logic.

**Behavior-preservation checkpoint.** This refactor was done first, in
isolation, before any other change in this slice, specifically so it
could be verified safe on its own: the full suite was run immediately
after it (before the signal, the new command, or the two history-push
sites were touched) and passed with the same count as the untouched
baseline. Only after that did the rest of the slice proceed.

### 3.3 `apply_history_state` and the `adjustment_state_restored` signal

A new method, `ImageController.apply_history_state(image, state)`:

```python
def apply_history_state(self, image, state: Dict[str, Any]) -> None:
    self._image_model.current_image = image
    self._apply_state_params(state)
    self.adjustment_state_restored.emit(self.get_adjustment_state())
```

Unlike `restore_adjustment_state` (which clears history and may
recompute from the original image), this keeps history intact, reuses an
already-rendered image buffer (no reprocessing -- undo/redo must stay
cheap), and is the only place that emits the new
`adjustment_state_restored = pyqtSignal(dict)` signal.

**Deliberately does not call `refresh_view()` itself** -- see section 5
for why, and what calls it instead.

It is named without a leading underscore, and documented as an
intentional internal API: `AdjustmentStateCommand`, in a different
module (`src/commands/adjustment_commands.py`), calls it directly.
`image_controller.py` already imports *from* `adjustment_commands.py`,
so a top-level import the other way would be circular; the type hint on
`AdjustmentStateCommand.__init__`'s `controller` parameter is a string
(`"ImageController"`) under `TYPE_CHECKING` instead.

### 3.4 `AdjustmentStateCommand`

A new command class, also in `adjustment_commands.py`:

```python
class AdjustmentStateCommand(BaseCommand):
    def __init__(self, controller, previous_image, previous_state, new_image, new_state):
        ...
    def execute(self):
        super().execute()
        self._controller.apply_history_state(self._new_image, self._new_state)
    def undo(self):
        super().undo()
        self._controller.apply_history_state(self._previous_image, self._previous_state)
```

`CombinedAdjustmentCommand` and `ImageStateChangeCommand` are kept,
unused by the real undo/redo flow but still present and still exercised
by their own direct unit tests -- a deliberate choice to minimize
unrelated test churn and risk. `CombinedAdjustmentCommand`'s
pixel-computation chain is still reused directly (see 3.5); its own
standalone tests (and `ImageStateChangeCommand`'s, though it turned out
to have none) remain valid tests of what those classes still do when
used directly, independent of what `ImageController` now pushes onto
`history_service`.

### 3.5 Wiring `AdjustmentStateCommand` into history-push sites

There turned out to be **three** places `ImageController` pushes a
command onto `history_service`, not the two originally identified --
`commit_adjustments()` (used by `on_slider_released()`'s synchronous
fallback for non-threaded callers/tests) was a third. All three were
converted:

- **`_commit_rendered_adjustment`** (threaded final-render commit): uses
  the paired `_pending_history_previous_image` /
  `_pending_history_previous_state` captured earlier in the gesture as
  "previous", and `self.get_adjustment_state()` (the params are already
  current by this point) as "new".
- **`apply_adjustments`'s synchronous `add_to_history` branch**: builds
  `CombinedAdjustmentCommand` exactly as before and calls `.execute()`
  directly (NOT via `history_service.execute_command`, so it never itself
  lands on the stack), reusing its existing pixel-computation chain
  without reimplementing it, then builds and pushes an
  `AdjustmentStateCommand` using the pending previous image/state and the
  just-computed image/state. This avoids double-computing pixels (the
  expensive part) while still getting a state-aware command onto the
  real stack.
- **`commit_adjustments()`** (not in the original design, found during
  implementation): converted the same way as the `apply_adjustments`
  branch above -- `CombinedAdjustmentCommand.execute()` directly, then an
  `AdjustmentStateCommand` push using the pending previous image/state.
  It also calls `_capture_pending_history_state()` itself at the top
  (idempotent -- a no-op if `on_adjustments_changed`/`on_curve_changed`/
  `on_hsl_changed`/`on_color_grading_changed` already captured it earlier
  in the same gesture, which is the normal case since this method is only
  ever reached after one of those), so a direct call to
  `commit_adjustments()` still gets a correct "previous" pair rather than
  silently pushing no history at all.

### 3.6 `MainWindow` wiring

`self._image_controller.adjustment_state_restored.connect(self._on_adjustment_state_restored)`,
alongside the controller's other signal connections. The handler mirrors
`_reset_adjustments`/`_paste_edit_settings`/`_apply_profile`'s exact
pattern:

```python
def _on_adjustment_state_restored(self, state: dict) -> None:
    self._tools_panel.set_adjustments(state, emit_signal=False)
    self._adjustment_persist_timer.start()
```

## 4. Contracts

- `ImageController.apply_history_state(image, state)`: internal API,
  callable by `AdjustmentStateCommand` only. Sets `image_model.current_image`,
  re-applies every `_xxx_params` field from `state` (same shape as
  `get_adjustment_state()`), and emits `adjustment_state_restored` with
  the resulting normalized state. Does not touch history, pending
  processing state, or repaint the view.
- `ImageController.adjustment_state_restored = pyqtSignal(dict)`: emitted
  every time `apply_history_state` runs -- on undo, on redo, and on an
  ordinary adjustment commit (since the commit path also pushes an
  `AdjustmentStateCommand`, whose `execute()` calls `apply_history_state`
  too). Listeners must tolerate being called on a normal commit, not only
  on undo/redo.
- `ImageController._apply_state_params(adjustments) -> dict`: pure
  bookkeeping, no `image_model`/history/pending-state side effects.
  Shared by `restore_adjustment_state` and `apply_history_state`.
- `ImageController.undo()`/`redo()`: unchanged signatures and return
  values; still call `refresh_view()` themselves after a successful
  `history_service.undo()/redo()`.

## 5. Nuances and failure modes

**`adjustment_state_restored` fires on every normal commit, not just
undo/redo.** Because the commit paths now also push an
`AdjustmentStateCommand`, `execute()` runs on the initial push too (not
only on a later `redo()`), so the signal fires then as well. This was
anticipated as "probably harmless" in the design and was verified
empirically rather than assumed: `MainWindow._on_adjustment_state_restored`
just resyncs the ToolsPanel to values it already has and restarts the
(debounced, 400ms) persist timer, which is a no-op in effect. No guard
was added.

**`refresh_view()` is deliberately NOT called from `apply_history_state`.**
An existing test,
`test_pending_final_render_does_not_refresh_full_res_view`, pins a real
performance optimization: the threaded final-render commit path
(`_on_processing_complete` / `_commit_rendered_adjustment`) must not
trigger an extra view repaint, because the canvas is already showing the
right pixels by the time the full-resolution render lands. If
`apply_history_state` called `refresh_view()` unconditionally, every
normal commit through `AdjustmentStateCommand.execute()` would violate
that invariant. Instead, `apply_history_state` only sets state; the
callers that need a repaint call `refresh_view()` themselves --
`ImageController.undo()`/`redo()` still do, exactly as before this slice
(previously this looked redundant with a hypothetical refresh inside the
command; it turned out NOT to be redundant once `apply_history_state`
itself stayed silent, so both calls were kept as-is). The commit paths
(`apply_adjustments`, `commit_adjustments`) already call `refresh_view()`
themselves at their own end, unconditionally, so this is also still
correct for them.

**A third history-push site existed beyond the two originally named**
(`commit_adjustments()`) -- see 3.5. Missing it would have left the
`on_slider_released()` synchronous fallback (used by non-threaded
callers, which is most of this project's own test suite) still only
pixel-buffer-undoable.

## 6. Test plan

**The core regression test**
(`test_undo_restores_adjustment_state_not_just_image`, in
`tests/unit/test_controllers/test_image_controller.py`): with threading
disabled, apply `exposure=1.0` then `exposure=2.0` via
`apply_adjustments(..., add_to_history=True)`, then `undo()`. Asserts
`get_adjustment_state()["exposure"] == 1.0`, not `2.0` -- which is
exactly what the old image-buffer-only undo would have left stale. This
is the single most important assertion added in this slice; it failed
against the pre-fix code path.

Other new controller-level tests, same file, class
`TestImageControllerStateAwareUndoRedo`:
- `test_live_pipeline_builds_on_undone_state_not_stale_params`: after
  undo, applies a third, independent adjustment and confirms the result
  reflects "exposure=1.0 baseline + contrast=5.0" (computed independently
  via the exposure processor) rather than "exposure=2.0 baseline +
  contrast=5.0" -- confirms the live pipeline really builds on the
  restored state.
- `test_redo_restores_image_and_state_to_pre_undo_values`: redo after
  undo restores both the image and `get_adjustment_state()`.
- `test_adjustment_state_restored_emitted_on_undo` /
  `_on_redo`: uses `qtbot.waitSignal` to confirm the signal fires with
  the correct state on both.
- `test_curve_undo_restores_full_curve_state`,
  `test_hsl_undo_restores_full_hsl_state`,
  `test_color_grading_undo_restores_full_color_grading_state`: one test
  per non-flat-dict category, each via `on_curve_changed`/`on_hsl_changed`/
  `on_color_grading_changed` + `commit_adjustments()` (the synchronous
  fallback path), confirming each restores its own full state on undo.
- `test_restore_adjustment_state_clears_pending_history_state`,
  `test_reset_to_original_clears_pending_history_state`,
  `test_loading_a_different_image_clears_pending_history_state`: confirm
  `_pending_history_previous_state` clears alongside
  `_pending_history_previous_image` in all three places.

New command-level tests, `tests/unit/test_commands/test_adjustment_commands.py`,
class `TestAdjustmentStateCommand`: `execute()` calls
`controller.apply_history_state(new_image, new_state)` (mocked
controller, asserted call); `undo()` calls it with the previous pair;
`redo()` after `undo()` calls it with the new pair again;
`undo()` before `execute()` and a second `execute()` both raise
`RuntimeError` (inherited `BaseCommand` behavior).

New UI-level test, `tests/ui/test_adjustment_workflow.py`,
`TestTonalSliderWorkflow::test_undo_resyncs_slider_widgets_not_just_image`:
drives the real highlights slider widget through two edit gestures
(`set_value` + `on_slider_released`, matching the file's existing
pattern), then asserts that after `undo()` the **slider widget itself**
reports the pre-second-edit value, not just the controller's internal
state -- the UI-sync half of the bug that a controller-only test cannot
catch.

## 7. Rollout

Two existing controller tests had to be updated because they manually
set `controller._pending_history_previous_image` to simulate the capture
step without going through the real capture flow, and the new code path
now also requires `_pending_history_previous_state` to be present before
`_commit_rendered_adjustment` will push a command:

- `test_threaded_final_render_commits_history_without_reprocessing`
- `test_pending_final_render_does_not_refresh_full_res_view`

Both were updated to also set
`controller._pending_history_previous_state = controller.get_adjustment_state()`
right alongside the existing `_pending_history_previous_image` assignment,
replicating what the real `_capture_pending_history_state()` flow does.
Neither test's actual assertions changed -- no test was weakened or had
an assertion removed; both were pinning the mechanism's precondition, not
the buggy undo behavior itself, and both continue to assert the same
things they did before.

No other existing test asserted the old buggy (image-buffer-only) undo
behavior, so no assertions elsewhere needed to change.

## 8. Implementation summary

Files changed:

- `src/controllers/image_controller.py`: `_pending_history_previous_state`
  field; `_capture_pending_history_state()` (replacing 5 duplicated
  blocks); `_apply_state_params()` (extracted from
  `restore_adjustment_state`); `apply_history_state()`;
  `adjustment_state_restored` signal; `_commit_rendered_adjustment`,
  `apply_adjustments`, and `commit_adjustments` converted to push
  `AdjustmentStateCommand`.
- `src/commands/adjustment_commands.py`: new `AdjustmentStateCommand`
  class; `TYPE_CHECKING` import of `ImageController` for the type hint.
- `src/views/main_window.py`: `adjustment_state_restored` connection;
  `_on_adjustment_state_restored` handler.
- `tests/unit/test_controllers/test_image_controller.py`: new
  `TestImageControllerStateAwareUndoRedo` class (11 tests); two existing
  tests updated per section 7.
- `tests/unit/test_commands/test_adjustment_commands.py`: new
  `TestAdjustmentStateCommand` class (4 tests).
- `tests/ui/test_adjustment_workflow.py`: one new test,
  `test_undo_resyncs_slider_widgets_not_just_image`.

Full suite (`QT_QPA_PLATFORM=offscreen python3 -m pytest -q --deselect
tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::test_geometry_is_restored_on_next_launch`):
baseline (before this slice) 1024 passed, 1 skipped, 1 deselected; after
this slice, 1040 passed, 1 skipped, 1 deselected -- the 16 new tests, no
regressions.
