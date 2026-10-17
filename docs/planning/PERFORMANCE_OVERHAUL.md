# Performance and responsiveness overhaul

Goal: PhotoEdit should feel **stable, smooth and professional**. A slider
drag, an undo, opening a photo, or switching tools must never freeze the
window, and every new feature must meet a measured time budget before it is
committed.

Related: [PRODUCT_ROADMAP.md](PRODUCT_ROADMAP.md),
[../PERFORMANCE.md](../PERFORMANCE.md).

## 1. What was wrong (measured 2026-10-17)

Per-stage cost on random float32 images (`stage_bench`, one core, numpy):

| Stage | 600 px drag | 1400 px quality | 24 MP full |
|---|---|---|---|
| Tone curve | 46 ms | 263 ms | 4.4 s |
| Defringe | 25 ms | 164 ms | 2.9 s |
| Tonal | 14 ms | 76 ms | 1.5 s |
| Vignette | 12 ms | 70 ms | 1.2 s |
| Exposure | 11 ms | 55 ms | 1.0 s |
| Others | 5-25 ms | 18-60 ms | 0.3-0.9 s each |

Architecture problems behind the lag:

1. **UI-thread float conversions.** `ImageView.set_image` converts a 24 MP
   float image to RGB on the UI thread (~330 ms each, 19 times in one
   short session log). It ran on photo open, every undo/redo, and every
   mask/heal preview.
2. **Synchronous full-size renders on the UI thread.** Mask preview, heal
   preview and entering crop mode called `get_export_image()`, which
   re-renders the full 24 MP image synchronously.
3. **Image-based history.** Each undo step held full-resolution float
   buffers (~288 MB each, up to 50 steps, ~14 GB worst case), and each
   history step needed a full 24 MP render after every slider release.
4. **No stage reuse.** Every request re-runs every active stage from the
   original image.
5. **Slow per-pixel stages.** Curves, tonal, exposure and vignette are
   point operations that should cost one lookup pass, not seconds.

## 2. Target architecture

Patterns taken from LightCraft's published design (`docs/architecture.md`,
`docs/gpu-pipeline.md`, MIT/Apache) and from observing Lightroom's
documented behaviour (History panel stores settings, editing runs on
2560 px previews). No Adobe code or binaries are used.

- **Edit state is the document.** History stores adjustment-state dicts,
  never full-resolution pixels. A small display frame may be attached for
  instant visual undo.
- **Renders are derived, tiered, and off the UI thread.**
  - *interactive* (drag): small proxy, cheapest path.
  - *quality* (release / undo / tool previews): screen-sized proxy.
  - *full*: export and 1:1 zoom only.
  Every tier produces a `DisplayFrame` whose RGB conversion happened in
  the worker; the UI thread only wraps it in a `QPixmap`.
