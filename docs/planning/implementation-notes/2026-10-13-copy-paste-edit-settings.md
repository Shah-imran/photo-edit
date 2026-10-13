# Copy/Paste Edit Settings between images

Related roadmap: Phase B, "Edit/File workflow and preferences MVP" in
`docs/planning/PRODUCT_ROADMAP.md` ("Copy/Paste edit settings between
images (requires serializable adjustment dict; feeds Phase K)."). Like
Export with Previous, this is menu/controller plumbing, not an image
processor slice, so this note follows that adapted section structure
rather than the processor template.

## 1. Problem, goal, and non-goals

**Problem.** There was no way to apply one image's complete adjustment
state to a different image without manually re-creating every slider,
tone-curve, HSL, and Color Grading value by hand. Lightroom's actual
"Copy Edit Settings" / "Paste Edit Settings" solves this with a
single-slot, in-session clipboard of the full adjustment state.

**Goal.** Add `MainWindow._copy_edit_settings()` and
`MainWindow._paste_edit_settings()`, wired to new Edit-menu actions
(`Ctrl+Alt+C` / `Ctrl+Alt+V`), that copy the current image's
`ImageController.get_adjustment_state()` dict into a single in-memory
slot and, on paste, replace the current image's entire adjustment
state with it -- reusing the exact `set_adjustments({}, ...)` /
`restore_adjustment_state({})` pattern `_reset_adjustments()` already
uses, but with the copied dict instead of `{}`.

**Non-goals:**

- No multi-slot clipboard history. This is a single slot, matching
  Lightroom's own Copy/Paste Edit Settings semantics, not its separate
  named-preset system (which supports many saved, named
  configurations).
- No "paste settings onto multiple selected images at once" batch
  behavior. This codebase's library grid/filmstrip has no multi-select
  to batch-apply to in the first place, so there is nothing to wire
  this feature into even if batch semantics were in scope.
- No persistence of the copied state across app restarts. The
  clipboard is purely in-memory (`MainWindow._copied_adjustment_state`)
  and is lost when the app closes, matching Lightroom's own
  session-scoped behavior for this specific feature, as opposed to its
  separate named-preset feature which *does* persist to disk.
- No undo/redo command for Paste. `_reset_adjustments()` does not push
  one either; the Phase B roadmap explicitly documents this codebase's
  adjustment Undo/Redo as "image-buffer-only" and an "acknowledged
  interim implementation," so matching the existing Reset precedent
  exactly is the right call here, not a regression to fix in this
  slice.

## 2. Current behavior (before this slice)

`ImageController.get_adjustment_state()` already returned a complete,
JSON-plain snapshot of every adjustment (the eleven flat float keys,
plus `tone_curve`, `hsl`, and `color_grading`), and
`restore_adjustment_state(state)` already applied any such dict back
onto the current image, re-processing from the original and resetting
history -- this is the exact dict shape `LibraryCatalogService`
already persists per-image to disk (`get_entry_adjustment_state` /
`set_entry_adjustment_state`), confirming it was already treated
elsewhere in this codebase as a portable, self-contained snapshot.
`MainWindow._reset_adjustments()` already demonstrated the "replace
the current image's entire adjustment state" call pair:

```python
self._tools_panel.set_adjustments({}, emit_signal=False)
self._image_controller.restore_adjustment_state({})
self._adjustment_persist_timer.start()
```

What was missing was simply a way to capture that state into something
other than `{}` (the hardcoded "defaults" case) and a way to feed a
captured snapshot back through the same call pair. Nothing needed
changing in `get_adjustment_state()`, `restore_adjustment_state()`, or
`ToolsPanel.set_adjustments()` themselves.

## 3. Design

### Clipboard storage

`MainWindow.__init__` adds one new instance attribute, next to the
other simple in-session-only state already initialized there
(`_pending_library_add_path`, `_current_image_library_id`, etc.):

```python
self._copied_adjustment_state: Optional[dict] = None
```

### `_copy_edit_settings()`

```python
def _copy_edit_settings(self):
    if self._image_controller.has_image():
        self._copied_adjustment_state = self._image_controller.get_adjustment_state()
        self._status_bar.showMessage("Copied edit settings", 2000)
    else:
        self._status_bar.showMessage("No image to copy edit settings from", 2000)
```

### `_paste_edit_settings()`

```python
def _paste_edit_settings(self):
    if not self._image_controller.has_image():
        self._status_bar.showMessage("No image to paste edit settings to", 2000)
        return
    if self._copied_adjustment_state is None:
        self._status_bar.showMessage(
            "Nothing to paste; copy edit settings first", 2000
        )
        return

    state_for_tools_panel = copy.deepcopy(self._copied_adjustment_state)
    state_for_controller = copy.deepcopy(self._copied_adjustment_state)
    self._tools_panel.set_adjustments(state_for_tools_panel, emit_signal=False)
    self._image_controller.restore_adjustment_state(state_for_controller)
    self._adjustment_persist_timer.start()
    self._status_bar.showMessage("Pasted edit settings", 2000)
```

### Mutation-safety decision, and what was actually found

The spec called for checking, rather than assuming, whether
`ToolsPanel.set_adjustments` or `ImageController.restore_adjustment_state`
mutate the dict they are given. Reading both in full:

- `ToolsPanel.set_adjustments(adjustments, ...)` only ever calls
  `adjustments.get(key, default)` (for the 21 flat keys, plus
  `tone_curve`/`hsl`/`color_grading`) and builds its own fresh `merged`
  dict and fresh `hsl_values`/`color_grading_values` dicts (seeded from
  `default_hsl_params()` / `default_color_grading_params()`). It never
  assigns into `adjustments` or any of its nested values. **It does not
  mutate its input.**
- `ImageController.restore_adjustment_state(adjustments)` similarly
  only reads via `self._normalize_adjustment_state(adjustments)` and
  `adjustments.get("tone_curve"/"hsl"/"color_grading")`, passing the
  results into `normalize_points(...)` (which builds a new tuple) and
  its own `_normalize_hsl_state`/`_normalize_color_grading_state`
  helpers (each builds a fresh dict from its own defaults dict). It
  never writes back into the `adjustments` dict or any nested
  structure it was given. **It does not mutate its input either.**

So, as of this slice, neither downstream call actually needs the
defensive copy to stay correct today. The spec's requirement to pass a
copy anyway was followed exactly as written: `copy.deepcopy` is used
(rather than a shallow `dict(...)`) because `get_adjustment_state()`'s
return value nests a mutable list of `[x, y]` point-lists under
`"tone_curve"` and two nested flat dicts under `"hsl"` /
`"color_grading"` -- a shallow copy would still share those nested
objects with the stored clipboard. Two independent `deepcopy` calls
are made (one for each downstream call) rather than one shared copy,
so that even if a future change made one of the two calls mutate its
argument, it could never corrupt what the *other* call receives in the
same paste, in addition to never corrupting the stored clipboard. This
is cheap insurance against a currently-nonexistent risk, documented
here explicitly so a future change to either method's internals does
not silently reintroduce a clipboard-corruption bug without this
analysis being redone.

### Menu wiring

Added to `_setup_menu_bar()`, right after the existing
`"&Reset Adjustments"` action:

```python
edit_menu.addAction(
    self._create_action(
        "&Copy Edit Settings", self._copy_edit_settings, "Ctrl+Alt+C"
    )
)
edit_menu.addAction(
    self._create_action(
        "&Paste Edit Settings", self._paste_edit_settings, "Ctrl+Alt+V"
    )
)
```

`Ctrl+Alt+C` / `Ctrl+Alt+V` (Lightroom's own Windows convention for
this exact feature) were checked against every other shortcut
registered in `_setup_menu_bar` (`Ctrl+O`, `Ctrl+Shift+O`, `Ctrl+E`,
`Ctrl+Shift+E`, `Ctrl+Q`, `Ctrl+Z`, `Ctrl+Shift+Z`, `Ctrl+R`, `0`, `1`,
`Ctrl+=`, `Ctrl+-`, `F5`, `F6`) via `grep`; no collision found, so they
were used as-is.

## 4. Contracts

- `MainWindow._copied_adjustment_state: Optional[dict]` -- new instance
  attribute, the single clipboard slot. `None` means "nothing copied
  yet."
- `MainWindow._copy_edit_settings(self) -> None` -- new method, wired
  to the new "&Copy Edit Settings" (`Ctrl+Alt+C`) Edit menu action.
- `MainWindow._paste_edit_settings(self) -> None` -- new method, wired
  to the new "&Paste Edit Settings" (`Ctrl+Alt+V`) Edit menu action.
- No existing method's signature or behavior changed.
  `ImageController.get_adjustment_state()` /
  `restore_adjustment_state()` and `ToolsPanel.set_adjustments()` are
  used exactly as `_reset_adjustments()` already used two of them, with
  no modification.

## 5. Nuances and failure modes

**Paste before any copy.** Handled explicitly (`"Nothing to paste;
copy edit settings first"`) rather than silently resetting to defaults
or doing nothing -- a user pressing `Ctrl+Alt+V` with an empty
clipboard gets clear feedback rather than ambiguity about whether
anything happened.

**Copy/Paste with no image loaded.** Both guarded the same way
`_reset_adjustments()` is guarded (`has_image()`), each with its own
status-bar message, so neither method ever calls into
`ImageController`/`ToolsPanel` when there is no image to act on.

**Clipboard survives switching images, by design.** Since
`_copied_adjustment_state` lives on `MainWindow` (not on
`ImageController`, which clears its own per-image params on every
image load/switch), copying from image A and then switching the active
image to B still leaves A's state in the clipboard, ready to paste
onto B -- this is the entire point of the feature and is explicitly
exercised by the cross-image test below.

**Clipboard is not cleared by Paste.** Pasting does not clear
`_copied_adjustment_state`, matching Lightroom's own behavior of
allowing the same copied settings to be pasted onto any number of
further images in the same session.

**Interaction with the adjustment-persist timer.** Paste calls
`self._adjustment_persist_timer.start()` exactly where
`_reset_adjustments()` does, so the pasted state is written through to
`LibraryCatalogService` on the same debounced schedule as every other
adjustment change, and survives a library reload.

## 6. Test plan

New `TestCopyPasteEditSettings` class added to
`tests/ui/test_main_window.py` (alongside its existing `main_window`
fixture and the file's other adjustment-state coverage, e.g.
`test_switching_images_restores_tonal_sliders_and_curve`, as the
closest sibling behavior):

- Copy with no image loaded shows the "No image to copy..." message
  and leaves `_copied_adjustment_state` as `None`.
- Copy with an image loaded captures `get_adjustment_state()`'s current
  return value.
- Paste with no image loaded shows the "No image to paste..." message
  and does not call `restore_adjustment_state`.
- Paste with an image loaded but nothing copied shows the "Nothing to
  paste..." message and does not call `restore_adjustment_state`.
- Paste with both an image and a prior copy asserts
  `set_adjustments`/`restore_adjustment_state` were each called once
  with a dict equal to the copied state's values but not the same
  object as `_copied_adjustment_state` (and not the same object as
  each other), pinning the two-independent-deepcopy behavior.
- A copy-then-paste-then-mutate test: the test's `restore_adjustment_state`
  mock mutates the dict it receives (simulating a careless downstream
  caller) and asserts `_copied_adjustment_state` itself is unaffected
  -- the direct mutation-safety regression test.
- A cross-image test: copies image A's state (with a non-default
  `highlights` value) via the real library/filmstrip image-switching
  flow already used elsewhere in this file, switches the active image
  to image B (which starts from a clean default state), pastes, and
  confirms the `restore_adjustment_state` call received image A's
  captured `highlights` value, not image B's defaults -- confirming
  copy/paste actually crosses between different images rather than
  being a same-image round-trip.

