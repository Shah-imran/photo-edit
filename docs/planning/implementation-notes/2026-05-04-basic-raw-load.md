# 2026-05-04 -- Basic RAW load (R1)

Slice owner: PhotoEdit team  
Status: **DONE**  
Depends on: P1 float32 linear pipeline (`docs/planning/implementation-notes/2026-05-04-float32-linear-pipeline.md`)

## Problem and goal

**Problem.** Users cannot open camera RAW files; Open/Import dialogs and folder import only listed raster formats.

**Goal.** Load common RAW extensions through **rawpy** / LibRaw into the existing `LinearImage` contract (float32 linear-light sRGB primaries). Library thumbnails stay responsive via embedded previews when possible.

**Non-goals.** Adobe DCP camera profiles, Lensfun lens corrections, custom WB UI, dual-illuminant tuning, or HDR merge -- separate slices (R2+).

## Design

- **`src/utils/image_extensions.py`** -- single source for `STANDARD_IMAGE_EXTENSIONS`, `RAW_IMAGE_EXTENSIONS`, `ALL_IMAGE_EXTENSIONS`, `is_raw_path()`, `open_image_file_dialog_filter()`.
- **`src/services/raw_service.py`** -- `load_linear()` full demosaic via `postprocess(output_bps=16, use_camera_wb=True, output_color=sRGB)`; treat uint16 output as sRGB-encoded and apply `srgb_to_linear`. `thumbnail_linear()` tries `extract_thumb()` (JPEG / BITMAP), else `half_size=True` postprocess then resize.
- **`ImageService`** -- optional injectable `RawService`; `load_image` dispatches on `is_raw_path`; `load_preview_thumbnail()` uses fast RAW path for library; `get_image_info` uses `raw.sizes` for RAW.
- **Dialogs** -- `ImageController.open_image`, `LibraryView._import_images`, `MainWindow._import_images` use `open_image_file_dialog_filter()`.
- **`FileService.IMAGE_EXTENSIONS`** -- `ALL_IMAGE_EXTENSIONS` so folder import picks up RAW files.

## Tests

- `test_image_extensions.py`, `test_raw_service.py` (mocked `rawpy.imread`), `test_image_service_raw.py` (mocked `RawService`), `test_file_service.py` extended for `.nef`.

## Acceptance

- [x] Open/Import accepts RAW extensions; library folder scan includes RAW.
- [x] Full load and thumbnail path covered by unit tests; full suite green.
- [x] No new Pipfile dependency (`rawpy` already present).

## Implementation summary

Landed: `image_extensions.py`, `raw_service.py`, `ImageService` wiring, dialog + `FileService` updates, library uses `load_preview_thumbnail`. **279** tests passing (`pytest --ignore=tests/performance`). Manual check: open a real `.cr2`/`.nef` on a machine with LibRaw support.

## Approval

Plan approved by starting implementation in-session (2026-05-04).
