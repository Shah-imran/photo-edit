"""Per-stage time budgets for the develop pipeline.

Every develop stage has to stay within a budget at the drag (interactive)
and release (quality) preview sizes, so a slow feature fails the suite
instead of shipping. Budgets come from
docs/planning/PERFORMANCE_OVERHAUL.md section 3. The timing used is the
fastest of several runs, which is stable on a loaded machine.

Set ``PHOTOEDIT_PERF_FULL=1`` to also check full 24 MP export budgets
(slow, so off by default).
"""

from __future__ import annotations

import os
from time import perf_counter

import numpy as np
import pytest

from src.processing.processing_worker import ProcessingWorker

pytestmark = pytest.mark.perf


# stage name -> (params, kind). The worker processor is
# ``_<name>_processor`` (the part before any ":" variant suffix).
# kind "point" = per-pixel operation, "spatial" = needs neighbourhoods.
STAGES = {
    "exposure": (dict(exposure=0.5, contrast=20), "point"),
    "tonal": (dict(highlights=-40, shadows=40), "point"),
    "curve": (dict(points=[(0, 0), (0.25, 0.2), (0.75, 0.85), (1, 1)]), "point"),
    "wb": (dict(temperature=15, tint=5), "point"),
    "color": (dict(saturation=20, vibrance=20), "point"),
    "hsl": (dict(red_sat=30, blue_hue=20, green_lum=-10), "point"),
    "color_grading": (dict(shadows_hue=200, shadows_sat=30), "point"),
    "vignette": (dict(vignette=-40), "point"),
    "grain": (dict(grain=40), "point"),
    "texture": (dict(texture=40), "spatial"),
    "clarity": (dict(clarity=40), "spatial"),
    "dehaze": (dict(dehaze=40), "spatial"),
    "sharpening": (dict(sharpening=60), "spatial"),
    "luminance_nr": (dict(luminance_nr=40), "spatial"),
    "color_nr": (dict(color_nr=40), "spatial"),
    "remove_ca": (dict(remove_ca=1), "spatial"),
    "defringe": (dict(defringe=40), "spatial"),
    "geometry": (dict(distortion=20, vertical=10), "spatial"),
    "straighten": (dict(straighten=3), "spatial"),
    # One local-adjustment mask (the masks list applies these in turn).
    "mask": (dict(mask=dict(type="radial", cx=0.5, cy=0.5, rx=0.3, ry=0.25, feather=0.5,
                            exposure=0.7, contrast=15, saturation=20)), "point"),
    "mask:linear": (dict(mask=dict(type="linear", x0=0.5, y0=0.2, x1=0.5, y1=0.8,
                                   exposure=-0.5, saturation=-20)), "point"),
    "mask:clarity": (dict(mask=dict(type="radial", cx=0.5, cy=0.5, rx=0.3, ry=0.25,
                                    feather=0.5, exposure=0.5, clarity=30)), "spatial"),
}

# tier -> (width, height, {kind: budget_ms})
TIERS = {
    "interactive": (600, 400, {"point": 8.0, "spatial": 20.0}),
    "quality": (1400, 933, {"point": 25.0, "spatial": 60.0}),
}
FULL_TIER = (6000, 4000, {"point": 400.0, "spatial": 900.0})

# Stages allowed to be over budget while being fixed (xfail). Empty since
# Phase 3 moved the slow stages to compiled kernels; keep it that way --
# a new stage should meet its budget before it is committed.
KNOWN_SLOW: set[str] = set()

RUNS = 5


@pytest.fixture(scope="module")
def worker():
    return ProcessingWorker()


def _best_ms(fn, image, params) -> float:
    best = float("inf")
    for _ in range(RUNS):
        src = image.copy()
        start = perf_counter()
        fn(src, **params)
        best = min(best, (perf_counter() - start) * 1000.0)
    return best


