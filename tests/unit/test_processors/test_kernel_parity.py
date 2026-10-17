"""Compiled kernels must reproduce each processor's NumPy reference.

Every processor that has a fast path keeps its original NumPy code as
``_process_numpy``; this pins the fast path to it across the full slider
range, out-of-range pixel values and extra (alpha) channels.
"""

import numpy as np
import pytest

from src.processors.exposure_processor import ExposureProcessor
from src.processors.tonal_processor import TonalProcessor
from src.processors.vignette_processor import VignetteProcessor
from src.utils import pixel_kernels

pytestmark = pytest.mark.skipif(
    not pixel_kernels.HAVE_NUMBA, reason="fast path needs Numba"
)

ATOL = 2e-5


@pytest.fixture(params=[3, 4], ids=["rgb", "rgba"])
def image(request):
    rng = np.random.default_rng(11)
    return rng.uniform(-0.1, 1.4, size=(41, 67, request.param)).astype(np.float32)


@pytest.mark.parametrize(
    "params",
    [
        dict(exposure=1.3),
        dict(exposure=-2.0, brightness=35.0),
        dict(contrast=60.0),
        dict(contrast=-100.0),
        dict(brightness=-100.0, contrast=25.0),
        dict(exposure=0.7, contrast=-40.0, brightness=10.0),
    ],
)
def test_exposure_matches_reference(image, params):
    processor = ExposureProcessor()
    full = {"exposure": 0.0, "contrast": 0.0, "brightness": 0.0, **params}
    fast = processor.process(image, **params)
    reference = processor._process_numpy(
        image, full["exposure"], full["contrast"], full["brightness"]
    )
    # Contrast goes through 65536-entry tables; an index can land one entry
    # over on a float32 tie, which is ~1e-5 in value.
    np.testing.assert_allclose(fast, reference, atol=ATOL)


@pytest.mark.parametrize(
    "params",
    [
        dict(highlights=-60.0),
        dict(shadows=70.0),
        dict(whites=40.0, blacks=-30.0),
        dict(highlights=45.0, shadows=-55.0, whites=-20.0, blacks=25.0),
        dict(whites=100.0, blacks=100.0),
    ],
)
def test_tonal_matches_reference(image, params):
    processor = TonalProcessor()
    full = {"highlights": 0.0, "shadows": 0.0, "whites": 0.0, "blacks": 0.0, **params}
    fast = processor.process(image, **params)
    reference = processor._process_numpy(
        image, full["highlights"], full["shadows"], full["whites"], full["blacks"]
    )
    np.testing.assert_allclose(fast, reference, atol=ATOL)


@pytest.mark.parametrize("value", [-100.0, -35.0, 20.0, 100.0])
def test_vignette_matches_reference(image, value):
    processor = VignetteProcessor()
    fast = processor.process(image, vignette=value)
    reference = processor._process_numpy(image, value)
    np.testing.assert_allclose(fast, reference, atol=ATOL)


from src.processors.color_grading_processor import ColorGradingProcessor  # noqa: E402
from src.processors.color_processor import ColorProcessor  # noqa: E402
from src.processors.defringe_processor import DefringeProcessor  # noqa: E402
from src.processors.hsl_mixer_processor import HslMixerProcessor  # noqa: E402


@pytest.fixture
def rgb():
    rng = np.random.default_rng(12)
    image = rng.uniform(-0.1, 1.2, size=(43, 59, 3)).astype(np.float32)
    image[0, :4] = [[0.5, 0.5, 0.5], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.2, 0.9, 0.2]]
    return image


# HSV-based stages: hue is in degrees, so a ~1e-5 relative difference in
# the reconstructed OpenCV conversion shows up as up to ~1e-4 in RGB.
HSV_ATOL = 2e-4


@pytest.mark.parametrize(
    "params",
    [dict(saturation=40.0), dict(saturation=-100.0), dict(vibrance=60.0),
     dict(vibrance=-50.0, saturation=30.0)],
)
def test_color_matches_reference(rgb, params):
    processor = ColorProcessor()
    full = {"saturation": 0.0, "vibrance": 0.0, **params}
    fast = processor.process(rgb, **params)
    reference = processor._process_numpy(rgb, full["saturation"], full["vibrance"])
    np.testing.assert_allclose(fast, reference, atol=HSV_ATOL)


