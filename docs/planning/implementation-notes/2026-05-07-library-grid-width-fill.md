# 2026-05-07 -- Library grid width fill

Related plan: [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) section 4 ; follow-up to the 2026-05-07 library accordion refinements

## 1. Problem and goal

The library explorer still shows a visible blank strip on the right side even
after removing the outer dock margin. The goal is to make the thumbnail grid
use the full available panel width so the right-side dead space disappears.

## 2. Current behavior

- `LibraryView` uses a `QListWidget` in icon mode for each library section.
- Each thumbnail cell uses a fixed `112px` grid width.
- When the dock width is wider than an exact multiple of the fixed cell width,
  Qt left-aligns the columns and leaves unused space on the right.

## 3. Proposed design

- Introduce a small library-grid widget inside `library_view.py` that
  recalculates its `gridSize()` from the current viewport width.
- Keep the existing thumbnail size and styling, but let the cell width expand
  to evenly fill the available width for the current column count.
- Re-run the calculation on resize/show so the layout stays correct when the
  dock is resized or sections are expanded.

## 4. API and data contracts

- No signal, controller, or persistence changes.
- No catalog/cache schema changes.

## 5. Nuances and failure modes

- Preserve the current minimum thumbnail-cell width so the panel does not
  become cramped on narrow windows.
- Avoid changing selection or item payload behavior.
- The grid should remain stable whether a library is empty, collapsed, or
  resized after startup.

## 6. UI and reskin impact

- Presentation-only change inside the library dock grid layout.
- Business logic stays out of the view.

## 7. Dependencies

- Depends only on the current accordion-based `LibraryView`.

## 8. Test plan

- Add a focused `LibraryView` regression test that verifies the grid cell width
  updates to match the available viewport width.
- Run focused library view and main-window UI tests.

## 9. Rollout and rollback

- Immediate UI-only rollout.
- Rollback restores the previous fixed grid cell width.

## 10. Acceptance criteria

- The active library grid no longer leaves a noticeable blank strip on the
  right side when the dock has spare width.
- Thumbnail cells resize to fill the available viewport width.
- Focused library UI tests still pass.

Plan approved -- implementation allowed: **Approved by user request in chat (2026-05-07)**

## 11. Implementation summary

Landed:

- Added a small responsive thumbnail-grid helper inside `library_view.py`.
- The library grid now recalculates its cell width from the live viewport width
  and updates item size hints so columns fill the available panel width.
- The active library section refreshes its grid metrics when entries load and
  when the accordion layout changes.
- Added a focused regression test for responsive grid sizing.
- Focused library view and main-window UI tests pass.
