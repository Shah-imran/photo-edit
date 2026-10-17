"""Per-stage visual regression on a real RAW, plus an export round trip.

``test_raw_golden.py`` renders a 14-adjustment recipe: it catches that the
look changed, not which stage changed it. Here every develop stage gets
its own single-adjustment golden, so a failure names the culprit. The
export test runs the real export path (full-resolution render, resize,
JPEG encode, decode) and compares what lands on disk.

Skips where the RAW (git-ignored, test_images/) is absent. Re-approve an
intended look change with PHOTOEDIT_UPDATE_GOLDEN=1 after deleting the
stage's PNG in tests/fixtures/golden/stages/.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.processing.display_frame import linear_to_display_rgb
from src.processing.pipeline import DevelopPipeline
from src.processing.proxy_manager import ProxyManager
from src.services.export_service import ExportService
from src.services.image_service import ImageService

pytestmark = [pytest.mark.integration, pytest.mark.raw]

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "test_images" / "IMG_4620.CR3"
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden" / "stages"
PREVIEW_EDGE = 800

# One clearly visible setting per stage (keyword -> params).
STAGES = {
    "exposure": {"exposure_params": {"exposure": 0.8}},
    "contrast": {"exposure_params": {"contrast": 50.0}},
    "tonal": {"tonal_params": {"highlights": -60.0, "shadows": 60.0}},
    "whites_blacks": {"tonal_params": {"whites": 40.0, "blacks": -40.0}},
    "white_balance": {"wb_params": {"temperature": 30.0, "tint": -15.0}},
    "tone_curve": {"curve_params": {"points": [[0.0, 0.0], [0.25, 0.15], [0.75, 0.9], [1.0, 1.0]]}},
    "rgb_curve": {"curve_params": {"red_points": [[0.0, 0.0], [0.5, 0.65], [1.0, 1.0]]}},
    "color": {"color_params": {"saturation": 40.0, "vibrance": 40.0}},
    "hsl": {"hsl_params": {"blue_sat": -60.0, "blue_hue": 40.0, "orange_lum": 30.0}},
    "color_grading": {"color_grading_params": {"shadows_hue": 210.0, "shadows_sat": 50.0,
                                               "highlights_hue": 40.0, "highlights_sat": 40.0,
                                               "blending": 50.0, "balance": 0.0}},
    "texture": {"texture_params": {"texture": 70.0}},
    "clarity": {"clarity_params": {"clarity": 70.0}},
    "dehaze": {"dehaze_params": {"dehaze": 60.0}},
    "vignette": {"vignette_params": {"vignette": 60.0}},
    "grain": {"grain_params": {"grain": 60.0}},
    "sharpening": {"sharpening_params": {"sharpening": 80.0}},
    "luminance_nr": {"luminance_nr_params": {"luminance_nr": 80.0}},
    "color_nr": {"color_nr_params": {"color_nr": 80.0}},
    "remove_ca": {"remove_ca_params": {"remove_ca": 1.0}},
    "defringe": {"defringe_params": {"defringe": 80.0}},
    "geometry": {"geometry_params": {"distortion": 30.0, "vertical": 20.0, "horizontal": 0.0,
                                     "scale": 100.0, "offset_x": 0.0, "offset_y": 0.0}},
    "straighten": {"straighten_params": {"straighten": 5.0}},
    "crop": {"crop_params": {"x0": 0.15, "y0": 0.1, "x1": 0.85, "y1": 0.8}},
    "mask": {"mask_params": {"type": "radial", "cx": 0.55, "cy": 0.45, "rx": 0.25, "ry": 0.3,
                             "feather": 0.5, "invert": False, "exposure": 1.2, "contrast": 20.0,
                             "saturation": 20.0, "clarity": 0.0}},
    # On the heron's head (flat water would make healing invisible).
    "healing": {"healing_params": {"heal_spots": [{"mode": "heal", "dst_x": 0.57, "dst_y": 0.37,
                                                   "src_x": 0.3, "src_y": 0.37, "radius": 0.05,
                                                   "feather": 0.3, "opacity": 1.0}]}},
}

# Native-pixel effects barely show on a downscaled preview (by design: the
# preview shows what the downscaled export shows), so they are checked on a
# 1:1 crop of the full-resolution photo around the head and beak instead.
DETAIL_STAGES = {
    name: STAGES.pop(name)
    for name in ("sharpening", "luminance_nr", "color_nr", "grain")
}
# Chromatic-aberration removal and defringe need colour fringes, which this
# photo doesn't have (they change it by ~0.01 levels); their unit tests use
# synthetic fringes instead.
for _name in ("remove_ca", "defringe"):
    STAGES.pop(_name)
DETAIL_CENTER = (0.6, 0.33)  # fraction of width, height
DETAIL_SIZE = 256
GOLDEN_EDGE = 320  # whole-photo goldens are stored at this long edge


@pytest.fixture(scope="module")
def photo():
    if not RAW.exists():
        pytest.skip(f"{RAW.name} not present in test_images/")
    image = ImageService().load_image(str(RAW))
    proxy = ProxyManager(max_size=PREVIEW_EDGE)
    proxy.set_image(image)
    preview = proxy.get_proxy()
    return image, preview, max(preview.shape[:2]) / max(image.shape[:2])


def _compare(name: str, rendered: np.ndarray, mean_limit=1.0, pct_limit=6) -> None:
    golden_path = GOLDEN_DIR / f"{name}.png"
    if not golden_path.exists():
        if os.environ.get("PHOTOEDIT_UPDATE_GOLDEN") == "1":
            GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
            Image.fromarray(rendered.astype(np.uint8)).save(golden_path)
            pytest.skip(f"recorded new golden {golden_path.name}")
        pytest.fail(f"missing golden {golden_path.name}; run with PHOTOEDIT_UPDATE_GOLDEN=1")
    golden = np.asarray(Image.open(golden_path).convert("RGB"), dtype=np.int16)
    assert rendered.shape == golden.shape, f"{name}: shape {rendered.shape} != {golden.shape}"
    diff = np.abs(rendered.astype(np.int16) - golden)
    assert diff.mean() <= mean_limit, f"{name}: mean difference {diff.mean():.2f} levels"
    assert np.percentile(diff, 99.5) <= pct_limit, (
        f"{name}: 99.5th percentile {np.percentile(diff, 99.5)} levels"
    )


def _small(rgb: np.ndarray) -> np.ndarray:
    height, width = rgb.shape[:2]
    factor = GOLDEN_EDGE / max(height, width)
    size = (max(1, round(width * factor)), max(1, round(height * factor)))
    return np.asarray(Image.fromarray(rgb).resize(size, Image.Resampling.BOX), dtype=np.int16)


def _assert_visible(stage, rendered, baseline):
    """A stage that changes nothing would make its golden prove nothing.
    Local tools (healing, masks) change a small area strongly, so the
    largest local change counts as well as the average."""
    if rendered.shape == baseline.shape:
        diff = np.abs(rendered.astype(np.int16) - baseline.astype(np.int16))
        assert diff.mean() > 0.2 or np.percentile(diff, 99.9) > 8, (
            f"{stage} had no visible effect ({diff.mean():.2f} levels)"
        )


@pytest.mark.parametrize("stage", list(STAGES))
def test_stage_render_matches_golden(photo, stage):
    _image, preview, scale = photo
    result = DevelopPipeline().render(preview, pixel_scale=scale, **STAGES[stage])
    rendered = linear_to_display_rgb(result)
    _assert_visible(stage, rendered, linear_to_display_rgb(preview))
    _compare(stage, _small(rendered))


@pytest.mark.parametrize("stage", list(DETAIL_STAGES))
def test_detail_stage_at_full_resolution_matches_golden(photo, stage):
    image, _preview, _scale = photo
    height, width = image.shape[:2]
    cx, cy = int(width * DETAIL_CENTER[0]), int(height * DETAIL_CENTER[1])
    half = DETAIL_SIZE // 2
    crop = np.ascontiguousarray(image[cy - half:cy + half, cx - half:cx + half])
    result = DevelopPipeline().render(crop, **DETAIL_STAGES[stage])
    rendered = linear_to_display_rgb(result)
    _assert_visible(stage, rendered, linear_to_display_rgb(crop))
    _compare(f"detail_{stage}", rendered.astype(np.int16))


def test_export_round_trip_matches_golden(photo, tmp_path):
    """Full-resolution render -> resize -> JPEG encode -> decode."""
    image, _preview, _scale = photo
    recipe = {**STAGES["exposure"], **STAGES["clarity"], **STAGES["crop"], **STAGES["vignette"]}
    rendered = DevelopPipeline().render(image, **recipe)
    out = tmp_path / "export.jpg"
    assert ExportService().export_image(
        rendered, str(out), format="JPEG", quality=95, resize=(900, 900), preserve_aspect=True
    )
    decoded = np.asarray(Image.open(out).convert("RGB"), dtype=np.uint8)
    assert max(decoded.shape[:2]) == 900
    # JPEG adds a little noise; allow slightly more than the render goldens.
    _compare("export_round_trip", _small(decoded), mean_limit=1.5, pct_limit=10)
