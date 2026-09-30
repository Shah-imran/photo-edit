# Workspace shell polish

## 1. Problem and goal

PhotoEdit's editing behavior is substantially ahead of its visual shell. The
main window uses functional Qt defaults and several view-local styles, while
the proposed product direction is a compact, professional dark workspace with
clear library, canvas, filmstrip, and adjustment hierarchy.

This slice implements the first visual vertical slice of that direction:

- a centralized dark application theme and design tokens;
- compact, fixed-purpose left and right docks;
- a canvas toolbar for fit, 100%, zoom, and pan affordances;
- a synchronized bottom filmstrip backed by the current library entries;
- a navigation-only left library rail, with thumbnails shown exclusively in
  the bottom filmstrip; and
- clearer status information and polished panel framing.

Non-goals are processor changes, new adjustment types, before/after image
rendering, search/filter behavior, album/folder data models, ratings, a new
histogram processor, icon asset production, and undo/redo state repair. The
toolbar may expose a disabled before/after affordance to communicate future
placement, but it will not pretend that the feature is implemented.

## 2. Current behavior

`MainWindow._setup_ui()` creates a bare central `ImageView` and two
`QDockWidget`s. Zoom actions exist only in the menu and status bar. The
`LibraryView` owns the only thumbnail grid and receives entries via
`MainWindow._on_library_entries_rebuilt()`. The tools panel contains all
working adjustment widgets but builds non-collapsible section frames and
duplicates hard-coded colors across view modules. Application startup in
`src/main.py` does not install an application-wide theme.

Window geometry and dock state are persisted already. Image loading is
asynchronous and library thumbnail payloads may arrive after the entry list.
The existing view and UI tests directly inspect several private widgets, so
their identities and existing signals must remain stable.

## 3. Proposed design

Add a view-only theme module containing named palette/spacing constants and a
single QSS string. `main.py` installs it on the `QApplication`; `MainWindow`
also applies it when constructed directly in tests or embedders.

Add two focused widgets:

- `ImageToolBar`: emits plain intent signals for fit, 100%, zoom in/out, and
  pan mode. It reflects zoom state but owns no image logic.
- `FilmstripView`: accepts the same list-of-dicts entry payload used by the
  library and emits a selected file path. It keeps a path-to-item lookup so
  asynchronous thumbnail updates and current-image selection are cheap.

The central area becomes a vertical workspace: `ImageView`, image toolbar,
then filmstrip. User flows are:

1. Library entries rebuild -> `MainWindow` sends the payload to the filmstrip
   and the hidden compatibility model in `LibraryView`; the left rail shows
   only library names and per-library counts.
2. A thumbnail update arrives -> the filmstrip updates the matching item.
3. Selection in either thumbnail view -> existing image-selection handler ->
   controller load path remains unchanged -> current path is reflected in the
   filmstrip.
4. Toolbar button -> intent signal -> existing `MainWindow` zoom method ->
   `ImageView` updates -> zoom signal refreshes toolbar and status label.

Tools sections are moved to the existing `CollapsibleSection` widget while
retaining the current child controls and signals. Light, Tone Curve, and Color
start expanded; advanced sections start collapsed.

## 4. API and data contracts

New view contracts:

- `ImageToolBar.fit_requested`, `actual_size_requested`,
  `zoom_in_requested`, and `zoom_out_requested`: no-argument Qt signals.
- `ImageToolBar.set_zoom_factor(float)`: display-only update.
- `FilmstripView.image_selected(str)`: absolute/normalized path passed through
  from the existing entry payload.
- `FilmstripView.set_entries(list[dict])`,
  `update_entry_thumbnail(str, dict)`, and `set_current_path(str | None)`.

No service, controller, JSON, QSettings, or adjustment payload formats change.
Existing `LibraryView`, `ToolsPanel`, and `ImageView` public contracts remain
compatible.

## 5. Nuances and failure modes

- An empty library shows an unobtrusive filmstrip empty state and must not
  reserve excessive height.
- Thumbnail generation is asynchronous; updates for removed or stale paths
  are ignored.
- A selection made during an in-flight load continues through the existing
  controller cancellation/latest-request rules.
- Restored dock state may contain older sizes. Minimum/maximum widths and a
  final resize provide sane defaults without invalidating the saved-state
  version.
- Direct widget construction in tests may occur without `main()`, so the
  central widgets must remain legible through object-level styles and the
  main window must be able to install the theme idempotently.
- Symbols used as temporary icons must have text tooltips and accessible names.

## 6. UI and reskin impact

The shell, menus, docks, status bar, sliders, scrollbars, buttons, and panels
adopt the shared theme. View code continues to emit intent and plain data;
controllers/services retain all file, persistence, processing, and async
behavior. Consolidating styling is the main reskin-enabling change requested
by workflow section 5.1.

## 7. Dependencies

This is independent of processor phases and does not block adjustment work.
It establishes the reusable visual foundation for later search, album tree,
before/after, detail, and full histogram slices. There is no feature flag: the
change is view-only and can be reverted as one slice.

## 8. Test plan

Automated pytest-qt coverage will verify:

- theme installation and stable object names;
- toolbar signals and zoom-label formatting;
- filmstrip entry population, selection, current-path synchronization, and
  asynchronous thumbnail updates;
- main-window propagation of entries and thumbnail updates to both views;
- toolbar actions invoking the existing image-view commands; and
- tools-panel section expansion defaults without regressing adjustment signals.

Run the full existing suite after focused view tests.

Manual smoke checklist:

1. Launch `python -m src.main` at 1920x1080 and at the 1200x800 minimum.
2. Confirm dark shell, readable menus, compact docks, and no clipped controls.
3. Open/import images and confirm both thumbnail surfaces populate.
4. Select from library and filmstrip; confirm the same image loads and the
   filmstrip highlight follows.
5. Exercise fit, 100%, zoom in, and zoom out from the toolbar and menus.
6. Expand/collapse tool sections and move several existing sliders.
7. Restart and confirm saved dock geometry still restores.

## 9. Rollout and rollback

The slice is local UI code with no migration. Rollback is a focused revert of
the theme, toolbar, filmstrip, and view composition changes. User catalog and
settings data remain valid because no persisted keys or formats change.

## 10. Acceptance criteria

- The workspace visually matches the approved mockup's hierarchy and palette.
- Existing image load, edit, export, library, and persistence paths behave as
  before.
- The bottom filmstrip is the only visible thumbnail browser; the left rail
  remains a compact library navigator with a current-library count.
- Toolbar zoom controls and zoom readout remain synchronized.
- Tools sections are compact and collapsible without changing adjustment
  payloads.
- Focused tests and the full suite pass.
- The manual smoke checklist completes without layout breakage.

**Plan approved -- implementation allowed (2026-09-30, user direction to
implement the approved mockup).**

## 11. Implementation summary

Implemented the shared application theme, compact fixed-side dock treatment,
collapsible adjustment sections, canvas toolbar, richer status readout, and a
bottom filmstrip synchronized to the active library. The left dock now acts as
a compact named-library navigator while thumbnail browsing lives in the
filmstrip, matching the approved second mockup. Existing controller, processor,
catalog, settings, and adjustment-payload contracts were preserved.

Added focused toolbar, filmstrip, library-navigation, and main-window tests.
Library payloads include entry counts so inactive navigation rows remain
accurate. The final regression run completed with **620 passed**, and `compileall`
completed successfully. A real offscreen Qt render was inspected at 1400x900;
accordion checked-state and platform viewport-background leaks found during
that inspection were corrected. Deferred items remain real before/after
rendering, search, ratings, album/folder models, and a dedicated RGB histogram.
