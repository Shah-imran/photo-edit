# Healing tool UI (interactive overlay), slice 2 of 2

Related roadmap: Phase J ("Healing and Masking", PDF sections 21-22),
`docs/planning/PRODUCT_ROADMAP.md`'s Healing bullet. Related prior
slice: `docs/planning/implementation-notes/2026-10-13-healing-processor.md`,
which built the entire data/processing layer this slice drives through
its one public entry point, `ImageController.on_heal_spots_changed(heal_spots)`.
Direct architectural templates, reused as heavily as possible: the Crop
and Mask tool UI slices --
`docs/planning/implementation-notes/2026-10-13-crop-tool-ui.md` (the
overlay/toolbar/`ImageView`/`MainWindow` wiring structure and the
canvas-matching coordinate-math property) and
`docs/planning/implementation-notes/2026-10-13-mask-tool-ui.md`
(critically, the live-preview-while-editing design --
`ImageController.preview_mask`/`get_export_image`'s `mask_override`
parameter -- reused here as `preview_heal_spots`/`heal_spots_override`).

## 1. Problem, goal, and non-goals

This is **slice 2 of 2**. Slice 1 built `HealingProcessor`, full
pipeline/undo-redo/export wiring, and a programmatic
`ImageController.on_heal_spots_changed(heal_spots: list)` API, but
explicitly left unbuilt: the interactive click-and-drag placement UI and
a basic "visualize spots" overlay, plus the disabled "Heal" placeholder
in `EditingToolStrip`. This slice builds exactly that -- a new overlay
plus a new toolbar plus the `ImageView`/`EditingToolStrip`/`MainWindow`
wiring to drive `on_heal_spots_changed` -- and touches no processor code,
and only one small, additive controller change
(`get_export_image`'s new `heal_spots_override` parameter, plus a new
`preview_heal_spots` method, mirroring the Mask slice's own
`mask_override`/`preview_mask` pattern exactly -- see section 3.2).

**Non-goals (explicitly out of scope for this v1, stated plainly rather
than left as an implicit oversight):**

- **Click-and-drag placement ONLY -- no post-placement selection or
  per-spot editing.** Press sets a spot's destination center; dragging
  before release grows/shrinks its radius live; release commits it.
  There is NO way to click an already-placed spot afterward to select,
  move, resize, or edit it individually in this v1 -- only "Remove Last"
  (undo the most recent placement) and "Clear All" (empty the whole
  in-progress list) are provided as correction mechanisms. This is a
  real, deliberate scope limit, not an oversight.
- **The source point is always auto-offset from the destination, never
  separately draggable.** A fixed rule: offset directly to the right by
  `2 * radius`, unless that would push the source circle (even
  partially) outside the image, in which case flip to directly the LEFT
  by the same amount; if a destination spot is wide enough that NEITHER
  side fits (wider than half the image), the offset is clamped to
  whatever keeps the source maximally in-bounds rather than crashing or
  producing an out-of-`[0,1]` source. See section 3.3's
  `_compute_source_offset` for the exact logic and section 6's edge-case
  test. No UI control overrides this. A later, separate slice could add
  draggable source points.
- **The toolbar's Mode/Feather/Opacity apply to the NEXT spot placed
  only, never retroactively to an already-placed spot.** There is no
  per-spot editing in this v1 (see above), so this is the only sensible
  meaning those controls can have. Each placed spot BAKES IN whatever
  the toolbar's pending values were at the moment of its OWN placement
  (not a live reference to a shared value) -- see section 3.3 and the
  dedicated test in section 6 that proves this directly, not just
  asserts it.
- **No toolbar "radius" control.** Radius is determined entirely by the
  drag gesture (press = center, drag distance = radius, clamped to a
  sensible `[0.01, 0.5]` normalized-fraction range) -- never by a
  toolbar default. A plain click with no drag still places a spot, at a
  small fixed default radius.
- **Spot visualization is deliberately basic ("simplified"), per the
  roadmap bullet's own qualifier.** A small circle outline at the
  destination, a smaller circle outline at the auto-computed source, and
  a thin connecting line between them, for every spot in the
  in-progress list (plus the actively-dragging spot, shown dashed) --
  not an elaborate overlay.
