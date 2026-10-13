"""Master RGB + per-channel (R/G/B) tone-curve processor.

Like ``TonalProcessor``/``ColorProcessor``, this operates on the canonical
pipeline format (:data:`src.utils.color_pipeline.LinearImage`: float32,
``(H, W, 3)``, linear-light, ``[0, 1]``), but every curve here is applied
in the **sRGB-encoded** domain: that is the domain the curve grid visually
represents to the user (a point at the visual midpoint should read as
"raise midtones", which only lines up with the on-screen grid in
gamma-encoded space, not linear light). ``ColorProcessor`` already
establishes the precedent of clipping to ``[0, 1]`` before a nonlinear
(HSV) conversion; this processor does the same before the sRGB OETF/EOTF
round-trip.

Per-channel curves (PDF section 12, Phase E)
---------------------------------------------
There are FOUR independent curves: the master (RGB) curve plus one each
for the Red, Green, and Blue channels, matching Lightroom's own Point
Curve panel ("RGB, R/G/B channels"). They compose in a fixed order: the
master curve's LUT is applied identically to R/G/B exactly as before,
THEN each channel's own LUT is applied to that channel alone. This
mirrors a real-world point-curve pipeline (a global contrast curve first,
then per-channel color-balance tweaks on top) and means a red-only curve
change can never leak into the green/blue channels, and vice versa.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage, linear_to_srgb, srgb_to_linear
from src.utils.curve_math import apply_curve_lut, build_curve_lut, is_identity_curve

CurvePoints = Optional[Iterable[Sequence[float]]]


class CurveProcessor(BaseProcessor):
    """Processor for the master (RGB) tone curve plus the independent
    Red/Green/Blue per-channel curves.
    """

    def process(
        self,
        image: LinearImage,
        points: CurvePoints = None,
        red_points: CurvePoints = None,
        green_points: CurvePoints = None,
        blue_points: CurvePoints = None,
    ) -> LinearImage:
        """Apply the master curve, then each per-channel curve.

        Args:
            image: Input ``LinearImage``.
            points: Master (RGB) curve control points as ``(x, y)`` pairs
                in ``[0, 1]``, applied identically to R/G/B. Defaults to
                the identity/straight-line curve (a no-op).
            red_points: Red channel's own curve, applied to the red
                channel only, AFTER the master curve. Defaults to
                identity.
            green_points: Green channel's own curve, applied to the
                green channel only, AFTER the master curve. Defaults to
                identity.
            blue_points: Blue channel's own curve, applied to the blue
                channel only, AFTER the master curve. Defaults to
                identity.

        Returns:
            A new float32 array of the same shape. When all 4 curves are
            identity (the all-defaults case, matching every other
            processor's "all defaults => identity copy" convention --
            see ``StraightenProcessor``/``GeometryProcessor``), this does
            no LUT-building work at all.
        """
        result = np.array(image, dtype=np.float32, copy=True)

        if (
            is_identity_curve(points)
            and is_identity_curve(red_points)
            and is_identity_curve(green_points)
            and is_identity_curve(blue_points)
        ):
            return result

        srgb = linear_to_srgb(result[..., :3])

        if not is_identity_curve(points):
            master_lut = build_curve_lut(points, resolution=256)
            srgb = apply_curve_lut(srgb, master_lut)

        channel_points = (red_points, green_points, blue_points)
        for channel_index, channel_pts in enumerate(channel_points):
            if is_identity_curve(channel_pts):
                continue
            channel_lut = build_curve_lut(channel_pts, resolution=256)
            srgb[..., channel_index] = apply_curve_lut(
                srgb[..., channel_index], channel_lut
            )

        result[..., :3] = srgb_to_linear(srgb)
        return result
