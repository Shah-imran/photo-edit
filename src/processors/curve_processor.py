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

from functools import lru_cache
from typing import Iterable, Optional, Sequence

import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage, linear_to_srgb, srgb_to_linear
from src.utils.curve_math import apply_curve_lut, build_curve_lut, is_identity_curve
from src.utils.pixel_kernels import apply_channel_luts

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
        if (
            is_identity_curve(points)
            and is_identity_curve(red_points)
            and is_identity_curve(green_points)
            and is_identity_curve(blue_points)
        ):
            return np.array(image, dtype=np.float32, copy=True)

        # The whole chain (sRGB encode -> master -> channel -> decode) is a
        # per-channel point operation, so it is sampled once into tables
        # and applied with one lookup per pixel instead of four full-image
        # power/interp passes (4.4 s -> ~0.3 s at 24 MP).
        master = _points_key(points)
        channels = (
            _points_key(red_points),
            _points_key(green_points),
            _points_key(blue_points),
        )
        luts = _linear_curve_luts(master, *channels)
        # A channel with no curve at all (no master, no own curve) is left
        # alone apart from the [0, 1] clip the old sRGB round-trip applied.
        active = tuple(master is not None or c is not None for c in channels)
        return apply_channel_luts(image, luts, active)


def _points_key(points: CurvePoints):
    """Hashable, identity-normalized form of a curve's points."""
    if is_identity_curve(points):
        return None
    return tuple((float(x), float(y)) for x, y in points)


# Tables are sampled uniformly over linear [0, 1]; with 65536 entries the
# nearest-entry error is below slope * 7.7e-6.
_LUT_SIZE = 65536


@lru_cache(maxsize=16)
def _linear_curve_luts(master, red, green, blue) -> np.ndarray:
    """``(3, _LUT_SIZE)`` linear-in/linear-out tables for one curve set.

    Cached: during a drag of any other slider the curves are unchanged,
    so the tables are built once (~10 ms) and reused.
    """
    srgb = linear_to_srgb(np.linspace(0.0, 1.0, _LUT_SIZE, dtype=np.float32))
    if master is not None:
        srgb = apply_curve_lut(srgb, build_curve_lut(master, resolution=256))
    luts = np.empty((3, _LUT_SIZE), dtype=np.float32)
    for channel_index, channel_pts in enumerate((red, green, blue)):
        channel = srgb
        if channel_pts is not None:
            channel = apply_curve_lut(
                srgb, build_curve_lut(channel_pts, resolution=256)
            )
        luts[channel_index] = srgb_to_linear(channel)
    luts.flags.writeable = False
    return luts