- **Point operations fused.** Exposure, tonal, white balance, curves,
  saturation/vibrance, HSL and grading run as one per-pixel pass driven by
  precomputed lookup tables (LightCraft's `finish` pass).
- **Stage cache.** Expensive spatial stages (healing, detail, optics,
  geometry) are cached by their own parameters, so a tone/colour drag only
  re-runs the fused pass.
- **Blurs** use separable/box filters whose cost is independent of radius.

## 3. Time budgets (enforced by tests)

| Scenario | Budget |
|---|---|
| Any single UI-thread task | ≤ 16 ms target, warning logged > 50 ms |
| Drag re-render (interactive tier, all common stages) | ≤ 33 ms |
| Release re-render (quality tier) | ≤ 150 ms |
| Undo / redo visible result | ≤ 50 ms |
| Open photo: first pixels on screen | ≤ 200 ms after decode |
| Export 24 MP | ≤ 5 s CPU, ≤ 1 s GPU |
| History memory | ≤ 300 MB for 50 steps |

## 4. Phases

### Phase 0 - Guardrails
- Per-stage speed tests (`tests/performance/test_stage_budgets.py`) with
  per-tier budgets; a stage that blows its budget fails the suite.
- UI-thread stall watchdog: a heartbeat timer logs `UI-STALL` with the
  duration whenever the event loop is blocked > 50 ms.
- UI changes are checked with a screenshot before commit.

### Phase 1 - No UI-thread freezes
- Full-tier renders emit `DisplayFrame`s converted in the worker.
- Photo open presents a display-sized frame built off the UI thread.
- Mask/heal/crop previews go through the worker at quality tier instead
  of synchronous `get_export_image()`.
- Histograms computed from the quality proxy, not 24 MP.

### Phase 2 - Settings-based undo/redo
- History entries hold `(previous_state, new_state)` plus an optional
  quality display frame.
- History is committed at slider release, not after a full render.
- Undo restores state with slider signals blocked, shows the stored frame
  immediately, and requests one quality render (usually a cache hit).
- The delayed 24 MP render after every release is removed.

### Phase 3 - Pipeline redesign
- Rewrite slow point stages with lookup tables (curve, tonal, exposure,
  vignette, colour) and fuse them into one pass.
- Stage cache for spatial stages; reorder so spatial stages run before
  the fused pass where that matches photographic intent.
- Radius-independent blurs for clarity, texture, dehaze, NR.

### Phase 4 - Full size only when needed
- 1:1 zoom requests a full-tier frame in the background; until it lands,
  the quality frame is shown scaled.
- Export renders full size in a background job with progress.

### Phase 5 - Compiled kernels (CPU)
- Move the fused pass and blurs into a compiled, multi-threaded kernel.
  Options in order of effort: Numba (`@njit(parallel=True)`), a Rust
  extension via PyO3 + rayon, or C++ via pybind11.
- Keep the numpy implementation as the reference; compiled output must
  match within 1/255.

### Phase 6 - GPU route
- **Backend:** `wgpu-py` (WebGPU over DX12/Vulkan/Metal) for compute
  shaders written in WGSL. Alternatives: Qt RHI compute (stays inside
  Qt 6, harder from Python), OpenCL via `pyopencl`, or CuPy for NVIDIA
  only. wgpu is the portable choice and matches LightCraft.
- **Integration point:** a `RenderBackend` interface with `cpu` and `gpu`
  implementations behind the processing worker. Stage order, lookup tables
  and cache keys are computed once on the CPU and shared (LightCraft's
  `pipeline::plan` idea), so both backends produce the same image.
- **Kernels:** geometry warp, separable blur (three box passes), fused
  `finish` pass (point ops + vignette + grain), downsample for display.
- **Residency:** upload the source once per photo; keep proxy and full
  source on the GPU while the photo is open; read back only the display
  frame (or full frame for export).
- **Fallback:** any adapter error, out-of-memory, device loss or readback
  timeout falls back to the CPU path for that render; device loss disables
  the GPU for the session. An all-black result is re-rendered on CPU.
- **Parity tests:** GPU vs CPU output within 1/255 on fixture images.
- **Preference:** Preferences > Performance > "Use GPU" (auto/on/off).

### Phase 7 - UI placement
- Edit / Crop / Mask / Heal as modes at the top of the right panel; the
  active tool's options replace the adjustment panels.
- Placement spec captured from Lightroom screenshots in
  [../UI_UX.md](../UI_UX.md); every UI change is checked against it.

## 5. Language choice

A full Rust rewrite is not planned. Most of the measured lag came from
architecture (UI-thread work, image-based history, no caching), which a
rewrite would not fix by itself. Compiled kernels (Phase 5) and the GPU
route (Phase 6) target the remaining per-pixel cost where it is measured.

## 6. Progress log

Updated as phases land; see git history for detail.

- **2026-10-17 Phase 0** - stage budget tests, UI-stall watchdog.
- **2026-10-17 Phases 1-2 (+ part of 4)** - all renders off the UI thread,
  settings-only undo history, full-resolution renders only for zoomed-in
  detail, true source-relative zoom, crop overlay no longer blanks the
  photo. Real-app run on a 24 MP CR3: no UI stalls over 50 ms across
  open, drag, release, undo, redo, zoom, mask and crop. Details:
  [implementation-notes/2026-10-17-responsiveness-overhaul.md](implementation-notes/2026-10-17-responsiveness-overhaul.md).
