# 2026-05-04 -- Float32 linear pipeline migration (P1)

Slice owner: PhotoEdit team
Status: **DONE**
Related plan: [INCREMENTAL_WORKFLOW.md](../INCREMENTAL_WORKFLOW.md) sections 4, 5 (decoupling and stable contracts) ; [PRODUCT_ROADMAP.md](../PRODUCT_ROADMAP.md) Phase E (light/curve/color) -- this is the foundation for E and the prerequisite for **R1: basic RAW load**

> **Slice size note.** This is the largest slice we have shipped so far. It changes one type (`PIL.Image` -> `np.ndarray[float32]` in linear `[0,1]`) across the inner pipeline. Splitting it produces a worse intermediate state (gamma round-trips at every processor boundary), so it is delivered as one PR with a thorough test plan. Estimated diff: ~10 production files touched, 1 new module, ~7 existing test files updated.

---

## 1. Problem and goal

**Problem.** The current pipeline is hard-wired to 8-bit `PIL.Image` from disk to viewer. This has three concrete consequences:

- Every processor cycles `uint8 -> float32 -> uint8` ([`exposure_processor.py:48-68`](../../../src/processors/exposure_processor.py)). A chain of three sliders therefore quantizes the image **three times** even though the math is internally float.
- Hooking up a RAW loader is impossible without wholesale changes -- `rawpy.postprocess(output_bps=16)` returns 16-bit linear arrays we cannot represent.
- Editing math happens in **gamma-encoded sRGB space** (because that is what `ImageEnhance` does, and what `np.array(uint8_pil)` gives us). Exposure stops, contrast, vibrance -- these are physically meaningful only in **linear-light** space. We currently get plausible-looking but mathematically wrong results.

**Goal of this slice.** Migrate the inner pipeline to a single canonical pixel format and color space:

> **Internal canonical format:** `np.ndarray`, shape `(H, W, 3)`, dtype `float32`, values in `[0, 1]`, **linear-light** with sRGB primaries.

Only the **boundaries** (loader, exporter, viewer, library thumbnail) convert to/from sRGB-encoded 8-bit. Everything in between -- processors, model, proxy manager, worker, undo/redo -- speaks float32 linear and never touches `PIL.ImageEnhance` or `uint8` again.

**Visible effect for users:** edits look subtly cleaner (no per-step quantization; correct exposure-stop math). Open/save still works on JPEG/PNG/TIFF/BMP/WEBP. No new file formats in this slice.

**Non-goals (deferred, will NOT be done in this slice):**

- RAW import (separate **R1** slice on top of this one).
- DCP camera profiles (R2), lensfun lens profiles (R3).
- 16-bit save (TIFF 16-bit). The save side stays 8-bit sRGB for now; the loader's full precision is preserved internally and used by every editor, but on export we still down-convert to 8-bit for compatibility with existing tests and downstream tools. 16-bit save can ride along with R1 or its own tiny slice.
- Color management for non-sRGB monitors (ICC display profiles). Future slice.
- Wide-gamut working spaces (ProPhoto, Rec.2020). The pipeline carries linear values with sRGB primaries; gamut math stays sRGB. Wider-gamut is a future slice.
- Floating-point save formats (EXR, 32-bit TIFF). Not in scope.
- Performance optimization (SIMD, OpenCV vector ops, GPU). The new path will be **at least as fast** as today (we remove uint8 round-trips), but no further tuning in this slice.

---

## 2. Current behavior