## 7. Rollout

Purely additive: one new `MainWindow` instance attribute, two new
`MainWindow` methods, and two new Edit-menu actions. No existing
method signature or behavior changed, and no processor, `ToolsPanel`
internals (beyond its pre-existing `set_adjustments`), or
`ImageController` adjustment-pipeline internals were touched. A plain
revert removes the feature entirely with no migration in either
direction, since nothing is persisted to disk.

## 8. Implementation summary

Added `MainWindow._copied_adjustment_state: Optional[dict] = None`
(`src/views/main_window.py`, initialized in `__init__` alongside the
other simple session-only instance attributes), plus
`_copy_edit_settings()` and `_paste_edit_settings()`, wired to two new
Edit-menu actions ("&Copy Edit Settings" / "&Paste Edit Settings",
`Ctrl+Alt+C` / `Ctrl+Alt+V`) added right after the existing "&Reset
Adjustments" action. `_paste_edit_settings()` mirrors
`_reset_adjustments()`'s exact `set_adjustments(...)` /
`restore_adjustment_state(...)` /
`_adjustment_persist_timer.start()` pattern, passing two independent
`copy.deepcopy`s of the stored clipboard dict rather than the stored
dict itself or a shared copy. By direct inspection, neither
`ToolsPanel.set_adjustments` nor `ImageController.restore_adjustment_state`
currently mutates the dict it is given (both only read via `.get(...)`
and build fresh dicts/tuples of their own) -- the defensive deep-copy
was implemented anyway per spec, as cheap insurance against either
method's internals changing in the future.

