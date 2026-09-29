"""The single "apply all current Basic-panel adjustments" sequence.

``ProcessingWorker`` (proxy preview and full-resolution render),
``CombinedAdjustmentCommand`` (undo/redo), and ``ImageController``'s
synchronous fallback and export paths all need to turn a PIL image plus
the current adjustment parameters into a processed PIL image. Before this
module existed, each of those three-plus call sites re-implemented the
same processor sequence separately - which is exactly how a new
adjustment could get wired into two of them and silently missed in the
third. This module is the one place that sequence is defined; every call
site should go through :func:`apply_basic_adjustments` rather than calling
the individual processors itself.
"""

from typing import Dict, Optional

from PIL import Image

from src.processing.color_space import image_to_linear, linear_to_image
from src.processors.color_processor import ColorProcessor
from src.processors.exposure_processor import ExposureProcessor
from src.processors.tonal_processor import TonalProcessor

# Stateless processors - safe to share across all call sites.
_exposure_processor = ExposureProcessor()
_tonal_processor = TonalProcessor()
_color_processor = ColorProcessor()

# Modes TonalProcessor's linear-light math understands. Anything else (e.g.
# a "L" grayscale image) skips the tonal step rather than crashing on the
# 3/4-channel assumption - a grayscale-image Highlights/Shadows/Whites/
# Blacks path can be added later without this module needing to change.
_TONAL_CAPABLE_MODES = ("RGB", "RGBA")


def apply_basic_adjustments(
    image: Image.Image,
    exposure_params: Optional[Dict[str, float]] = None,
    tonal_params: Optional[Dict[str, float]] = None,
    color_params: Optional[Dict[str, float]] = None,
) -> Image.Image:
    """Apply the full Basic-panel adjustment chain to an image.

    Order: Exposure/Contrast/Brightness (legacy 8-bit path) -> Highlights/
    Shadows/Whites/Blacks (converted to linear light and back) ->
    Saturation/Vibrance. Each stage is skipped entirely when its
    parameters are all zero (or absent), so an image with no active
    Highlights/Shadows/Whites/Blacks sliders pays no linear-light
    round-trip cost at all.

    Args:
        image: Source PIL image. Never mutated.
        exposure_params: exposure/contrast/brightness, as
            ``ExposureProcessor.process`` expects.
        tonal_params: highlights/shadows/whites/blacks, as
            ``TonalProcessor.process`` expects.
        color_params: saturation/vibrance, as ``ColorProcessor.process``
            expects.

    Returns:
        A new processed PIL Image.
    """
    result = image.copy()

    if exposure_params and any(v != 0 for v in exposure_params.values()):
        result = _exposure_processor.process(result, **exposure_params)

    if (
        tonal_params
        and any(v != 0 for v in tonal_params.values())
        and result.mode in _TONAL_CAPABLE_MODES
    ):
        linear = image_to_linear(result)
        linear = _tonal_processor.process(linear, **tonal_params)
        result = linear_to_image(linear, result.mode)

    if color_params and any(v != 0 for v in color_params.values()):
        result = _color_processor.process(result, **color_params)

    return result
