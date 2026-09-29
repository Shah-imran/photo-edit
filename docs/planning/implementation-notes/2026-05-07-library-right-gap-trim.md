# 2026-05-07 -- Library right-gap trim

Related plan: [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) section 4 ; follow-up to the library accordion UI slices from 2026-05-07

## 1. Problem and goal

The library explorer still shows visible dead space on the right side of the
image area. The goal is to remove that extra gap so the image column/grid sits
flush with the usable panel width.

## 2. Current behavior

- `LibraryView` uses an outer `QVBoxLayout` with symmetric `8px` margins.
- The image explorer content already has zero inner content margins, so the
  remaining visible right-side gap is most likely coming from the panel wrapper.

## 3. Proposed design

- Remove the right outer margin from `LibraryView` while keeping the existing
  top/left/bottom spacing.
- Leave behavior and controller wiring unchanged.

## 4. API and data contracts

- No API or signal changes.

## 5. Nuances and failure modes

- Keep left/top/bottom spacing so the dock does not become visually cramped.
- Do not alter selection, accordion, or thumbnail behavior.

## 6. UI and reskin impact

- Presentation-only spacing adjustment in the library dock.

## 7. Dependencies

- No code dependencies beyond the current library view.

## 8. Test plan

- Run focused library view and main-window UI tests to confirm no behavior
  regressions.

## 9. Rollout and rollback

- Immediate UI-only rollout.
- Rollback restores the previous right margin.

## 10. Acceptance criteria

- The right-side gap in the library image explorer is removed or materially
  reduced.
- Focused library UI tests still pass.

Plan approved -- implementation allowed: **Approved by user request in chat (2026-05-07)**

## 11. Implementation summary

Landed:

- Removed the outer right margin from `LibraryView` so the library image
  explorer uses the available dock width more tightly.
- Left the rest of the library accordion behavior unchanged.
- Focused library view and main-window UI tests still pass.