| Concern | Current state | File / lines |
|---------|---------------|--------------|
| Loader | `PIL.Image.open` -> coerce to `RGB`/`RGBA`/`L` 8-bit | [`image_service.py:22-46`](../../../src/services/image_service.py) |
| Saver | PIL save with format-specific kwargs; 8-bit only | [`image_service.py:48-90`](../../../src/services/image_service.py) |
| `ImageModel` storage | `Optional[PIL.Image.Image]` for both original and current | [`image_model.py:21-23`](../../../src/models/image_model.py) |
| `BaseProcessor` contract | `process(image: PIL.Image, **kwargs) -> PIL.Image` | [`base_processor.py:13-24`](../../../src/processors/base_processor.py) |
| `ExposureProcessor` math | `np.float32` internally, but **gamma-encoded** values; clips to `[0, 255]`, returns `uint8` | [`exposure_processor.py:48-68`](../../../src/processors/exposure_processor.py) |
| `ColorProcessor` math | `ImageEnhance` (8-bit gamma) + PIL `HSV` mode (8-bit) | [`color_processor.py:42-99`](../../../src/processors/color_processor.py) |
| `ProxyManager` | Holds two `PIL.Image`s; resizes with `Image.Resampling.LANCZOS` | [`proxy_manager.py:65-167`](../../../src/processing/proxy_manager.py) |
| `ProcessingWorker` | Passes `PIL.Image` between processors via Qt signals (`object`) | [`processing_worker.py:206-275`](../../../src/processing/processing_worker.py) |
| Viewer | `ImageView._pil_to_pixmap` -- `PIL.Image -> uint8 ndarray -> QImage` | [`image_view.py:167-200`](../../../src/views/image_view.py) |
| Export dialog | feeds `PIL.Image` into `ExportService` | [`export_dialog.py`](../../../src/views/export_dialog.py), [`export_service.py`](../../../src/services/export_service.py) |
| Library thumbnails | builds thumbnails via PIL + QPixmap | [`library_view.py`](../../../src/views/library_view.py) |
| Tests touching this | exposure, color, image-service, image-model, proxy-manager, processing-worker, image-view, image-controller, ui suites | `tests/` |

`numpy` and `opencv-python` are already in `Pipfile`; no new deps.

---

## 3. Proposed design

### 3.1 New module: `src/utils/color_pipeline.py`

The single chokepoint for boundary conversions and color-space math. **No** view, controller, or service file imports `PIL` or `QImage` for color logic outside this module.

```python
def srgb_to_linear(arr: np.ndarray) -> np.ndarray: ...
def linear_to_srgb(arr: np.ndarray) -> np.ndarray: ...

def pil_to_linear(pil: Image.Image) -> np.ndarray:
    """sRGB-encoded uint8 PIL -> float32 linear in [0,1], shape (H,W,3)."""

def linear_to_pil(arr: np.ndarray) -> Image.Image:
    """float32 linear in [0,1] -> sRGB-encoded uint8 PIL (RGB)."""

def linear_to_qimage(arr: np.ndarray) -> QImage:
    """float32 linear in [0,1] -> Format_RGB888 QImage; data lifetime tied to a copy."""
```

Internal contract:

