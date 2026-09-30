"""Color Grading: Shadows/Midtones/Highlights tonal color-tint processor.

Like ``HslMixerProcessor``, this converts to **linear-light HSV** via
``cv2.cvtColor`` -- but only to *measure* luminance (``V``) for tonal-range
weighting, never to produce the output. Unlike the HSL Mixer (which rotates
a pixel's existing hue), Color Grading blends each pixel toward a fixed
tint color per tonal range, directly in RGB against the pixel's original,
unclipped value -- see
docs/planning/implementation-notes/2026-09-30-color-grading.md section 3
for why: it is what "grading" means (a global tint over a tonal range,
including on neutral/gray pixels a hue-rotation approach cannot reach),
and it preserves linear-light headroom for any pixel no active range
covers.

Three tonal ranges -- Shadows, Midtones, Highlights -- each get independent
Hue/Saturation/Luminance parameters, plus two global parameters:
``blending`` (window width) and ``balance`` (shifts the midtone center).
Deliberate simplifications of Lightroom's own wheel-based UI and exact
tone-range crossover math (documented in the implementation note section 1).
"""

from __future__ import annotations

from typing import Dict, Tuple

import cv2
import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage

COLOR_GRADING_RANGES: Tuple[str, str, str] = ("shadows", "midtones", "highlights")
COLOR_GRADING_CHANNELS: Tuple[str, str, str] = ("hue", "sat", "lum")

#: Fixed luminance (HSV V) anchors for the shadow/highlight ranges. Only
#: the midtone center moves (via ``balance``) -- see module docstring.
_SHADOW_CENTER = 0.0
_HIGHLIGHT_CENTER = 1.0

#: How far `balance` (-100..100) can shift the midtone center away from
#: its default 0.5, each direction.
_BALANCE_SHIFT_RANGE = 0.25

#: Raised-cosine window full-width bounds as `blending` (0..100) sweeps
#: from narrow/hard-edged to wide/smooth. At `blending=50`, `W=1.0` --
#: double the 0.5 default center spacing, the same Hann-window 50%-overlap
#: COLA shape ``HslMixerProcessor`` already uses.
_WIDTH_AT_BLENDING_0 = 0.4
_WIDTH_AT_BLENDING_100 = 1.6

#: Fully-weighted, full-saturation blend fraction toward a range's pure
#: hue tint -- a visible tint, not a full color replacement.
_TINT_STRENGTH = 0.6

#: Fully-weighted, full-range luminance slider's additive RGB brightness
#: shift.
_LUM_STRENGTH = 0.25


def default_color_grading_params() -> Dict[str, float]:
    """Return the identity (all-zero, default blending/balance) 11-key dict."""
    params = {
        f"{range_}_{channel}": 0.0
        for range_ in COLOR_GRADING_RANGES
        for channel in COLOR_GRADING_CHANNELS
    }
    params["blending"] = 50.0
    params["balance"] = 0.0
    return params


def _range_centers(balance: float) -> Dict[str, float]:
    """Return this call's shadow/midtone/highlight luminance centers."""
    midtone_center = 0.5 + (balance / 100.0) * _BALANCE_SHIFT_RANGE
    return {
        "shadows": _SHADOW_CENTER,
        "midtones": midtone_center,
        "highlights": _HIGHLIGHT_CENTER,
    }


def _window_width(blending: float) -> float:
    """Raised-cosine full width for the given ``blending`` (0..100)."""
    fraction = blending / 100.0
    return _WIDTH_AT_BLENDING_0 + fraction * (
        _WIDTH_AT_BLENDING_100 - _WIDTH_AT_BLENDING_0
    )


def _range_weight(v: np.ndarray, center: float, width: float) -> np.ndarray:
    """Raised-cosine weight of ``center`` at each luminance in ``v``.

    ``v`` is a bounded linear domain (``[0, 1]``), not cyclic like hue, so
    no wraparound handling is needed here (unlike
    ``hsl_mixer_processor._band_weight``).
    """
    distance = np.abs(v - center)
    return np.where(
        distance < width / 2.0,
        0.5 * (1.0 + np.cos(2.0 * np.pi * distance / width)),
        0.0,
    )


class ColorGradingProcessor(BaseProcessor):
    """Processor for the 3-range (Shadows/Midtones/Highlights) Color Grading."""

    def process(self, image: LinearImage, **params: float) -> LinearImage:
        """Apply tonal-range color grading.

        Args:
            image: Input ``LinearImage``.
            **params: Up to 11 keys: ``"<range>_hue"`` (0..360),
                ``"<range>_sat"`` (0..100), ``"<range>_lum"`` (-100..100)
                for ``range`` in :data:`COLOR_GRADING_RANGES`, plus
                ``"blending"`` (0..100, default 50) and ``"balance"``
                (-100..100, default 0). Missing keys default to identity.

        Returns:
            A new float32 array of the same shape.
        """
        result = np.array(image, dtype=np.float32, copy=True)

        range_params = {
            range_: (
                params.get(f"{range_}_hue", 0.0),
                params.get(f"{range_}_sat", 0.0),
                params.get(f"{range_}_lum", 0.0),
            )
            for range_ in COLOR_GRADING_RANGES
        }
        if all(
            sat == 0.0 and lum == 0.0 for _, sat, lum in range_params.values()
        ):
            return result

        original_rgb = result[..., :3]
        clipped = np.clip(original_rgb, 0.0, 1.0)
        hsv = cv2.cvtColor(clipped, cv2.COLOR_RGB2HSV)
        v = hsv[..., 2]

        balance = params.get("balance", 0.0)
        blending = params.get("blending", 50.0)
        centers = _range_centers(balance)
        width = _window_width(blending)

        raw_weights = {
            range_: _range_weight(v, centers[range_], width)
            for range_ in COLOR_GRADING_RANGES
        }
        total_weight = sum(raw_weights.values())
        safe_total = np.where(total_weight > 0.0, total_weight, 1.0)
        normalized_weights = {
            range_: np.where(total_weight > 0.0, w / safe_total, 0.0)
            for range_, w in raw_weights.items()
        }

        total_amount = np.zeros_like(v)
        tint_numerator = np.zeros((*v.shape, 3), dtype=np.float32)
        lum_delta = np.zeros_like(v)

        for range_, (hue, sat, lum) in range_params.items():
            weight = normalized_weights[range_]
            amount = weight * (sat / 100.0) * _TINT_STRENGTH
            total_amount += amount
            if sat != 0.0:
                tint_hsv = np.array([[[hue, 1.0, 1.0]]], dtype=np.float32)
                tint_rgb = cv2.cvtColor(tint_hsv, cv2.COLOR_HSV2RGB)[0, 0]
                tint_numerator += amount[..., np.newaxis] * tint_rgb
            lum_delta += weight * (lum / 100.0) * _LUM_STRENGTH

        total_amount = np.clip(total_amount, 0.0, 1.0)
        safe_amount = np.where(total_amount > 0.0, total_amount, 1.0)[..., np.newaxis]
        combined_tint = np.where(
            total_amount[..., np.newaxis] > 0.0,
            tint_numerator / safe_amount,
            0.0,
        )

        blended = (
            original_rgb * (1.0 - total_amount[..., np.newaxis])
            + combined_tint * total_amount[..., np.newaxis]
        )
        blended = blended + lum_delta[..., np.newaxis]

        result[..., :3] = blended.astype(np.float32, copy=False)
        return result
