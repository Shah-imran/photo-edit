"""The develop pipeline: the one definition of stage order and skip rules.

Five places used to carry their own copy of "run every processor in this
order" (the preview worker, export, restoring saved settings, the
synchronous preview fallback and the undo command), and the copies had
drifted -- the synchronous preview passed the mask's fields to the mask
stage as keyword arguments and would raise as soon as a mask existed.
Everything now renders through :meth:`DevelopPipeline.render`.

Order (see the implementation notes of each stage): healing first (it
repairs the as-shot pixels), then tone and colour, effects, detail,
optics, geometry and straighten, the local mask, and crop strictly last
(the only stage that changes the output shape).
"""

from __future__ import annotations

from time import perf_counter
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.processors.clarity_processor import ClarityProcessor
from src.processors.color_grading_processor import ColorGradingProcessor
from src.processors.color_noise_reduction_processor import ColorNoiseReductionProcessor
from src.processors.color_processor import ColorProcessor
from src.processors.crop_processor import CropProcessor
from src.processors.curve_processor import CurveProcessor
from src.processors.defringe_processor import DefringeProcessor
from src.processors.dehaze_processor import DehazeProcessor
from src.processors.exposure_processor import ExposureProcessor
from src.processors.geometry_processor import GeometryProcessor
from src.processors.grain_processor import GrainProcessor
from src.processors.healing_processor import HealingProcessor
from src.processors.hsl_mixer_processor import HslMixerProcessor
from src.processors.luminance_noise_reduction_processor import (
    LuminanceNoiseReductionProcessor,
)
from src.processors.mask_processor import MaskProcessor
from src.processors.remove_chromatic_aberration_processor import (
    RemoveChromaticAberrationProcessor,
)
from src.processors.sharpening_processor import SharpeningProcessor
from src.processors.straighten_processor import StraightenProcessor
from src.processors.texture_processor import TextureProcessor
from src.processors.tonal_processor import TonalProcessor
from src.processors.vignette_processor import VignetteProcessor
from src.processors.white_balance_processor import WhiteBalanceProcessor
from src.utils.color_pipeline import LinearImage

_GEOMETRY_IDENTITY = {
    "distortion": 0.0, "vertical": 0.0, "horizontal": 0.0,
    "scale": 100.0, "offset_x": 0.0, "offset_y": 0.0,
}


def mask_list(params) -> List[Dict[str, Any]]:
    """The masks in a ``mask_params`` value: ``{"masks": [...]}``, or a
    single mask dict (older callers and saved edits)."""
    if not params:
        return []
    if "masks" in params:
        return [m for m in params["masks"] if m]
    return [params] if params.get("type") else []


def _any_nonzero(params) -> bool:
    return bool(params) and any(v != 0 for v in params.values())


def _key_nonzero(key: str) -> Callable[[Dict[str, Any]], bool]:
    return lambda params: bool(params) and params.get(key, 0.0) != 0.0


def _geometry_active(params) -> bool:
    return bool(params) and any(
        params.get(key, default) != default for key, default in _GEOMETRY_IDENTITY.items()
    )


