"""Editorial White Balance (Temperature/Tint) processor.

Unlike ``CurveProcessor`` (deliberately applied in sRGB-encoded space),
white balance is a per-channel multiplicative gain -- a diagonal/von Kries
transform -- which is only physically meaningful on linear radiometric
values. This processor therefore operates directly on the
:data:`src.utils.color_pipeline.LinearImage` (float32, ``(H, W, 3)``,
linear-light, ``[0, 1]``), the same way ``ExposureProcessor``/
``TonalProcessor`` do; there is no sRGB round-trip here.

Temperature and Tint use the same -100..100 relative range as
Highlights/Shadows/Whites/Blacks rather than an absolute Kelvin scale:
there is no reliable "as-shot" baseline temperature for a JPEG, and RAW
files already had camera white balance applied by ``rawpy`` before this
pipeline sees them (see ``src/services/raw_service.py``), so an absolute
scale would have no defined zero point. This is a purely editorial shift
on top of whatever white balance the source pixels already have.
"""

from __future__ import annotations

import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage


class WhiteBalanceProcessor(BaseProcessor):
    """Processor for the Temperature/Tint sliders.

    Temperature rotates Red against Blue (positive = warmer/more orange,
    negative = cooler/more blue); Green is untouched by temperature. Tint
    rotates Green against Red+Blue together (positive = more magenta/less
    green, negative = more green), matching Lightroom's slider
    directionality.
    """

    #: How strongly a full-range (-100/+100) slide shifts a channel gain.
    #: Chosen so the effect is clearly visible without immediately
    #: clipping a channel -- same order of magnitude as
    #: ``TonalProcessor._RECOVERY_STRENGTH``.
    _TEMPERATURE_STRENGTH = 0.35
    _TINT_STRENGTH = 0.35

    def process(
        self,
        image: LinearImage,
        temperature: float = 0.0,
        tint: float = 0.0,
    ) -> LinearImage:
        """Apply a white balance gain shift.

        Args:
            image: Input ``LinearImage``.
            temperature: -100..100. Positive warms (boosts R, cuts B),
                negative cools (boosts B, cuts R).
            tint: -100..100. Positive shifts toward magenta (cuts G,
                boosts R and B), negative shifts toward green (boosts G).

        Returns:
            A new float32 array of the same shape. Values are not
            clamped -- clipping happens at final encode, matching every
            other processor in the pipeline.
        """
        result = np.array(image, dtype=np.float32, copy=True)

        if temperature == 0.0 and tint == 0.0:
            return result

        t = temperature / 100.0
        n = tint / 100.0

        r_gain = 1.0 + t * self._TEMPERATURE_STRENGTH + n * self._TINT_STRENGTH * 0.5
        g_gain = 1.0 - n * self._TINT_STRENGTH
        b_gain = 1.0 - t * self._TEMPERATURE_STRENGTH + n * self._TINT_STRENGTH * 0.5

        result[..., 0] *= r_gain
        result[..., 1] *= g_gain
        result[..., 2] *= b_gain
        return result