- **No multi-mask-stack-style add/select/delete UI beyond
  Remove-Last/Clear-All.** Mirrors the deliberate v1 scope limit already
  accepted for Masking's own single-slot design, adapted to healing's
  own list shape.
- **Masking** (the other half of Phase J's PDF 21-22 pairing) is
  untouched -- it was already completed in the mask-tool-ui slice.

## 2. Current behavior

Before this slice, `ImageController.on_heal_spots_changed` was callable
only from tests/scripts -- `EditingToolStrip`'s "Heal" button was a
disabled placeholder identical to the still-unbuilt Transform, and no
widget existed to let a user place, see, or remove heal spots.

## 3. Design

### 3.1 Reusing the Crop/Mask overlays' coordinate-math property, directly

`HealingOverlay` is, deliberately, structured as closely as possible to
`CropOverlay`/`MaskOverlay`: a `QWidget` with `WA_TranslucentBackground`,
a direct child of `ImageView._image_canvas`, resized/positioned to
exactly match it on every `_update_display()` call. The same property
that made `CropOverlay` tractable (see the crop-tool-ui note's section
3.1 for the full derivation) applies identically here: the canvas's own
`(0, 0)`-to-`(width, height)` local rect IS the displayed, zoomed
pixmap's screen rect at any zoom level, so a pixel position inside the
overlay maps directly to a normalized image fraction via a single
division, with no scroll-offset or zoom correction needed.

### 3.2 The live-preview-vs-commit design decision, re-derived (not just
     copied) for healing