def _image(width: int, height: int) -> np.ndarray:
    rng = np.random.default_rng(1234)
    # Smooth gradient plus noise: closer to a photo than pure noise.
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    base = np.stack(
        [x / width, y / height, 0.5 * (x / width + y / height)], axis=-1
    )
    noise = rng.normal(0.0, 0.03, size=base.shape).astype(np.float32)
    return np.clip(base * 0.8 + 0.1 + noise, 0.0, 1.0).astype(np.float32)


def _params_for_marks():
    for tier in TIERS:
        for stage in STAGES:
            marks = []
            if stage in KNOWN_SLOW:
                marks.append(pytest.mark.xfail(reason="Phase 3 target", strict=False))
            yield pytest.param(tier, stage, id=f"{tier}-{stage}", marks=marks)


@pytest.mark.parametrize("tier,stage", list(_params_for_marks()))
def test_stage_within_budget(worker, tier, stage):
    width, height, budgets = TIERS[tier]
    params, kind = STAGES[stage]
    processor = getattr(worker, f"_{stage.split(':')[0]}_processor")
    elapsed = _best_ms(processor.process, _image(width, height), params)
    budget = budgets[kind]
    assert elapsed <= budget, (
        f"{stage} took {elapsed:.1f} ms at {tier} ({width}x{height}); "
        f"budget {budget:.0f} ms"
    )


@pytest.mark.skipif(
    os.environ.get("PHOTOEDIT_PERF_FULL") != "1",
    reason="set PHOTOEDIT_PERF_FULL=1 for 24 MP budgets",
)
@pytest.mark.parametrize("stage", list(STAGES))
def test_stage_full_resolution_budget(worker, stage):
    width, height, budgets = FULL_TIER
    params, kind = STAGES[stage]
    processor = getattr(worker, f"_{stage.split(':')[0]}_processor")
    image = _image(width, height)
    start = perf_counter()
    processor.process(image, **params)
    elapsed = (perf_counter() - start) * 1000.0
    assert elapsed <= budgets[kind], (
        f"{stage} took {elapsed:.0f} ms at 24 MP; budget {budgets[kind]:.0f} ms"
    )


# A heavy, realistic edit: 14 adjustments at once. Per-stage budgets can all
# pass while the sum still misses the frame budget, so the whole pipeline is
# budgeted too (docs/planning/PERFORMANCE_OVERHAUL.md section 3).
HEAVY_RECIPE = dict(
    exposure_params={"exposure": 0.6, "contrast": 15.0},
    tonal_params={"shadows": 30.0, "highlights": -40.0},
    wb_params={"temperature": 10.0},
    color_params={"vibrance": 20.0, "saturation": 10.0},
    curve_params={"points": [[0.0, 0.0], [0.5, 0.6], [1.0, 1.0]]},
    hsl_params={"blue_sat": -20.0},
    texture_params={"texture": 20.0},
    clarity_params={"clarity": 25.0},
    dehaze_params={"dehaze": 10.0},
    vignette_params={"vignette": -20.0},
    sharpening_params={"sharpening": 40.0},
    luminance_nr_params={"luminance_nr": 20.0},
    color_nr_params={"color_nr": 25.0},
    defringe_params={"defringe": 30.0},
)
PIPELINE_BUDGETS_MS = {"interactive": 33.0, "quality": 150.0}


@pytest.mark.parametrize("tier", list(PIPELINE_BUDGETS_MS))
def test_heavy_edit_renders_within_frame_budget(tier):
    from src.processing.pipeline import DevelopPipeline

    width, height, _ = TIERS[tier]
    pipeline = DevelopPipeline()
    image = _image(width, height)
    scale = max(width, height) / 6000.0  # proxy of a 24 MP photo
    best = float("inf")
    for _ in range(RUNS):
        start = perf_counter()
        pipeline.render(image, pixel_scale=scale, **HEAVY_RECIPE)
        best = min(best, (perf_counter() - start) * 1000.0)
    assert best <= PIPELINE_BUDGETS_MS[tier], (
        f"14-adjustment edit took {best:.0f} ms at {tier}; budget {PIPELINE_BUDGETS_MS[tier]:.0f} ms"
    )
