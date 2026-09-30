# 2026-05-07 -- Library inline remove glyph polish

Related plan: [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) section 4 ; follow-up to [2026-05-07-library-row-toggle-and-inline-delete.md](2026-05-07-library-row-toggle-and-inline-delete.md)

## 1. Problem and goal

The inline library-row delete action currently uses a full `Delete` text label.
The desired UI is a lighter-weight remove sign on the library row.

Goal for this slice:

- Replace the inline `Delete` row action label with a compact remove sign.
- Keep the existing row-level delete behavior and tooltip.

Non-goals:

- No behavior change to delete confirmation or controller wiring.
- No storage or layout changes beyond the row action label.

## 2. Current behavior

- Each library row in `LibraryView` renders a text button labeled `Delete`.
- Clicking it emits `remove_library_requested(library_id)`.

## 3. Proposed design

- Change the row action control text from `Delete` to a compact remove glyph.
- Keep the tooltip explicit so discoverability remains good.
- Retain existing styling and signal wiring.

## 4. API and data contracts

- No signal or controller contract changes.

## 5. Nuances and failure modes

- The glyph should remain legible in the dark theme.
- The button click must still not toggle the accordion row unexpectedly.

## 6. UI and reskin impact

- This is a presentation-only refinement within the library row header.

## 7. Dependencies

- Depends on the row-level delete behavior already landed.

## 8. Test plan

- Update focused view test to assert the row action uses the compact remove sign.

## 9. Rollout and rollback

- Immediate UI-only rollout.
- Rollback restores the text label.

## 10. Acceptance criteria

- The row action no longer says `Delete`.
- Clicking the remove sign still emits `remove_library_requested(library_id)`.

Plan approved -- implementation allowed: **Approved by user request in chat (2026-05-07)**

## 11. Implementation summary

Landed:

- Replaced the inline `Delete` label with a compact remove glyph on each library
  row.
- Kept the explicit tooltip (`Remove library`) for discoverability.
- Updated the focused view test to assert the new glyph while preserving the
  existing remove signal behavior.