class DevelopPipeline:
    """Owns one instance of every processor and applies them in order."""

    # (stage name, param keyword, "does this stage run?", call style)
    # call style "kwargs" spreads the params; "mask" passes mask=params;
    # "pixel" spreads the params plus pixel_scale (native-pixel effects).
    STAGES: List[Tuple[str, str, Callable[[Any], bool], str]] = [
        ("healing", "healing_params", lambda p: bool(p and p.get("heal_spots")), "kwargs"),
        ("exposure", "exposure_params", _any_nonzero, "kwargs"),
        ("tonal", "tonal_params", _any_nonzero, "kwargs"),
        ("wb", "wb_params", _any_nonzero, "kwargs"),
        ("curve", "curve_params", bool, "kwargs"),
        ("color", "color_params", _any_nonzero, "kwargs"),
        ("hsl", "hsl_params", _any_nonzero, "kwargs"),
        ("color_grading", "color_grading_params", bool, "kwargs"),
        ("texture", "texture_params", _key_nonzero("texture"), "kwargs"),
        ("clarity", "clarity_params", _key_nonzero("clarity"), "kwargs"),
        ("dehaze", "dehaze_params", _key_nonzero("dehaze"), "kwargs"),
        ("vignette", "vignette_params", _key_nonzero("vignette"), "kwargs"),
        ("grain", "grain_params", _key_nonzero("grain"), "kwargs"),
        ("sharpening", "sharpening_params", _key_nonzero("sharpening"), "pixel"),
        ("luminance_nr", "luminance_nr_params", _key_nonzero("luminance_nr"), "pixel"),
        ("color_nr", "color_nr_params", _key_nonzero("color_nr"), "pixel"),
        ("remove_ca", "remove_ca_params", _key_nonzero("remove_ca"), "kwargs"),
        ("defringe", "defringe_params", _key_nonzero("defringe"), "kwargs"),
        ("geometry", "geometry_params", _geometry_active, "kwargs"),
        ("straighten", "straighten_params", _key_nonzero("straighten"), "kwargs"),
        ("mask", "mask_params", lambda p: bool(mask_list(p)), "masks"),
        ("crop", "crop_params", bool, "kwargs"),
    ]

    def __init__(self) -> None:
        self.processors = {
            "healing": HealingProcessor(),
            "exposure": ExposureProcessor(),
            "tonal": TonalProcessor(),
            "wb": WhiteBalanceProcessor(),
            "curve": CurveProcessor(),
            "color": ColorProcessor(),
            "hsl": HslMixerProcessor(),
            "color_grading": ColorGradingProcessor(),
            "texture": TextureProcessor(),
            "clarity": ClarityProcessor(),
            "dehaze": DehazeProcessor(),
            "vignette": VignetteProcessor(),
            "grain": GrainProcessor(),
            "sharpening": SharpeningProcessor(),
            "luminance_nr": LuminanceNoiseReductionProcessor(),
            "color_nr": ColorNoiseReductionProcessor(),
            "remove_ca": RemoveChromaticAberrationProcessor(),
            "defringe": DefringeProcessor(),
            "geometry": GeometryProcessor(),
            "straighten": StraightenProcessor(),
            "mask": MaskProcessor(),
            "crop": CropProcessor(),
        }

    def render(
        self,
        image: LinearImage,
        timings: Optional[Dict[str, float]] = None,
        pixel_scale: float = 1.0,
        **params: Any,
    ) -> LinearImage:
        """Apply every active stage to ``image`` (never modified in place).

        ``params`` uses the ``<stage>_params`` keywords of
        ``ProcessingWorker.submit_request``; missing ones are identity.
        When ``timings`` is given, each run stage's milliseconds go in it.
        ``pixel_scale`` is this image's size relative to the full-resolution
        photo (a 1400 px proxy of a 6000 px photo: ~0.23); native-pixel
        effects (sharpening, noise reduction) use it so previews match the
        export (see src/utils/spatial.py).
        """
        unknown = set(params) - {keyword for _, keyword, _, _ in self.STAGES}
        if unknown:
            raise TypeError(f"unknown pipeline parameters: {sorted(unknown)}")
        result = image.copy()
        for name, keyword, active, style in self.STAGES:
            stage_params = params.get(keyword)
            if not active(stage_params):
                continue
            start = perf_counter()
            processor = self.processors[name]
            if style == "masks":
                for mask in mask_list(stage_params):
                    result = processor.process(result, mask=mask)
            elif style == "pixel":
                result = processor.process(result, pixel_scale=pixel_scale, **stage_params)
            else:
                result = processor.process(result, **stage_params)
            if timings is not None:
                timings[name] = (perf_counter() - start) * 1000.0
        return result


_SHARED: Optional[DevelopPipeline] = None


def shared_pipeline() -> DevelopPipeline:
    """A process-wide pipeline for synchronous callers (processors are
    stateless; the compiled kernels serialize themselves)."""
    global _SHARED
    if _SHARED is None:
        _SHARED = DevelopPipeline()
    return _SHARED
