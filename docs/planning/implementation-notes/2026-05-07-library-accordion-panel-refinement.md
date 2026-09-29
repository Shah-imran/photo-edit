# 2026-05-07 -- Library accordion panel refinement

Related plan: [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) sections 4, 5.1 ; follow-up to [2026-05-07-library-controller-and-stacked-panel-refactor.md](2026-05-07-library-controller-and-stacked-panel-refactor.md)

## 1. Problem and goal

The stacked library-panel refactor still separates "libraries" and "photos"
into two areas. The desired interaction is tighter: each library should appear
as a single collapsible row in one column, and expanding that row should show
that library's images directly underneath it.

Goal for this slice:

- Replace the separate libraries list + photo grid pattern with a one-column
  accordion.
- Make each library header clickable/collapsible.
- Show the images for the selected library directly under that library header.
- Keep one expanded library at a time for a cleaner dock.

Non-goals:

- No storage-schema change.
- No new metadata, relink, search/filter, or folder-watch features.
- No redesign of import/export behavior beyond the accordion layout.

## 2. Current behavior

- `LibraryView` currently renders:
  - one collapsible "Libraries" section containing a list of libraries,
  - one separate photo grid below it.
- `LibraryController` already owns library orchestration and emits:
  - library list updates,
  - entry payloads for the current library,
  - thumbnail updates for current-library entries.
- Only one library's entries are meant to be visible at a time, but the UI still
  feels like two coordinated widgets instead of one accordion.

## 3. Proposed design

- Keep `LibraryController` as the orchestration layer.
- Refactor `LibraryView` into an accordion container:
  - one `CollapsibleSection` per library,
  - each section contains a `QListWidget` grid for that library's images,
  - only the current library section is expanded,
  - expanding a section emits `library_selected(library_id)`.
- Top panel controls remain simple:
  - `+ Import`,
  - `+ Library`,
  - `- Library` for the currently expanded library.
- When controller emits current-library entries, the view renders them into the
  expanded library section's grid instead of a separate global grid.
- Thumbnail updates target the expanded/current library section only.

## 4. API and data contracts

- Keep existing controller signals and view intent signals when possible.
- `LibraryView.set_libraries(...)` changes behavior:
  - it now rebuilds accordion sections instead of populating a list widget.
- `LibraryView.set_entries(...)` changes behavior:
  - it now repopulates the image grid belonging to the current expanded library.
- `LibraryView.get_image_count()` continues to report the visible/current
  library's image count for test compatibility.
- `LibraryView.get_current_library_id()` continues to report the expanded
  library id.

## 5. Nuances and failure modes

- Rebuilding accordion sections must not leak old widgets or leave stale signal
  connections.
- If the current library disappears (remove action), the next current library
  must become the only expanded section.
- Collapsing the currently expanded section by clicking it should still leave it
  selected conceptually; for this slice we will use accordion behavior and keep
  the current library expanded when selected.
- Missing-entry placeholders and available-entry click behavior must remain
  unchanged.

## 6. UI and reskin impact

- The left dock becomes visually simpler:
  - one vertical stack of library headers,
  - images inline under the expanded header.
- This better matches the desired "one column" behavior and keeps the dock from
  feeling like an embedded second explorer.

## 7. Dependencies

- Depends on the existing `LibraryController` and `CollapsibleSection`.
- Does not require any catalog or cache migration.

## 8. Test plan

Automated:

- Update view tests to assert accordion sections exist instead of a library list.
- Test that clicking/expanding another library emits `library_selected`.
- Test that visible image count belongs to the expanded library section.
- Update main-window/library tests for section-based switching rather than list
  selection.

Manual smoke:

1. Launch app and confirm libraries appear as one-column collapsible rows.
2. Expand different libraries and verify images appear beneath the selected
   header.
3. Import into the current library and verify thumbnails appear under that
   header.
4. Remove a library and confirm the next remaining library expands.

## 9. Rollout and rollback

- Rollout is immediate and always-on.
- Rollback is a pure UI refactor rollback; the controller/services can remain.

## 10. Acceptance criteria

- The library dock is one column of collapsible library headers.
- Expanding a library shows that library's images directly underneath it.
- The separate library-list widget is removed.
- Existing persistence/cache behavior continues to work.
- Focused view/controller/UI tests pass.

Plan approved -- implementation allowed: **Approved by user request in chat (2026-05-07)**

## 11. Implementation summary

Landed:

- Replaced the separate library-list manager block with a one-column accordion
  in `LibraryView`.
- Each library now renders as its own `CollapsibleSection`, and the current
  library's images appear inline beneath that header.
- Accordion behavior keeps one library expanded at a time and emits
  `library_selected(library_id)` when a different library is opened.
- The top bar still provides import/create/remove actions, but the dock no
  longer feels like a parallel explorer plus separate photo area.
- Updated focused view and main-window tests to assert section-based rendering
  and switching.

Deferred as planned:

- Persisting section expanded/collapsed state across launches.
- Rendering multiple libraries' image grids open at the same time.
