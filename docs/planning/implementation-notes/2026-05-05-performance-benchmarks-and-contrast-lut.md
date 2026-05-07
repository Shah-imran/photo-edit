# 2026-05-05 -- Performance benchmarks and contrast LUT

## Problem

Performance work needed a repeatable baseline. Logs were useful, but they were
hard to compare after each implementation phase. The existing performance tests
also still used some PIL-era assumptions that no longer matched the `LinearImage`
pipeline.

## Implementation

- Added `src.benchmarking.photo_performance`, a JSON benchmark harness with:
  - `smoke` profile for tests,
  - `quick` profile for routine interactive/quality timing,
  - `full` profile for 26MP-style full-resolution timing.
- Reports are written to `logs/benchmarks/` plus `latest_<profile>.json`.
- Added report comparison support via `--compare-to`.
- Added unit tests for benchmark schema/comparison and performance smoke tests.
- Updated legacy performance tests to use `LinearImage` arrays.
- Optimized contrast with cached sRGB transfer lookup tables.

## Benchmark Snapshot

Quick profile before the contrast LUT:

- `apply_contrast_interactive`: ~33.94ms
- `apply_contrast_quality`: ~199.32ms

Quick profile after the contrast LUT:

- `apply_contrast_interactive`: ~16.48ms
- `apply_contrast_quality`: ~86.97ms

Full profile after the contrast LUT:

- `apply_exposure_full`: ~186ms
- `apply_contrast_full`: ~1618ms

## How To Run

```powershell
.\.venv\Scripts\python.exe -m src.benchmarking.photo_performance --profile quick
.\.venv\Scripts\python.exe -m src.benchmarking.photo_performance --profile full
.\.venv\Scripts\python.exe -m src.benchmarking.photo_performance --profile quick --compare-to logs\benchmarks\some_previous_report.json
```

## Next

Full-image contrast is much faster than before but still too slow for
Lightroom-style interaction at 26MP. The next phase should avoid whole-image
interactive rendering entirely by adding viewport-aware crop/tile rendering.