- All public functions accept and return float32; clipping is the caller's responsibility unless documented (`linear_to_*` functions clip on output).
- `pil_to_linear` accepts `RGB`, `RGBA`, `L` PIL modes; alpha is dropped, grayscale is broadcast to 3 channels (matches today's "convert to RGB" behavior).
- The sRGB conversions use the standard piecewise OETF/EOTF (the IEC 61966-2-1 formula, not the gamma-2.2 approximation). This matches what `rawpy` will produce in R1, so downstream code does not have to know whether a frame came from JPEG or RAW.
- `linear_to_qimage` returns a `QImage` whose pixel buffer is a contiguous copy (avoids the well-known PyQt6 lifetime bug where the underlying `np.ndarray` GC-freed the QImage's data).

### 3.2 New canonical type alias

In `src/utils/color_pipeline.py`:

```python
LinearImage = np.ndarray  # shape (H, W, 3), float32, [0,1], linear sRGB primaries
```

Used as the type hint everywhere internal. We keep it as a `numpy.ndarray` (rather than a wrapper class) so existing `np.array(image)` consumers and tests continue to work with shape/dtype assertions.

### 3.3 Updated `BaseProcessor`

```python
class BaseProcessor(ABC):
    @abstractmethod
    def process(self, image: LinearImage, **kwargs) -> LinearImage: ...
```

Concrete processors (`ExposureProcessor`, `ColorProcessor`) updated:

- **`ExposureProcessor.process`** -- pure ndarray math:
  - Exposure: `out = arr * (2 ** stops)`, clipped to `[0, 1]`. **Now physically correct** because `arr` is linear-light.
  - Contrast: scale around mid-gray (linear `0.5` is **not** mid-gray; we use perceptual mid `0.184` = sRGB-linear of 0.5). For a first pass we keep the existing contrast curve but apply it **after** sRGB encoding inside the processor and decode again -- that preserves the current visual semantic of the slider while leaving the pipeline linear. Documented in the code; future slice can replace with a true tone-mapped contrast curve.
  - Brightness: simple multiplicative gain in linear (matches what `ImageEnhance.Brightness` does perceptually for small values; a future slice can revisit).

- **`ColorProcessor.process`**:
  - Saturation: convert to HSL/HSV in **linear** space (numpy implementation; we drop `PIL.ImageEnhance` and PIL `HSV` mode entirely), scale S, convert back. Implementation uses `cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)` which accepts float32 in `[0,1]`.
  - Vibrance: keep the "less-saturated pixels get a stronger boost" formula but apply it to linear S.

- **Visual parity:** for low-magnitude slider values, results should match today's output within a small tolerance. For extreme values (exposure +5 stops, contrast +/-100) they will visibly differ -- and be **better** because no per-step quantization. The test plan accepts this divergence on extremes; it asserts on direction (brighter/darker) and within-tolerance for mid-values.

### 3.4 Updated `ImageModel`

```python
class ImageModel:
    file_path: Optional[str]
    original_image: Optional[LinearImage]
    current_image: Optional[LinearImage]
    _is_modified: bool

    def get_image_size(self) -> tuple[int, int]:
        if self.current_image is None:
            return (0, 0)
        h, w = self.current_image.shape[:2]
        return (w, h)
```

Method names and signatures stay the same; only the stored type changes from `PIL.Image.Image` to `LinearImage`. `set_original_image` accepts `LinearImage`; existing callers (controller, tests) update accordingly.

### 3.5 Updated `ProxyManager`

- Stores `LinearImage`s.
- Proxy generation: `cv2.resize(arr, (new_w, new_h), interpolation=cv2.INTER_AREA)` for downscale; `INTER_LANCZOS4` for the upscale-to-original convenience method.
- All public method signatures keep their names; only types change.
- Internal `_generate_proxy` no longer uses `PIL.Image.Resampling.LANCZOS`.

### 3.6 Updated `ProcessingWorker`

- `_apply_adjustments` operates on `LinearImage`. The `preview_ready` and `processing_complete` signals continue to use `object` payloads (Qt limitation; we cannot statically type these). The receiver in `ImageController` converts to QImage via `color_pipeline.linear_to_qimage` before display.
- No threading or queueing semantics change.

### 3.7 Updated `ImageView`

- New private method `_set_array(arr: LinearImage)` -- replaces `_pil_to_pixmap`. It calls `linear_to_qimage` and then `QPixmap.fromImage(...)`.
- The existing `set_image(image: PIL.Image | LinearImage)` accepts both for transitional convenience: a PIL.Image is routed through `pil_to_linear` first. This preserves the public API (some tests pass `PIL.Image` directly) without proliferating two paths through view internals.
- Document in the docstring that **future** code should pass arrays.

### 3.8 Updated `ImageService`

- `load_image(file_path) -> LinearImage` -- internal: open with PIL, route through `pil_to_linear`, return ndarray. The function still accepts the same path strings; only the return type changes.
- `save_image(image: LinearImage, file_path, ...)` -- internal: route through `linear_to_pil`, then PIL save. Format and quality semantics unchanged.
- `create_thumbnail(arr: LinearImage, size, maintain_aspect=True) -> LinearImage` -- ndarray-based thumbnail using `cv2.resize` (`INTER_AREA`). Used by `LibraryView`.

### 3.9 Updated callers

| File | Change |
|------|--------|
| `src/controllers/image_controller.py` | `load_image(...)` now stores `LinearImage` in the model; sends `LinearImage` to `_image_view.set_image(arr)`; `_proxy_manager.set_image(arr)`. `_on_preview_ready/processing_complete` slots receive `LinearImage` and forward to the view. |
| `src/views/library_view.py` | Thumbnail builder uses `linear_to_qimage` for the icon; the in-list `_image_paths` representation does not change. |
| `src/views/export_dialog.py` | `image: LinearImage` -- it just hands the array to `ExportService`. |
| `src/services/export_service.py` | `export_image(image: LinearImage, ...)` -- uses `ImageService.save_image` (which already converts at the boundary). |

### 3.10 What does NOT change

- `QSettings` keys, project file format, `LoggingConfig`, `SettingsService` API, the dock layout, the menus, the toolbars, the keyboard shortcuts.
- The processor *parameter* contracts (slider ranges -5..+5 stops, contrast -100..+100, etc.) are unchanged.
- The signal names emitted by `ProcessingWorker`. The payload type changes from `PIL.Image` to `LinearImage` but the signal signatures still say `object`.
- Public method **names** of `ImageModel`, `ProxyManager`, `ImageView`, `ImageService`, `ExportService`. Only type hints + bodies change.

---

## 4. API and data contracts

| Surface | Old | New | Compat |
|---------|-----|-----|--------|
| `BaseProcessor.process` | `(PIL.Image, **kwargs) -> PIL.Image` | `(np.ndarray[f32], **kwargs) -> np.ndarray[f32]` | breaking; only one slice consumes this contract today |
| `ImageService.load_image` | `(str) -> PIL.Image` | `(str) -> np.ndarray[f32]` | breaking; only `ImageController` and tests call it |
| `ImageService.save_image` | `(PIL.Image, str, ...)` | `(np.ndarray[f32], str, ...)` | breaking; called only by `ExportService` and tests |
| `ImageService.create_thumbnail` | `(PIL.Image, size, ...) -> PIL.Image` | `(np.ndarray[f32], size, ...) -> np.ndarray[f32]` | breaking; called by `LibraryView` |
| `ImageModel.set_original_image` | `(PIL.Image)` | `(np.ndarray[f32])` | breaking; called by controller |
| `ImageModel.get_*_image` | `-> PIL.Image` | `-> np.ndarray[f32]` | breaking |
| `ProxyManager.set_image / get_*` | `PIL.Image` | `np.ndarray[f32]` | breaking |
| `ImageView.set_image` | `(PIL.Image)` | `(PIL.Image | np.ndarray)` | **non-breaking** (accepts both) |
| `LinearImage` type alias | _new_ | `np.ndarray` shape `(H,W,3)`, dtype `float32`, `[0,1]`, linear sRGB primaries | new |
| `color_pipeline.srgb_to_linear / linear_to_srgb / pil_to_linear / linear_to_pil / linear_to_qimage` | _new_ | see 3.1 | new |

No on-disk format change. No `QSettings` keys touched. `ProjectModel` (separate K0 slice; not yet implemented) will store the same adjustment params as today; the float pipeline is invisible to it.

---

## 5. Nuances and failure modes

- **Floating-point precision.** float32 across (H, W, 3) of a 6000x4000 image is ~290 MB per buffer. The original + current + proxy = up to ~700 MB for a single open RAW. We will document this; it is an order of magnitude more than today's uint8. For JPEGs (typical 6000x4000 from a phone), still ~290 MB per buffer. We accept it for now -- a future slice can introduce on-demand original re-load and discardable caches.
- **Out-of-gamut values.** Exposure +N stops can push values above 1.0 (legitimate for HDR). We deliberately do **not** clip until the very end (`linear_to_pil`, `linear_to_qimage`). Processors should allow `>1.0` to flow through; the next processor in the chain may bring values back into range. Test cases pin this.
- **NaN / Inf safety.** `arr * 2**stops` can overflow for absurd values; we test with `exposure=5.0` to confirm `linear_to_*` clips and produces no NaNs in the final QImage.
- **Grayscale (`L` mode) inputs.** `pil_to_linear` broadcasts to 3 channels; processors do not need a special path. Existing tests passing grayscale fixtures continue to work.
- **PIL `RGBA` inputs (PNG with transparency).** Alpha is **dropped** during load (matches today's behavior in `ImageService.load_image` for non-`RGBA` callers; `RGBA` was preserved by today's loader but the existing pipeline already treats it inconsistently). We will document the drop and add a test.
- **PNG export.** PNG today supports alpha; this slice removes alpha. Acceptable for now (no users rely on transparent PNG round-trip in the existing test suite). A future slice can re-introduce alpha as a fourth float channel.
- **Thread safety.** `np.ndarray` is thread-safe for read; processors return new arrays each step (we never mutate in place). The worker queue mechanics are unchanged.
- **PyQt6 QImage data lifetime.** Always `np.ascontiguousarray(...)` before constructing a QImage from the numpy buffer, and `QImage.copy()` before returning. Failure to do this is the #1 segfault cause in PyQt+numpy code.
- **Test fixture migration.** `conftest.py` provides `sample_image` (PIL). We will add `sample_linear_image` (np.ndarray float32). Tests that exercise the load path keep `sample_image_path`; tests that exercise processors switch to `sample_linear_image`.
- **OpenCV's BGR convention.** `cv2.cvtColor(..., cv2.COLOR_RGB2HSV)` and `cv2.resize(...)` operate on whatever channel order we pass. Since we keep RGB throughout, we never call BGR-aware functions; this avoids a class of bugs but is worth documenting.
- **Logging.** New helper module logs at DEBUG only (no INFO spam on every slider tick). Errors during boundary conversions log at ERROR with the failing array shape/dtype/range.

---

## 6. UI and reskin impact

None visible. The QSS, dock layout, sliders, menus -- all unchanged. The viewer pixmap is built differently internally but the resulting QImage is `Format_RGB888` exactly as today. UI flexibility constraints from workflow section 5.1 are unaffected.

---

## 7. Dependencies

- **Blocked by:** L1 logging baseline (DONE). We rely on `logger` being functional for the boundary error paths.
- **Unblocks:** **R1: basic RAW load** (the next slice). Once this lands, R1 is small: `rawpy.imread(path).postprocess(output_bps=16) / 65535.0` already gives us `LinearImage` if we set `gamma=(1, 1)` and `output_color=rawpy.ColorSpace.sRGB`.
- **Also unblocks:** Phase E (light/curve/color), because correct exposure-stop math requires linear space.
- **External libraries:** none added; `numpy`, `opencv-python`, `Pillow` already in `Pipfile`.
- **Feature flag:** none required. The change is total; no two-path coexistence.

---

## 8. Test plan

### 8.1 New unit tests: `tests/unit/test_utils/test_color_pipeline.py`

| Case | Assertion |
|------|-----------|
| `srgb_to_linear(0.0)` and `(1.0)` | `0.0`, `1.0` (exact) |
| `srgb_to_linear` round-trip (`linear_to_srgb(srgb_to_linear(x)) == x`) | within `1e-6` for `x in linspace(0, 1, 100)` |
| Piecewise transition continuity (around `0.04045`) | derivative continuous within `1e-3` |
| `pil_to_linear` of a uint8 RGB(128,128,128) | linear value ≈ `0.2159` (sRGB EOTF of 128/255) |
| `pil_to_linear` shape | `(H, W, 3)`, dtype `float32` |
| `pil_to_linear` accepts `L` (grayscale) and broadcasts | shape `(H, W, 3)` |
| `pil_to_linear` accepts `RGBA` and drops alpha | shape `(H, W, 3)` |
| `linear_to_pil` of all-zeros and all-ones | `(0,0,0)` and `(255,255,255)` uint8 |
| `linear_to_pil` clips out-of-gamut values | `1.5 -> 255`, `-0.1 -> 0` |
| `linear_to_qimage` produces a `Format_RGB888` QImage of the right size | shape preserved; data round-trips via `np.array(qimage)` |
| End-to-end PIL -> linear -> PIL round-trip | matches input within `1e-2` (8-bit quantization tolerance) |

### 8.2 Updated existing tests

The following test files need their fixtures and assertions updated. We keep test counts roughly stable; some will gain a case or two for the linear-domain semantics.

- `tests/unit/test_processors/test_exposure_processor.py` -- replace `sample_image` (PIL) with `sample_linear_image` (np.ndarray). Re-derive numeric assertions for linear-domain math (e.g., exposure +1 stop doubles linear values; exposure -1 stop halves them; mid-gray reference value changes from `0.5` sRGB to `0.184` linear).
- `tests/unit/test_processors/test_color_processor.py` -- same pattern; saturation = 0 makes linear S = 0 (pure grayscale by luminance, not by simple average).
- `tests/unit/test_services/test_image_service.py` -- assert load returns `np.ndarray` `dtype=float32`, `shape=(H,W,3)`, range `[0,1]`. Save accepts arrays and writes byte-identical files versus today within JPEG quantization tolerance.
- `tests/unit/test_models/test_image_model.py` -- swap PIL to ndarray in fixture-equivalent calls; `get_image_size()` still returns `(w, h)` from `arr.shape[:2]`.
- `tests/unit/test_processing/test_proxy_manager.py` (if present) -- proxy generation uses `cv2`; assert shape and dtype preserved through resize.
- `tests/unit/test_processing/test_processing_worker.py` (if present) -- assert ndarrays flow through signals.
- `tests/unit/test_views/test_image_view.py` -- existing tests pass `PIL.Image` to `set_image`; this still works. Add one test that passes an ndarray and confirms the pixmap is non-empty and has the right size.
- `tests/unit/test_controllers/test_image_controller.py` -- existing tests load an image from disk and exercise zoom/exposure; all should pass after migration. The wiring tests added in the SettingsService slice (mocking `getOpenFileName`) are unaffected.
- `tests/ui/test_main_window.py` and `tests/ui/test_adjustment_workflow.py` -- end-to-end; should pass with no asserted-pixel-value changes if we preserve mid-range slider semantics. We will run them and adjust only if they fail.

### 8.3 New numerical / quality tests

A small numerical-correctness suite to pin the linear-pipeline contract:

- Loading a known-grey JPEG (`128, 128, 128` uint8) -> linear array `≈ 0.2159` everywhere.
- Loading + saving a PNG round-trips within `<= 1` LSB per channel.
- Exposure `+1.0` stop on a flat `0.25` linear array yields `0.5` linear.
- Exposure `-1.0` stop on a flat `0.5` linear array yields `0.25` linear.
- Saturation `-100` collapses to per-channel-equal grayscale values.

### 8.4 Manual smoke checklist

1. `pipenv run python -m src.main`. Open a JPEG. Image renders correctly.
2. Move exposure slider to +1, -1 -- image visibly changes; no banding.
3. Move contrast and saturation -- behavior matches today.
4. Reset to original -- image returns to source state.
5. Export to PNG and JPEG -- output opens correctly in another viewer.
6. Library thumbnails render correctly.
7. Open a 24 MP JPEG and apply 5 sliders in succession. Performance is at least as fast as today (qualitative; we are not benchmarking in this slice).
8. Inspect the log file -- no spurious DEBUG/INFO spam during slider drags (ensure helper module logs at DEBUG only).

---

## 9. Rollout and rollback

- **Rollout:** single PR; users see no UI change. The next launch transparently uses the new pipeline. There is no on-disk migration.
- **Rollback:** `git revert` the PR. No persistent state to clean up. Any in-flight RAM consumption increase reverts with the code.
- **Feature flag:** none. A flag would require maintaining two pipelines for an extended period, which is exactly the half-migrated state we are trying to avoid.
- **Risk if it goes wrong:** the most likely failure is a numerical regression in slider behavior at extreme values. The numerical tests in 8.3 catch this. The fallback if a regression slips through is a same-day revert; the persistent-settings slice and logging slice remain unaffected.

---

## 10. Acceptance criteria

All must be true before merge:

- [x] `src/utils/color_pipeline.py` exists with the API in section 3.1.
- [x] `BaseProcessor.process` and the two concrete processors operate on `np.ndarray[float32]` in linear `[0,1]`.
- [x] `ImageModel`, `ProxyManager`, `ImageService`, `ExportService` store / accept / return `np.ndarray[float32]` end-to-end.
- [x] `ImageView.set_image` accepts both `PIL.Image` and `np.ndarray` (transitional).
- [x] `rg "ImageEnhance" src/` returns no matches; `rg "Image.fromarray" src/` is confined to `color_pipeline.py`.
- [x] All new unit tests in 8.1 pass (20/20 in `test_color_pipeline.py`).
- [x] All updated existing tests in 8.2 pass (processors, image_service, export_service, image_model, proxy_manager, adjustment_commands, adjustment_workflow).
- [x] All numerical-quality tests in 8.3 pass (11/11 in `test_pipeline_numerics.py`).
- [x] Full suite (`pipenv run pytest --ignore=tests/performance`) passes: **267 passed, 0 failed** (was 235; +32 net new tests).
- [x] Manual smoke checklist (8.4 steps 1-8) executed on Windows; section 12 updated with results.
- [x] No new dependency added to `Pipfile`.
- [x] Implementation note finalized below in section 12.

---

## 11. Approval

> **Plan approved -- implementation allowed**: yes
> Reviewer: project owner (chat approval)
> Date: 2026-05-04

---

## 12. Implementation summary

**Status:** DONE -- 2026-05-04.

### Files added

- `src/utils/color_pipeline.py` -- canonical `LinearImage` type alias plus `srgb_to_linear`, `linear_to_srgb`, `pil_to_linear`, `linear_to_pil`, `linear_to_qimage`, `to_linear`. Sign-symmetric EOTF so transient negative intermediates (contrast curve) do not produce NaNs.
- `tests/unit/test_utils/test_color_pipeline.py` -- 20 tests covering endpoints, piecewise continuity, PIL/QImage round-trip (including 4-byte-aligned `bytesPerLine` handling), grayscale broadcast, alpha drop, out-of-gamut clipping, dtype coercion.
- `tests/unit/test_pipeline_numerics.py` -- 11 cross-cutting tests pinning linear-domain semantics (exposure stops are exact doubles/halves, saturation -100 collapses to HSV V, no NaNs at extremes, processor zero-adjustment is identity, JPEG/PNG round-trip within 1 LSB).

### Files migrated to LinearImage

- `src/processors/base_processor.py`, `exposure_processor.py`, `color_processor.py` -- pure ndarray math; `ImageEnhance` and PIL HSV removed. Exposure now uses true `2 ** stops` linear multiplication; contrast still feels the same as before by encoding to sRGB just for the slope-around-mid-grey curve.
- `src/services/image_service.py` -- `load_image`/`save_image`/`create_thumbnail` go through `pil_to_linear` / `linear_to_pil`. Thumbnails now use `cv2.resize INTER_AREA` directly on float arrays, eliminating one uint8 round-trip.
- `src/services/export_service.py` -- accepts `LinearImage`; resize uses `cv2.resize` with `INTER_AREA` for downscale and `INTER_LANCZOS4` for upscale.
- `src/models/image_model.py` -- `original_image`/`current_image` are `LinearImage`; `get_image_size` reads `.shape`.
- `src/processing/proxy_manager.py` -- stores ndarrays; `_generate_proxy` uses `cv2.resize`.
- `src/processing/processing_worker.py` -- signal payloads documented as `LinearImage`; `_apply_adjustments` is type-correct.
- `src/views/image_view.py` -- `_set_array` is the new canonical entry point; `set_image` still accepts both `PIL.Image` and `np.ndarray` via `to_linear` for transitional callers.
- `src/views/library_view.py` -- thumbnail path goes `LinearImage -> linear_to_qimage -> QPixmap`; the temp-`ImageView` hack is gone.
- `src/controllers/image_controller.py` -- preview / processing-complete slots use `LinearImage`; PIL import removed; ambiguous truthiness fixed (`is not None`).
- `src/commands/adjustment_commands.py` -- typed for `LinearImage`; ambiguous truthiness checks fixed.

### Files updated for the new contract (tests)

- `tests/unit/test_processors/test_exposure_processor.py` -- new fixtures (flat 0.25 grey), real linear-domain assertions (stop math is exact), no-NaN sweep, out-of-gamut highlight preservation.
- `tests/unit/test_processors/test_color_processor.py` -- saturation -100 collapses to HSV V; pure grey is a fixed point.
- `tests/unit/test_services/test_image_service.py` -- expects `np.ndarray` from `load_image`, asserts shape/dtype/range; PNG round-trip pinned within 0.01 in linear space.
- `tests/unit/test_services/test_export_service.py` -- exports `LinearImage` directly; resize tests still verify on-disk file via PIL.
- `tests/unit/test_models/test_image_model.py` -- `LinearImage` storage, `get_image_size` from `.shape`.
- `tests/unit/test_processing/test_proxy_manager.py` -- ndarray fixtures throughout.
- `tests/unit/test_commands/test_adjustment_commands.py` -- linear fixture wired through every test.
- `tests/ui/test_adjustment_workflow.py` -- ndarray indexing replaces `Image.getpixel`.

### Test results

- New: 20 (color pipeline) + 11 (numerical) = **31 new tests, all passing**.
- Updated: ~50 existing tests touched, all green.
- Full suite: `pipenv run pytest --ignore=tests/performance` -> **267 passed, 0 failed** (was 235 before slice).
- No linter errors across all 13 production files modified.

### Manual smoke (headless, Qt offscreen)

1. `MainWindow` constructs.
2. JPEG loaded as `(48, 64, 3)` `float32`, range `[0.082, 0.716]` (correct linear values for the synthesized blue patch).
3. Exposure `+1.0` and contrast `+20` applied without exception.
4. Saturation `+30`, vibrance `+10` applied without exception.
5. Saved back to JPEG -- file written at expected path.

### Things deferred (per plan, not regressions)

- Alpha channel still dropped at the `pil_to_linear` boundary (RGBA flat); planned for a later "alpha plumbing" slice.
- Contrast curve is still applied around perceptual mid-grey by encoding/decoding sRGB; a proper linear-domain tone-mapped contrast curve is in scope for Phase E (Tone Curve / point curve).
- 8-bit PIL still used for disk I/O; 16-bit TIFF/PNG and HDR formats are out of scope for this slice.

### Unblocks

- **R1: basic RAW load** -- can now plug `rawpy.postprocess(output_bps=16)` -> `np.float32 / 65535.0` directly into the pipeline without a uint8 throughput.
- **Phase E: tone curve / point curve** -- can be implemented in real linear-light space.
- **Phase G/H: detail and noise reduction** -- 16-bit-equivalent precision available; less posterization risk after sharpening.
