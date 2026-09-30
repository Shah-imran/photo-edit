# 2026-05-07 -- Library row toggle and inline delete refinement

Related plan: [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) sections 4, 5.1 ; follow-up to [2026-05-07-library-accordion-panel-refinement.md](2026-05-07-library-accordion-panel-refinement.md)

## 1. Problem and goal

The accordion library UI is close, but three interaction details still do not
match the intended behavior:

- Clicking the currently expanded library header does not collapse it.
- The active library section does not visually consume the full usable panel
  space when expanded.
- Delete is a global top action instead of living on each library row.

Goal for this slice:

- Make each library header a true toggle for its own image panel.
- Make the expanded/current library section stretch to fill the panel while
  collapsed libraries stay as header rows only.
- Move delete affordance onto the library row/header itself.

Non-goals:

- No storage or controller contract changes unless needed for row-level delete.
- No multi-open accordion behavior; one expanded library at a time remains the
  default.

## 2. Current behavior

- `LibraryView` renders one `CollapsibleSection` per library.
- Opening another library collapses the previous one.
- Clicking the current library row again reopens it immediately instead of
  allowing a closed state.
- Delete is still driven by a top-level `- Library` button.
- Section sizing is not explicitly biased so the active library grid fills the
  panel height.

## 3. Proposed design

- Keep per-library `CollapsibleSection`s.
- Allow toggling the current section closed; preserve `current_library_id` as the
  last selected library even when its panel is collapsed.
- Give the expanded section an expanding size policy and/or layout stretch so its
  image grid fills the available dock space.
- Add a per-library delete button on the header row of each section; clicking it
  emits `remove_library_requested(library_id)`.
- Remove the top-level global delete button.

## 4. API and data contracts

- Existing view/controller signals remain valid.
- `remove_library_requested(str)` is now emitted from row-level controls instead
  of a top-level button.
- `is_library_section_expanded()` continues to report whether the current
  library's panel is open.

## 5. Nuances and failure modes

- Clicking the delete button must not also toggle the section.
- When a section is collapsed, its grid remains bound to the current library but
  hidden.
- Thumbnail updates for a collapsed current library should still update the grid
  items safely.
- When another library expands, it should still collapse any previously open
  library and become the stretched section.

## 6. UI and reskin impact

- The dock remains one-column, but now each library row is fully self-contained:
  title, toggle arrow, delete affordance, and inline image panel.
- The active library reads more clearly as the current working area by consuming
  the remaining panel space.

## 7. Dependencies

- Depends on the current accordion view and reusable `CollapsibleSection`.
- No service-layer migration required.

## 8. Test plan

Automated:

- Update view tests for:
  - toggle closed on same-row click,
  - expanding another row collapses the prior row,
  - row-level delete emits correct id,
  - active library grid remains the visible/current grid.
- Update focused UI tests for the new toggle semantics.

Manual smoke:

1. Expand a library and click it again to collapse it.
2. Expand another library and verify the first collapses.
3. Confirm the expanded library fills the panel space.
4. Delete a library using the button on its own row.

## 9. Rollout and rollback

- Rollout is immediate and UI-only.
- Rollback restores the previous accordion behavior and top-level delete button.

## 10. Acceptance criteria

- Clicking the same library row toggles its panel closed/open.
- The expanded library section fills the panel vertically when active.
- Delete lives on the library row/header, not the top toolbar.
- Focused view and UI tests pass.

Plan approved -- implementation allowed: **Approved by user request in chat (2026-05-07)**

## 11. Implementation summary

Landed:

- Updated the accordion so clicking the currently expanded library row can
  collapse that row instead of forcing it to stay open.
- Kept one-library-at-a-time expansion when opening a different library.
- Moved delete from the top toolbar into each library header row.
- Adjusted section sizing so the active expanded library is the section marked to
  fill the remaining panel space.
- Updated focused view and main-window tests for true toggle behavior and
  row-level delete.

Deferred as planned:

- Persisting expanded/collapsed row state across launches.
