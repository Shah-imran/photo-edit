# Test suite audit (2026-10-17)

Related: [../TESTING.md](../TESTING.md),
[PERFORMANCE_OVERHAUL.md](PERFORMANCE_OVERHAUL.md).

## 1. Why audit

Line coverage was already 90% (1,585 test cases, 22k lines of tests), yet
the performance overhaul found serious bugs on covered lines that no test
caught:

| Bug | Why tests missed it |
|---|---|
| Any render slower than 1 s was silently discarded | Worker tests used tiny images that finish in milliseconds |
| Photo hand-off to workers ran on the UI thread and could lose the first render | Tests waited, then checked "a proxy exists" |
| Crop overlay erased the photo to black inside the crop box | Overlay tests checked rectangle math, never pixels |
| 24 MP float conversions and full renders on the UI thread | No test measured UI-thread time |
| "100%" zoom showed the preview, not the photo, after any edit | Zoom tests checked the factor, not what reached the screen |

The suite ran the code but asserted the wrong things.

## 2. Findings

1. **Testing a path the app doesn't run.** 147 of 150 controller tests
   build `ImageController(use_threading=False)`, a synchronous fallback
   the app never uses (it always threads). The production path had a
   handful of tests built from hand-rolled fake workers.
2. **Tests whose names promise more than they check.** e.g.
   `test_vibrance_increase_grows_low_saturation_more` and
   `test_contrast_increase_widens_distribution_in_srgb` only asserted the
   output shape; `test_full_resolution_processing_time` only asserted the
   worker existed; `test_ui_responsiveness_during_processing` only checked
   that `zoom_in()` didn't raise; `test_reset_adjustments_keyboard` and
   `test_fit_to_window` asserted nothing.
3. **Constructor-only tests** (`assert service is not None`): cannot fail.
4. **Wall-clock tests mixed into the default run**, some with assertions
   that depend on machine load (`processing_count < 20`), failing
   intermittently and under coverage.
5. **Misfiled and duplicated tests.** "Debouncing performance" tests were
   behaviour tests (call counts) and the only coverage of debouncing;
   three proxy "performance" tests duplicated unit tests.
6. **Heavy coupling to private attributes** in UI and controller tests
   (`test_main_window.py` alone: 277 private references), so refactors
   break tests without behaviour changing, while behaviour bugs pass.
7. **No visual regression and no real-RAW coverage.** Nothing decoded a
   real camera file or compared rendered output.
8. **Tests for dead code.** `src/models/project_model.py` and
   `src/models/adjustment_layer.py` are not imported anywhere in `src/`
   (30 tests).

## 3. Changes made

- **Tiers and markers** (`pyproject.toml`, `tests/conftest.py`):
  `integration` (real threads/files/MainWindow), `perf` (all of
  `tests/performance/` plus stage budgets; skipped automatically under
  coverage), `raw` (needs `test_images/`).
- **Outcome tests on the production path**:
  `tests/support/inline_worker.py` runs the real `ProcessingWorker`
  pipeline without a thread (`ImageController(worker_factory=...)`).
  `test_image_controller_pipeline.py` checks what reaches the screen:
  edit/release, undo/redo pixels, step order, restore, display-only mask
  preview, crop output size, full-resolution detail on zoom.
- **Responsiveness**: `tests/integration/test_responsiveness.py` (UI-thread
  time per call on 24 MP) and `test_main_window_responsiveness.py` (a full
  session through the real window under the stall watchdog; replaces
  `tests/performance/test_integrated_performance.py`).
- **Pixel tests for overlays**: `test_tool_overlays_rendering.py` renders
  the view and reads pixels (fails on the old crop overlay).
- **Visual regression on real RAWs**: `tests/integration/test_raw_golden.py`
  renders two CR3s with a fixed 14-adjustment recipe and compares with
  goldens in `tests/fixtures/golden/`; both the Numba and NumPy paths
  match.
- **Kernel parity**: `test_kernel_parity.py`, `test_pixel_kernels.py`.
- **Stage time budgets**: `tests/performance/test_stage_budgets.py`.
- **Fixed** the shape-only and assert-free tests listed above; **removed**
  constructor-only tests and the duplicate proxy tests; **moved**
  debounce behaviour tests into `tests/unit/test_processing/test_debouncer.py`.
- **Regression tests** for every bug in section 1.

## 4. Next steps

Done 2026-10-17 (after the first pass):
- **Synchronous controller path retired.** `use_threading=False` now runs
  the production path with `SynchronousProcessingWorker`
  (`src/processing/synchronous_worker.py`); ~230 lines of duplicate
  synchronous flows removed from `ImageController`. The 147 non-threaded
  controller tests now exercise the code the app runs.
- **One develop pipeline** (`src/processing/pipeline.py`) for every render
  entry point, pinned by `tests/unit/test_processing/test_pipeline.py`.
- **Per-stage RAW goldens** + export round trip
  (`tests/integration/test_raw_stage_goldens.py`).
- **UI placement checks** as geometry (`tests/ui/test_tool_drawer.py`).
- **Windows Delete from Disk** fixed.

Still open:
1. **Remove the unused command classes** `AdjustmentCommand`,
   `CombinedAdjustmentCommand`, `ImageStateChangeCommand` (nothing in the
   app uses them now). First move their stage-ordering tests (crop after
   straighten, mask before crop, healing before exposure) to
   `test_pipeline.py`, then delete the classes and the rest of their tests.
2. **Decouple UI tests from private fields**: drive widgets through their
   public signals and read results through public accessors.
3. **Decide on dead modules** (`project_model.py`, `adjustment_layer.py`):
   delete with their tests, or wire them in.

## 5. How to run

```bash
pytest                      # everything (perf skipped under coverage)
pytest -m "not perf"        # skip wall-clock budgets
pytest -m perf              # only time budgets
pytest -m integration       # real threads / files / full window
PHOTOEDIT_UPDATE_GOLDEN=1 pytest tests/integration/test_raw_golden.py  # re-approve looks
PHOTOEDIT_DISABLE_NUMBA=1 pytest   # run the NumPy fallback path
```
