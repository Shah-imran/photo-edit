"""HSL Color Mixer: per-color-range Hue/Saturation/Luminance processor.

Like ``ColorProcessor`` (Saturation/Vibrance), this operates directly in
**linear-light HSV** via ``cv2.cvtColor`` -- not converting to sRGB first,
unlike ``CurveProcessor``'s deliberate choice. Kept consistent with the
existing saturation/vibrance precedent rather than introducing a second
convention for hue-based math.

Eight evenly spaced hue bands (45 degrees apart) -- Red, Orange, Yellow,
Green, Aqua, Blue, Purple, Magenta -- each get independent Hue/Saturation/
Luminance sliders. This is a deliberate simplification versus Lightroom's
own non-uniform band widths (documented in
docs/planning/implementation-notes/2026-09-30-hsl-color-mixer.md section
1): even spacing plus a raised-cosine falloff whose width exactly equals
twice the band spacing gives a mathematically clean partition of unity
(the 8 band weights sum to exactly 1.0 at every hue, the classic
Hann-window 50%-overlap COLA property) with no extra normalization step.
"""

from __future__ import annotations

from typing import Dict

import cv2
import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage

#: Band name -> hue center in degrees (HSV hue, as returned by
#: ``cv2.cvtColor(..., COLOR_RGB2HSV)``).
HSL_BAND_CENTERS: Dict[str, float] = {
    "red": 0.0,
    "orange": 45.0,
    "yellow": 90.0,
    "green": 135.0,
    "aqua": 180.0,
    "blue": 225.0,
    "purple": 270.0,
    "magenta": 315.0,
}

HSL_BAND_NAMES = tuple(HSL_BAND_CENTERS.keys())
HSL_CHANNELS = ("hue", "sat", "lum")

#: Raised-cosine window width in degrees. Exactly twice the 45-degree band
#: spacing so adjacent windows overlap at 50% -- see module docstring.
_BAND_WIDTH_DEG = 90.0

#: Maximum hue rotation (degrees) a fully-weighted, full-range (+/-100)
#: hue slider applies -- large enough to be clearly visible, small enough
#: to stay a "nudge" rather than a color-replace effect.
_MAX_HUE_SHIFT_DEG = 40.0

#: Luminance (V) delta a fully-weighted, full-range luminance slider
#: applies.
_LUM_STRENGTH = 0.3


def _band_weight(hue_deg: np.ndarray, center: float) -> np.ndarray:
    """Raised-cosine weight of ``center`` at each hue in ``hue_deg``.

    Uses the signed hue-wraparound trick so a band centered at 0 (Red)
    correctly overlaps with Magenta (315) across the 360/0 boundary.
    """
    signed_diff = ((hue_deg - center + 180.0) % 360.0) - 180.0
    distance = np.abs(signed_diff)
    return np.where(
        distance < _BAND_WIDTH_DEG / 2.0,
        0.5 * (1.0 + np.cos(2.0 * np.pi * distance / _BAND_WIDTH_DEG)),
        0.0,
    )


def default_hsl_params() -> Dict[str, float]:
    """Return the identity (all-zero) 24-key HSL parameter dict."""
    return {
        f"{band}_{channel}": 0.0
        for band in HSL_BAND_NAMES
        for channel in HSL_CHANNELS
    }


class HslMixerProcessor(BaseProcessor):
    """Processor for the 8-band HSL Color Mixer."""

    def process(self, image: LinearImage, **band_params: float) -> LinearImage:
        """Apply per-band hue/saturation/luminance adjustments.

        Args:
            image: Input ``LinearImage``.
            **band_params: Up to 24 keys of the form ``"<band>_hue"``,
                ``"<band>_sat"``, ``"<band>_lum"`` (each -100..100) for
                ``band`` in :data:`HSL_BAND_NAMES`. Missing keys default
                to 0 (no effect for that band/channel).

        Returns:
            A new float32 array of the same shape.
        """
        result = np.array(image, dtype=np.float32, copy=True)

        if not band_params or all(v == 0.0 for v in band_params.values()):
            return result

        clipped = np.clip(result[..., :3], 0.0, 1.0)
        hsv = cv2.cvtColor(clipped, cv2.COLOR_RGB2HSV)
        hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]

        hue_shift = np.zeros_like(hue)
        sat_factor = np.zeros_like(hue)
        lum_delta = np.zeros_like(hue)

        for band, center in HSL_BAND_CENTERS.items():
            hue_p = band_params.get(f"{band}_hue", 0.0)
            sat_p = band_params.get(f"{band}_sat", 0.0)
            lum_p = band_params.get(f"{band}_lum", 0.0)
            if hue_p == 0.0 and sat_p == 0.0 and lum_p == 0.0:
                continue
            weight = _band_weight(hue, center)
            hue_shift += weight * (hue_p / 100.0) * _MAX_HUE_SHIFT_DEG
            sat_factor += weight * (sat_p / 100.0)
            lum_delta += weight * (lum_p / 100.0) * _LUM_STRENGTH

        new_hue = np.mod(hue + hue_shift, 360.0)
        new_sat = np.clip(sat * (1.0 + sat_factor), 0.0, 1.0)
        new_val = np.clip(val + lum_delta, 0.0, 1.0)

        new_hsv = np.stack([new_hue, new_sat, new_val], axis=-1).astype(np.float32)
        result[..., :3] = cv2.cvtColor(new_hsv, cv2.COLOR_HSV2RGB)
        return result