@pytest.mark.parametrize(
    "params",
    [dict(red_sat=40.0), dict(blue_hue=-80.0, green_lum=30.0),
     dict(orange_sat=-100.0, aqua_hue=100.0, magenta_lum=-60.0, purple_sat=55.0)],
)
def test_hsl_matches_reference(image, params):
    processor = HslMixerProcessor()
    fast = processor.process(image, **params)
    reference = processor._process_numpy(image, **params)
    np.testing.assert_allclose(fast, reference, atol=HSV_ATOL)


@pytest.mark.parametrize(
    "params",
    [dict(shadows_hue=220.0, shadows_sat=40.0),
     dict(highlights_hue=40.0, highlights_sat=70.0, midtones_lum=-30.0, balance=40.0),
     dict(midtones_hue=300.0, midtones_sat=-50.0, blending=0.0),
     dict(shadows_lum=50.0, blending=100.0)],
)
def test_color_grading_matches_reference(image, params):
    processor = ColorGradingProcessor()
    fast = processor.process(image, **params)
    reference_input = np.array(image, dtype=np.float32, copy=True)
    range_params = {
        r: (params.get(f"{r}_hue", 0.0), params.get(f"{r}_sat", 0.0), params.get(f"{r}_lum", 0.0))
        for r in ("shadows", "midtones", "highlights")
    }
    reference = processor._process_numpy(reference_input, range_params, params)
    np.testing.assert_allclose(fast, reference, atol=ATOL)


@pytest.mark.parametrize("value", [15.0, 60.0, 100.0])
def test_defringe_matches_reference(rgb, value):
    processor = DefringeProcessor()
    fast = processor.process(rgb, defringe=value)
    reference = processor._process_numpy(rgb, value)
    np.testing.assert_allclose(fast, reference, atol=ATOL)


from src.processors.clarity_processor import ClarityProcessor  # noqa: E402
from src.processors.color_noise_reduction_processor import ColorNoiseReductionProcessor  # noqa: E402
from src.processors.dehaze_processor import DehazeProcessor  # noqa: E402
from src.processors.sharpening_processor import SharpeningProcessor  # noqa: E402
from src.processors.texture_processor import TextureProcessor  # noqa: E402


def _numpy_only(monkeypatch, *names):
    for name in names:
        monkeypatch.setattr(pixel_kernels, name, lambda *a, **k: None)


@pytest.mark.parametrize("cls,kw", [(ClarityProcessor, "clarity"), (TextureProcessor, "texture")])
@pytest.mark.parametrize("value", [-80.0, 45.0])
def test_unsharp_stages_match_reference(rgb, monkeypatch, cls, kw, value):
    fast = cls().process(rgb, **{kw: value})
    _numpy_only(monkeypatch, "unsharp")
    reference = cls().process(rgb, **{kw: value})
    np.testing.assert_allclose(fast, reference, atol=ATOL)


@pytest.mark.parametrize("value", [30.0, 100.0])
def test_dehaze_matches_reference(rgb, monkeypatch, value):
    fast = DehazeProcessor().process(rgb, dehaze=value)
    _numpy_only(monkeypatch, "dark_channel", "dehaze_combine")
    reference = DehazeProcessor().process(rgb, dehaze=value)
    np.testing.assert_allclose(fast, reference, atol=ATOL)


@pytest.mark.parametrize("value", [25.0, 100.0])
def test_sharpening_matches_reference(rgb, monkeypatch, value):
    fast = SharpeningProcessor().process(rgb, sharpening=value)
    _numpy_only(monkeypatch, "masked_unsharp")
    reference = SharpeningProcessor().process(rgb, sharpening=value)
    np.testing.assert_allclose(fast, reference, atol=ATOL)


@pytest.mark.parametrize("value", [40.0, 100.0])
def test_color_nr_matches_reference(rgb, monkeypatch, value):
    fast = ColorNoiseReductionProcessor().process(rgb, color_nr=value)
    _numpy_only(monkeypatch, "chroma_split", "chroma_merge")
    reference = ColorNoiseReductionProcessor().process(rgb, color_nr=value)
    np.testing.assert_allclose(fast, reference, atol=ATOL)
