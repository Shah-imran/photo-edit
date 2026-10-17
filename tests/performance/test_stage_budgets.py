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


# stage name -> (worker processor attribute suffix, params, kind)
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
}

# tier -> (width, height, {kind: budget_ms})
TIERS = {
    "interactive": (600, 400, {"point": 8.0, "spatial": 20.0}),
    "quality": (1400, 933, {"point": 25.0, "spatial": 60.0}),
}
FULL_TIER = (6000, 4000, {"point": 400.0, "spatial": 900.0})

# Stages that are known to be over budget and are being fixed in Phase 3
# of the overhaul. Remove a name once its stage meets the budget; a stage
# listed here that starts passing is reported as XPASS.
KNOWN_SLOW: set[str] = {
    "exposure",
    "tonal",
    "curve",
    "color",
    "hsl",
    "color_grading",
    "vignette",
    "defringe",
}

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
    processor = getattr(worker, f"_{stage}_processor")
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
    processor = getattr(worker, f"_{stage}_processor")
    image = _image(width, height)
    start = perf_counter()
    processor.process(image, **params)
    elapsed = (perf_counter() - start) * 1000.0
    assert elapsed <= budgets[kind], (
        f"{stage} took {elapsed:.0f} ms at 24 MP; budget {budgets[kind]:.0f} ms"
    )
