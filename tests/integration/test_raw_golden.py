"""Visual regression on real camera RAW files.

Decodes each RAW in test_images/ (git-ignored, so this skips where the
files are absent), applies a fixed edit recipe through the real pipeline
at quality-preview size, and compares the result with a committed golden
PNG. Any unintended change to how photos look -- a processor rewrite, a
kernel bug, a colour-pipeline change -- fails here, which no per-stage
unit test can catch.

Golden images live in tests/fixtures/golden/. To re-approve after an
intended look change, delete the PNG and run with PHOTOEDIT_UPDATE_GOLDEN=1.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.processing.display_frame import linear_to_display_rgb
from src.processing.processing_worker import ProcessingWorker
from src.processing.proxy_manager import ProxyManager
from src.services.image_service import ImageService

pytestmark = [pytest.mark.integration, pytest.mark.raw]

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "test_images"
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"
RAWS = ["IMG_4598.CR3", "IMG_4620.CR3"]

RECIPE = dict(
    exposure_params={"exposure": 0.4, "contrast": 20.0, "brightness": 0.0},
    tonal_params={"highlights": -40.0, "shadows": 35.0, "whites": 10.0, "blacks": -10.0},
    wb_params={"temperature": 8.0, "tint": -3.0},
    curve_params={"points": [[0.0, 0.0], [0.25, 0.22], [0.75, 0.8], [1.0, 1.0]]},
    color_params={"saturation": 10.0, "vibrance": 20.0},
    hsl_params={"blue_sat": -20.0, "orange_lum": 10.0},
    color_grading_params={"shadows_hue": 210.0, "shadows_sat": 15.0, "blending": 50.0, "balance": 0.0},
    texture_params={"texture": 15.0},
    clarity_params={"clarity": 20.0},
    dehaze_params={"dehaze": 10.0},
    vignette_params={"vignette": -15.0},
    sharpening_params={"sharpening": 30.0},
    luminance_nr_params={"luminance_nr": 15.0},
    defringe_params={"defringe": 20.0},
)


def _render(raw_path: Path) -> np.ndarray:
    image = ImageService().load_image(str(raw_path))
    proxy = ProxyManager(max_size=1400)
    proxy.set_image(image)
    result = ProcessingWorker()._apply_adjustments(proxy.get_proxy(), **RECIPE)
    rgb = linear_to_display_rgb(result)
    small = Image.fromarray(rgb).resize(
        (rgb.shape[1] // 4, rgb.shape[0] // 4), Image.Resampling.BOX
    )
    return np.asarray(small, dtype=np.int16)


@pytest.mark.parametrize("name", RAWS)
def test_recipe_render_matches_golden(name):
    raw_path = RAW_DIR / name
    if not raw_path.exists():
        pytest.skip(f"{name} not present in test_images/")
    golden_path = GOLDEN_DIR / f"{raw_path.stem}_recipe.png"
    rendered = _render(raw_path)

    if not golden_path.exists():
        if os.environ.get("PHOTOEDIT_UPDATE_GOLDEN") == "1":
            GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
            Image.fromarray(rendered.astype(np.uint8)).save(golden_path)
            pytest.skip(f"recorded new golden {golden_path.name}")
        pytest.fail(f"missing golden {golden_path.name}; run with PHOTOEDIT_UPDATE_GOLDEN=1")

    golden = np.asarray(Image.open(golden_path), dtype=np.int16)
    assert rendered.shape == golden.shape
    diff = np.abs(rendered - golden)
    # Allow float/rounding noise, not a visible change.
    assert diff.mean() <= 1.0, f"mean difference {diff.mean():.2f} levels"
    assert np.percentile(diff, 99.5) <= 6, f"99.5th pct {np.percentile(diff, 99.5)} levels"