No changes were made to any processor, `ProcessingQueue`/`Worker`,
`CombinedAdjustmentCommand`, or any Texture/Clarity/.../Straighten
processor math -- this feature is entirely contained in
`main_window.py`, as scoped.

**Deviation note.** None of substance. `copy.deepcopy` was used (per
the spec's own guidance, since `tone_curve`/`hsl`/`color_grading` nest
mutable lists/dicts) with two independent calls, one per downstream
callee, rather than one shared copy passed to both -- a stricter
reading of "don't let either call corrupt anything else" than a single
shared copy would have given, and documented above as a deliberate
choice rather than an oversight.

Verification: new tests (`TestCopyPasteEditSettings` in
`tests/ui/test_main_window.py`) **7 passed**; complete suite run via
`QT_QPA_PLATFORM=offscreen python3 -m pytest -q --deselect tests/ui/test_main_window.py::TestMainWindowSettingsPersistence::test_geometry_is_restored_on_next_launch`
**879 passed, 1 skipped, 1 deselected in 122.50s** (872 pre-existing +
7 new; the deselected test is the same pre-existing
offscreen-rendering flake noted in prior implementation notes,
unrelated to this slice; the 1 skipped test is pre-existing and
unrelated to this work). No other failures or flakes observed. A live
GUI smoke test (actually pressing `Ctrl+Alt+C`/`Ctrl+Alt+V` in the real
running app) was not performed in this non-interactive environment;
the behavior is instead pinned at the `MainWindow` unit-test level,
including through the real library/filmstrip image-switching path for
the cross-image test.
