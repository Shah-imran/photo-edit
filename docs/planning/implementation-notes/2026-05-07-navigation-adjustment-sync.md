# 2026-05-07 -- Navigation adjustment sync

Related plan: [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) sections 4, 5.1 ; follow-up to [2026-05-07-dock-state-and-image-adjustment-persistence.md](2026-05-07-dock-state-and-image-adjustment-persistence.md)

## 1. Problem and goal

Adjustment persistence now works across close/reopen, but navigation still has a
gap: library switches can bypass the current-image persistence step because the
view signal is wired directly to the library controller.

The goal is to make adjustment-state sync happen consistently whenever the user
moves between images or libraries, so returning to a previously edited image
restores its own saved adjustments.

## 2. Current behavior

- Image selection already persists the current image before loading the next one.
- Library selection still goes straight from `LibraryView.library_selected` to
  `LibraryController.select_library`.
- Create/remove library actions also do not explicitly flush current-image
  adjustments before changing library context.

## 3. Proposed design

- Route library-selection handling through `MainWindow`.
- Persist current-image adjustments before:
  - switching libraries,
  - creating a library,
  - removing a library.
- Keep restore behavior unchanged: selecting an image still loads that image's
  own saved adjustment payload.
- Add focused UI coverage for image-to-image switching and cross-library
  switching.

## 4. API and data contracts

- No new persisted schema fields.
- No signal signature changes.

## 5. Nuances and failure modes

- Persist must happen before library contents rebuild, otherwise the current
  image can lose its last unsaved edits.
- Removing a library must still avoid crashing if the currently displayed image
  belonged to that library.

## 6. UI and reskin impact

- No visual changes.
- Navigation behavior becomes more consistent.

## 7. Dependencies

- Depends on the existing adjustment-persistence slice.

## 8. Test plan

- Add UI test for switching between two images and restoring each image's saved
  adjustments.
- Add UI test for switching libraries, then returning to the original image and
  restoring its saved adjustments.
- Re-run focused main-window UI tests.

## 9. Rollout and rollback

- Immediate behavior-only rollout.
- Rollback restores the previous direct library-selection wiring.

## 10. Acceptance criteria

- Adjustments are persisted when moving from one image to another.
- Adjustments are persisted when switching away to another library and restored
  when returning to the original image.
- Focused UI tests pass.

Plan approved -- implementation allowed: **Approved by user request in chat (2026-05-07)**

## 11. Implementation summary

Landed:

- Routed library selection through `MainWindow` so current-image adjustments are
  persisted before switching library context.
- Added the same persistence flush before create/remove library actions.
- Kept image-selection restore behavior intact, so returning to an image restores
  that image's own saved adjustment payload.
- Added focused UI coverage for switching between images and for switching away
  to another library and then back to the original edited image.
- Focused main-window and broader persistence/library/controller test suites
  pass.
