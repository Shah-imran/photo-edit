"""Master RGB tone-curve processor.

Like ``TonalProcessor``/``ColorProcessor``, this operates on the canonical
pipeline format (:data:`src.utils.color_pipeline.LinearImage`: float32,
``(H, W, 3)``, linear-light, ``[0, 1]``), but the curve itself is applied
in the **sRGB-encoded** domain: that is the domain the curve grid visually
represents to the user (a point at the visual midpoint should read as
"raise midtones", which only lines up with the on-screen grid in
gamma-encoded space, not linear light). ``ColorProcessor`` already
establishes the precedent of clipping to ``[0, 1]`` before a nonlinear
(HSV) conversion; this processor does the same before the sRGB OETF/EOTF
round-trip.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage, linear_to_srgb, srgb_to_linear
from src.utils.curve_math import apply_curve_lut, build_curve_lut, is_identity_curve


class CurveProcessor(BaseProcessor):
    """Processor for the master (RGB) tone curve."""

    def process(
        self,
        image: LinearImage,
        points: Iterable[Sequence[float]] | None = None,
    ) -> LinearImage:
        """Apply the tone curve defined by ``points``.

        Args:
            image: Input ``LinearImage``.
            points: Control points as ``(x, y)`` pairs in ``[0, 1]``. An
                identity/straight-line curve (the default) is a no-op.

        Returns:
            A new float32 array of the same shape.
        """
        result = np.array(image, dtype=np.float32, copy=True)

        if is_identity_curve(points):
            return result

        lut = build_curve_lut(points, resolution=256)
        srgb = linear_to_srgb(result[..., :3])
        curved = apply_curve_lut(srgb, lut)
        result[..., :3] = srgb_to_linear(curved)
        return result