**The question, re-asked for this slice.** `on_heal_spots_changed`'s own
docstring and slice 1's implementation note are explicit: it is a
single, discrete, `add_to_history=True` commit (mirroring
`on_crop_changed`/`on_mask_changed`'s pattern exactly), not meant for
live-drag spam. So how does the user see a spot's effect while still
dragging its radius, or after placing several spots, before clicking
Apply?

**Re-confirming the two rejected-mechanism reasons still apply to
Healing.** The mask-tool-ui slice's section 3.5 rejected reusing the
existing slider-drag debounce/preview path
(`on_adjustments_changed` -> `ThrottledDebouncer` -> ...) for two
concrete, code-verified reasons. Both were independently re-verified
here for Healing, reading `get_export_image` and
`apply_adjustments`'s own code directly rather than assuming the mask
slice's findings transfer unchanged:

- `apply_adjustments`'s own synchronous, non-threaded
  (`use_threading=False`) fallback branch -- the one exercised by every
  unit test that constructs `ImageController` without a running
  `ProcessingWorker` -- reaches `self._healing_processor` only via the
  THREADED worker path and the full synchronous `get_export_image`
  recompute, not via that particular live-preview fallback branch
  either (confirmed by reading `apply_adjustments`'s code directly: the
  non-threaded live-preview fallback calls a fixed subset of
  processors, and Healing, like Mask before it, is not among them).
  Reusing that path for heal-spot live preview would silently do
  nothing in exactly the test configuration most of this codebase's
  non-UI tests use.
- Every call into `apply_adjustments`/`on_*_changed`-style methods
  unconditionally stores whatever `healing_params` it is given (see
  `apply_adjustments`'s own code: `self._healing_params = healing_params`
  whenever the argument is not `None`, regardless of `add_to_history`).
  Using this path for a live, in-progress, UNCOMMITTED spot list would
  mean the controller's own "current heal spots" field tracks the
  candidate, not the last real commit, for the whole editing session --
  requiring a second, separate "undo a non-historied apply" mechanism on
  Cancel that does not otherwise exist.

**The chosen design, mirroring `preview_mask`'s exact pattern.**
`ImageController.get_export_image` gained a second override parameter,
`heal_spots_override` (defaulting to the same private `_UNSET` sentinel
`mask_override` already uses, distinct from both `None` and `[]` -- both
legitimate override values). When passed, it is used IN PLACE OF
`self._healing_params` for that one recompute only; `self._healing_params`
itself is never read or mutated by this path. Applied at the FIRST
pipeline position, exactly where slice 1's own "healing goes first"
ordering decision put the committed-state code path (see slice 1's
section 2.2) -- `heal_spots_override`'s check sits ahead of every other
processor call in `get_export_image`, not wherever `mask_override`
happens to sit (which is near the end, matching Mask's own "applied
after every other adjustment" pipeline position). A new, tiny, public
method, `ImageController.preview_heal_spots(heal_spots)`, wraps this:
normalize/clamp the candidate (reusing slice 1's own
`_normalize_heal_spots_state`, so a mid-drag value momentarily outside
`[0, 1]`/`[0.01, 1]` can never reach the processor un-clamped), call
`get_export_image(heal_spots_override=normalized)`, and hand the result
straight to `ImageView.set_image(..., emit_loaded=False,
preserve_view_scale=True)` -- the exact same call `preview_mask` and
`_enter_crop_mode` already use for a "not the currently-committed state"
preview image.

This is safe to call on every drag frame (and is -- `HealingOverlay`'s
`spots_changed` signal and every `HealingToolbar` pending-value-change
signal are all wired to a handler that calls `preview_heal_spots` with
the overlay's current full in-progress list) with zero accumulating cost
beyond the one full-pipeline recompute itself, and zero risk of ever
being mistaken for, or leaving a stray trace in, a real edit.

**Why this resolves `_cancel_healing` as trivially as `_cancel_mask`.**
Because `preview_heal_spots` never touches `self._healing_params` or
`self._image_model.current_image`, there is nothing to roll back on
cancel beyond hiding the overlay/toolbar. `_cancel_healing` simply calls
`ImageController.refresh_view()`, mirroring `_cancel_mask`'s own
simplicity exactly (and unlike `_cancel_crop`, which must perform a
second real `get_export_image()` recompute because `_enter_crop_mode`
swapped in a different, uncropped display image that needs reverting --
Healing, like Mask, needs no such image swap on entry).

### 3.3 `HealingOverlay` (`src/views/widgets/healing_overlay.py`)

State: `self._spots: list[dict]` (the full in-progress list, each a
COMPLETE, `HealingProcessor`-shaped dict --
`dst_x`/`dst_y`/`src_x`/`src_y`/`radius`/`feather`/`opacity`/`mode`),
`self._dragging_spot: Optional[dict]` (the in-progress, not-yet-released
spot, with a live radius), and the toolbar's current pending
`mode`/`feather`/`opacity` (`self._pending_mode`/`_pending_feather`/
`_pending_opacity`).

**The toolbar-values-baked-in-at-placement-time design, confirmed
deliberate.** Each placed spot's `mode`/`feather`/`opacity` are copied
from `self._pending_*` INTO the spot dict at the moment `mouseReleaseEvent`
commits it -- not referenced live from a shared toolbar value at render
or commit time. This means changing the toolbar's controls after a spot
is placed never retroactively changes that already-placed spot, which
is the only interpretation consistent with this v1 having no per-spot
editing at all. `TestPendingValuesBakedInAtPlacementTime` in
`tests/unit/test_views/test_healing_overlay.py` proves this directly,
not just by assertion: it places one spot with one set of pending
values, changes every one of them, places a second spot, and asserts
the two spots in the final list have DIFFERENT stored
mode/feather/opacity reflecting what was pending at each one's own
placement time.

**Interaction (`mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`).**
Press sets the destination center and starts a spot with a small fixed
default radius (`_DEFAULT_RADIUS_FRACTION = 0.05`); move while pressed
recomputes the radius live as the normalized-fraction distance from the
press point to the current mouse position, clamped to
`[_MIN_RADIUS_FRACTION=0.01, _MAX_RADIUS_FRACTION=0.5]` (mirroring
`CropOverlay`'s own min-size-floor precedent, adapted to a radius rather
than a rect); release computes the final auto-offset source point (see
below), bakes in the current pending mode/feather/opacity, appends the
complete spot dict to `self._spots`, clears the drag state, repaints,
and emits `spots_changed`.

**The auto-offset source rule (`_compute_source_offset`).** Offset
directly right by `2 * radius`; if `dst_x + offset + radius > 1.0` (the
source circle would spill past the right edge), flip to directly left by
the same amount instead; if that ALSO doesn't fit (`dst_x - offset -
radius < 0.0` -- only possible for a destination spot wider than half
the image), clamp to whichever side has more room, itself clamped into
`[0, 1]` so the result is never out-of-bounds. `dst_y`/`src_y` are
always equal -- the offset is purely horizontal, per the spec's own
fixed rule. `tests/unit/test_views/test_healing_overlay.py`'s
`TestPlacementNearRightEdgeFallsBackToLeftOffset` constructs this edge
case precisely: a destination at `dst_x=0.9` with `radius=0.08` (right
offset `0.9+0.16+0.08=1.14 > 1.0` does not fit; left offset
`0.9-0.16-0.08=0.66 >= 0.0` does), and asserts the exact expected
`src_x = dst_x - 2*radius = 0.74`, distinct from the simple right-offset
case's own exact-value assertion (`TestPlacementDragReleaseSimpleCase`,
a press comfortably away from any edge).

**Rendering.** For every spot in `self._spots` PLUS the in-progress
`self._dragging_spot` (if any): a destination circle outline, a smaller
source circle outline, and a thin connecting line between their centers
-- `#0078d4` (blue) for Heal-mode spots, `#d48a00` (amber) for Clone-mode
spots, dashed while still being dragged (no final source point exists
yet mid-drag, so the source marker/line is only drawn for already-placed
spots and the just-released one). A deliberately basic marker, per the
roadmap bullet's own "(simplified)" qualifier -- see section 1's
non-goals.

**Radius rendering: NO Mask-style two-axis (`rx`/`ry`) aspect
correction needed, confirmed by re-deriving the reasoning rather than
copying Mask's math.** `MaskOverlay._ellipse_rect_px()` scales `rx` by
the widget's width and `ry` by its height INDEPENDENTLY, because
`MaskProcessor._radial_alpha` itself treats `rx`/`ry` as two independent
normalized fractions of width/height respectively (see the
mask-tool-ui note's section 3.2). `HealingProcessor`, by contrast, has
only a SINGLE `radius` value, converted to pixels via
`radius * min(width, height)` (slice 1's own documented
"resolution-relative, not per-axis" convention -- see the
healing-processor note's section 4.2, point 2). Since this overlay
widget's own pixel size always has the same aspect ratio as the
displayed image (section 3.1's property), scaling that SAME single
radius by `min(widget_width, widget_height)` is therefore already
exactly consistent with what `HealingProcessor` actually renders, with
no separate horizontal/vertical scale factor needed at all -- a true
on-screen circle (not an ellipse) is the CORRECT rendering here, unlike
Mask's radial ellipse, which is only "visually circular" on a
square-aspect canvas and is genuinely elliptical in image-pixel space on
a non-square one. `HealingOverlay._spot_radius_px` implements exactly
this: `spot["radius"] * min(width, height)`, deliberately NOT
`MaskOverlay`'s own two-factor approach.

### 3.4 `HealingToolbar` (`src/views/widgets/healing_toolbar.py`)

Mirrors `MaskToolbar`'s `QFrame` structure/styling. Contains a Mode
combo (`"Heal"`/`"Clone"`), Feather/Opacity sliders (both `0..1`
fractions, reusing the existing `AdjustmentSlider` widget class, ranges
confirmed directly from `HealingProcessor`'s own documented state
contract in the healing-processor note's section 4.1 -- not guessed),
and Remove Last/Clear All/Cancel/Apply buttons. **Deliberately no
"radius" control** -- see section 1's non-goals; radius is purely a drag
property. `set_values(mode, feather, opacity)` is the programmatic,
non-emitting init (heal-mode entry), using the same `_suppress_signals`
flag pattern `MaskToolbar.set_values` already establishes.

**What each control affects, exactly (documented plainly, per the task's
own request).** The Mode combo and Feather/Opacity sliders set the
PENDING values baked into the NEXT spot placed -- they never
retroactively change an already-placed spot, since this v1 has no
per-spot editing at all (see section 3.3). Remove Last/Clear All operate
on the overlay's in-progress list directly. Apply commits the overlay's
full list via `on_heal_spots_changed`; Cancel discards everything
in-progress without committing.

### 3.5 `ImageView` additions

`enter_healing_mode(initial_spots)`/`exit_healing_mode()`/
`is_in_healing_mode()`/`get_healing_overlay()` mirror
`enter_mask_mode`/`exit_mask_mode`/`is_in_mask_mode`/`get_mask_overlay`
exactly (lazy single-instance creation, shown/hidden rather than
recreated, resized/positioned to match the canvas, kept in sync on every
`_update_display()` call while visible). Like Mask mode (and unlike Crop
mode), entering healing mode does NOT require an image swap -- the
canvas already shows the correct, fully-adjusted image, and the
live-preview mechanism (section 3.2) shows exactly the in-progress
candidate's effect on top of it.

### 3.6 `EditingToolStrip`/`ToolsPanel` -- enabling the "Heal" button

`EditingToolStrip` gained a `heal_tool_requested` signal, emitted by the
now-enabled Heal button -- mirrors exactly how `crop_tool_requested`/
`mask_tool_requested` were added in the prior two slices. Transform
remains the one disabled placeholder. `ToolsPanel` forwards it outward
as its own `heal_tool_requested`, the same direct re-emit pattern already
used for the other two.

### 3.7 `MainWindow` wiring

`_enter_healing_mode`: no-image guard (status-bar message); reads the
current `heal_spots` from `get_adjustment_state()`, initializes the
overlay via `set_spots` (so re-entering healing mode after a prior
Apply always reflects the current real committed state, mirroring
`_enter_mask_mode`'s own "always re-read fresh" principle); shows
`HealingToolbar`, hides `ImageToolBar`.

`HealingOverlay.spots_changed` and every `HealingToolbar`
pending-value-change signal (`mode_changed`/`feather_changed`/
`opacity_changed`) are connected to `_on_heal_editing_changed`, which
calls `self._image_controller.preview_heal_spots(overlay.get_spots())`
-- the live-preview path, never touching history. (A pure mode/feather/
opacity change with no spot yet placed is a correct, harmless no-op on
the displayed image, since it does not change the committed list being
previewed -- it only changes what the NEXT placement will bake in.)

`_apply_healing`: `self._image_controller.on_heal_spots_changed(overlay.get_spots())`
as the ONE committed edit, then exits healing mode.

`_cancel_healing`: exits healing mode without committing -- mirrors
`_cancel_mask`'s trivial simplicity exactly (see section 3.2 for why this
is safe).

**Three-way mutual exclusion (Crop/Mask/Heal), refactored into a shared
helper.** The prior slice (Mask) implemented Crop<->Mask mutual
exclusion as two separate pairwise checks, one inside each of
`_enter_crop_mode`/`_enter_mask_mode`. Rather than adding a THIRD
pairwise check in each of three methods (six total conditionals), this
slice refactors all of it into one shared helper,
`_exit_any_interactive_tool_mode`, called at the top of all three
`_enter_X_mode` methods: it checks each of `is_in_crop_mode`/
`is_in_mask_mode`/`is_in_healing_mode()` and calls that mode's own
Cancel method if active. Every `_enter_X_mode`, including a FOURTH tool
mode in a hypothetical future slice, needs only ONE line
(`self._exit_any_interactive_tool_mode()`) rather than N-1 pairwise
checks -- this is the real DRY benefit of the refactor, not just fewer
lines today. None of the three Cancel paths commit the mode being
exited -- entering one tool while mid-edit on another always discards
that other edit, exactly like clicking its own Cancel button would.
`tests/ui/test_main_window_healing.py::TestThreeWayMutualExclusivity`
verifies every meaningful pairing directly (Heal exits an active Crop;
Heal exits an active Mask; Crop exits an active Heal; Mask exits an
active Heal; and a combined test asserting never more than one of the
three is active at once even after entering all three in sequence), and
the prior slice's own `test_main_window_crop.py`/`test_main_window_mask.py`
Crop<->Mask tests were rerun to confirm the refactor caused no
regression in the two-way case.

## 4. Contracts

- `ImageController.get_export_image(apply_crop=True, mask_override=_UNSET,
  heal_spots_override=_UNSET)`: `heal_spots_override`, when passed
  (including explicitly `[]`), is a LIST used IN PLACE OF
  `self._healing_params` for that one recompute only, applied at the
  FIRST pipeline position (mirroring slice 1's own "healing goes first"
  ordering). `self._healing_params` itself is never mutated by this
  path. Left at the private `_UNSET` sentinel (shared with
  `mask_override`) by every existing call site, which is therefore
  completely unaffected.
- `ImageController.preview_heal_spots(heal_spots: list) -> None`: new
  public, display-only, non-historied, non-mutating live-preview entry
  point. Normalizes/clamps via `_normalize_heal_spots_state`. Safe to
  call any number of times in a row.
- `HealingOverlay.set_spots(spots)`/`get_spots() -> list`: programmatic
  bulk-set (no signal)/full-list read, each spot a complete
  `HealingProcessor`-shaped dict.
- `HealingOverlay.remove_last()`/`clear_all()`: mutate the in-progress
  list and emit `spots_changed`; no-op (no emission) if already empty.
- `HealingOverlay.set_pending_mode(mode)`/`set_pending_feather(feather)`/
  `set_pending_opacity(opacity)`: set the values baked into the NEXT
  spot placed; never touch an already-placed spot.
- `HealingOverlay.spots_changed = pyqtSignal(list)`: emitted with the
  full in-progress list on a new placement, Remove Last, or Clear All.
  Never emitted by `set_spots`.
- `HealingToolbar.set_values(mode, feather, opacity)`/`get_mode()`/
  `get_feather()`/`get_opacity()`: programmatic init (no emission)/
  reads.
- `HealingToolbar.mode_changed`/`feather_changed`/`opacity_changed`/
  `remove_last_requested`/`clear_all_requested`/`apply_requested`/
  `cancel_requested`: see section 3.4/the module docstring.
- `ImageView.enter_healing_mode(initial_spots)`/`exit_healing_mode()`/
  `is_in_healing_mode() -> bool`/`get_healing_overlay() ->
  Optional[HealingOverlay]`.
- `EditingToolStrip.heal_tool_requested`/`ToolsPanel.heal_tool_requested`:
  forwarded, no payload.
- `MainWindow._exit_any_interactive_tool_mode()`: new shared helper,
  cancels whichever of Crop/Mask/Heal is currently active (a no-op if
  none are). Called at the top of all three `_enter_X_mode` methods.

## 5. Nuances and failure modes

**Three-way mutual exclusion is now a shared helper, not three pairwise
checks -- see section 3.7 in full.** This is the one structural
refactor this slice makes to pre-existing Crop/Mask code, verified not
to regress the existing two-way tests.

**The auto-offset source rule's edge-case fallback is a real, tested
path, not a theoretical one.** See section 3.3's exact worked example
(`dst_x=0.9, radius=0.08`) and its dedicated test.

**The toolbar-values-baked-in-at-placement-time design is the only
correct reading of "toolbar applies to the next spot," given no
per-spot editing exists.** See section 3.3's extended discussion and its
dedicated, two-spot-comparison test -- proven, not merely asserted.

**No Mask-style two-axis radius correction is needed for Healing's
circle rendering, and this is a genuine simplification, not a missed
case.** See section 3.3's extended derivation: `HealingProcessor` itself
scales its single `radius` by `min(width, height)`, not per-axis, so a
widget-space circle scaled the same way is already exactly correct.

**The chosen live-preview mechanism recomputes the FULL image on every
call, exactly like `preview_mask`/crop mode's own full-frame fetch
already do.** For a very large source image, dragging a spot's radius
could feel less smooth than the global slider's own throttled/debounced
worker-thread path. An accepted, documented v1 cost, in the same
category Mask's own slice already accepted and documented.

**Re-entering healing mode after a prior session's Apply always
reflects the CURRENT real committed state**, since `_enter_healing_mode`
always re-reads `get_adjustment_state()["heal_spots"]` fresh on every
entry -- mirroring Crop/Mask's own "always re-read fresh" principle.

## 6. Test plan

- `tests/unit/test_views/test_healing_overlay.py` (19 tests): `set_spots`/
  `get_spots` round-trip without emitting (and `get_spots` returns a
  defensive copy); a simulated press-drag-release places a spot with the
  exact expected center/radius and the exact expected RIGHT-offset
  source (a press comfortably away from any edge); a second, dedicated
  press-drag-release NEAR THE RIGHT EDGE falls back to the exact expected
  LEFT-offset source instead; `remove_last`/`clear_all` behave correctly,
  including no-op-on-empty (no emission); multiple sequential placements
  accumulate correctly, in order; **the toolbar-values-baked-in-at-
  placement-time test**
  (`TestPendingValuesBakedInAtPlacementTime::test_two_spots_reflect_different_pending_values_at_their_own_placement`)
  -- places one spot with one set of pending mode/feather/opacity,
  changes all three, places a second spot, and asserts the two spots'
  stored values differ exactly as expected, proving per-placement
  baking, not shared-reference lookup; radius clamping to both the
  minimum and maximum floor; `spots_changed` emitted exactly once per
  placement/remove-last/clear-all, with the correct full-list payload.
- `tests/unit/test_views/test_healing_toolbar.py` (11 tests): slider
  ranges match `HealingProcessor`'s own `0..1` feather/opacity contract;
  `set_values`/get-pair round-trip without emitting; each control change
  emits the right signal with the right payload; Remove Last/Clear
  All/Apply/Cancel buttons each emit their signal via `QTest.mouseClick`.
- `tests/ui/test_main_window_healing.py` (11 tests): `_enter_healing_mode`
  with no image shows the right status message and never touches
  `ImageView`; with an image, shows the toolbar/hides `ImageToolBar`, and
  seeds the overlay from any existing committed spots; `_apply_healing`
  commits exactly once via `on_heal_spots_changed` with the overlay's
  full spot list (built from a real simulated placement, not a hand-
  constructed dict) and exits healing mode; `_cancel_healing` after a
  real in-progress placement leaves the real, committed
  `get_adjustment_state()["heal_spots"]` byte-for-byte unchanged; live
  preview's "realness" is proven, not assumed -- a real, default-threaded
  `ImageController` loads a genuinely two-colored (non-flat) test image
  (a flat-color image would make a Clone/Heal preview test meaningless,
  since there would be nothing visually different to clone), a spot is
  placed straddling the color boundary, and the displayed `QImage` is
  asserted to have genuinely changed while `get_adjustment_state()["heal_spots"]`
  stayed `[]` throughout; three-way mutual exclusion, tested in every
  meaningful pairing (Heal exits Crop; Heal exits Mask; Crop exits Heal;
  Mask exits Heal; and never more than one active at once after entering
  all three in sequence).

## 7. Rollout

Purely additive UI, plus one small, fully backward-compatible
`ImageController` addition: a new optional `get_export_image` parameter
(default preserves every existing call site's behavior exactly) and a
new `preview_heal_spots` method (never called by any pre-existing code
path). No state-shape or pipeline change -- the `"heal_spots"` state key
and `on_heal_spots_changed`'s own contract are completely unchanged from
slice 1. A plain revert removes the two new widgets, the `ImageView`/
`EditingToolStrip`/`ToolsPanel`/`MainWindow` wiring, and the
`get_export_image`/`preview_heal_spots` additions, leaving
`on_heal_spots_changed` exactly as reachable (by tests only) as it was
before this slice. The one structural change to PRE-EXISTING code is the
Crop/Mask mutual-exclusion refactor into `_exit_any_interactive_tool_mode`
(section 3.7); it is behavior-preserving for the two-way case (verified
by rerunning the prior slices' own mutual-exclusion tests) and purely
additive for the new three-way case.

This completes Phase J's Healing bullet's v1 scope: both halves of PDF
21-22 (Healing and Masking) now have real, if deliberately limited, UI
coverage. See section 8 and the roadmap update for exactly what remains
a gap in each.

## 8. Implementation summary

Built `HealingOverlay` (`src/views/widgets/healing_overlay.py`) and
`HealingToolbar` (`src/views/widgets/healing_toolbar.py`), wired into
`ImageView` (`enter_healing_mode`/`exit_healing_mode`/
`is_in_healing_mode`/`get_healing_overlay`, plus
overlay-resize-on-display-update), `EditingToolStrip`/`ToolsPanel`
(enabled Heal button, forwarded `heal_tool_requested` signal), and
`MainWindow` (`_enter_healing_mode`/`_apply_healing`/`_cancel_healing`/
`_on_heal_remove_last`/`_on_heal_clear_all`/`_on_heal_mode_changed`/
`_on_heal_feather_changed`/`_on_heal_opacity_changed`/
`_on_heal_editing_changed`, the `HealingToolbar` instance swapped in for
`ImageToolBar`, and the new shared `_exit_any_interactive_tool_mode`
helper replacing the prior slice's Crop<->Mask pairwise checks). Added
`ImageController.get_export_image`'s new `heal_spots_override` parameter
and the new `ImageController.preview_heal_spots` method (section 3.2).

**Deviation notes.**

1. The task brief left the per-spot dict's storage of
   mode/feather/opacity "your call, just be consistent and document it
   clearly" -- storing them PER-SPOT at placement time (not a shared
   toolbar reference) was chosen, as the spec itself flagged as the only
   reading consistent with "toolbar applies to the next spot." No
   deviation from the spec's own stated preference, but documented here
   per its own request, with a dedicated proof test (section 6).
2. The radius-rendering aspect-correction question (single on-screen
   circle vs. Mask-style two-axis ellipse) was explicitly re-derived
   rather than assumed, per the task's own instruction -- concluded a
   plain circle, scaled by `min(width, height)` exactly like
   `HealingProcessor` itself does, is already correct with no two-axis
   correction needed (see section 3.3's extended reasoning). This
   simplified the implementation relative to blindly porting
   `MaskOverlay._ellipse_rect_px()`'s two-factor math.
3. The Crop/Mask mutual-exclusion refactor into
   `_exit_any_interactive_tool_mode` was explicitly suggested as optional
   ("feel free to refactor ... if it reduces duplication") -- taken, since
   a third pairwise check in each of three methods would have meant six
   total conditionals versus one shared three-line helper; verified not
   to regress the existing two-way Crop/Mask tests.
4. No other deviation of substance from the task's design spec for the
   widget APIs, signal shapes, or `MainWindow` wiring.

**Verification.** New/changed test files: `tests/unit/test_views/
test_healing_overlay.py` (19 passed), `tests/unit/test_views/
test_healing_toolbar.py` (11 passed), `tests/ui/test_main_window_healing.py`
(11 passed) -- all passing in isolated, file-scoped runs, including the
real simulated press-drag-release placement tests (simple case and the
right-edge-fallback case), the per-placement toolbar-value-baking proof,
and the real-controller live-preview/no-net-change-on-cancel tests.
Also reran the full prior crop/mask-tool-ui test files
(`test_crop_overlay.py`, `test_crop_toolbar.py`, `test_main_window_crop.py`,
`test_mask_overlay.py`, `test_mask_toolbar.py`, `test_main_window_mask.py`)
plus `test_image_controller.py` and all of `tests/unit/test_views/`
together (443 passed) to confirm no regression from the
`get_export_image` signature change or the `_exit_any_interactive_tool_mode`
refactor. Full-suite pass count: see the calling session's own run for
the final authoritative number (per this task's own instruction).
