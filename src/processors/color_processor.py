"""Color processor for saturation and vibrance in linear-light space."""

from __future__ import annotations

import cv2
import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage


class ColorProcessor(BaseProcessor):
    """Processor for saturation and vibrance.

    Operates on ``LinearImage`` (float32, linear-light). Internally uses
    OpenCV's HSV conversion which accepts float32 RGB in ``[0, 1]`` and
    returns ``(H in [0, 360], S in [0, 1], V in [0, 1])``.
    """

    def process(
        self,
        image: LinearImage,
        saturation: float = 0.0,
        vibrance: float = 0.0,
    ) -> LinearImage:
        """Apply color adjustments.

        Args:
            image: Input ``LinearImage``.
            saturation: Saturation adjustment (-100 .. +100).
            vibrance: Vibrance adjustment (-100 .. +100).

        Returns:
            New ``LinearImage`` with adjustments applied.
        """
        result = np.asarray(image, dtype=np.float32).copy()

        # Vibrance first so subsequent saturation acts on the boosted
        # values, matching the previous ordering.
        if vibrance != 0.0:
            result = self._adjust_vibrance(result, vibrance)
        if saturation != 0.0:
            result = self._adjust_saturation(result, saturation)
        return result

    def _adjust_saturation(self, image: LinearImage, value: float) -> LinearImage:
        """Uniform saturation scale in linear HSV.

        At -100 the result is a luminance-preserving grayscale (per
        OpenCV's HSV V == max(R, G, B)); at +100 saturation is doubled
        (clipped to 1.0).
        """
        factor = float(np.clip(1.0 + (value / 100.0), 0.0, 2.0))
        clipped = np.clip(image, 0.0, 1.0)
        hsv = cv2.cvtColor(clipped, cv2.COLOR_RGB2HSV)
        hsv[..., 1] = np.clip(hsv[..., 1] * factor, 0.0, 1.0)
        rgb = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
        return rgb.astype(np.float32, copy=False)

    def _adjust_vibrance(self, image: LinearImage, value: float) -> LinearImage:
        """Vibrance: stronger boost on low-saturation pixels.

        Formula: ``new_S = S + adjustment * (1 - S) * 0.5``. Negative
        values reduce S the same way (more on already-saturated pixels)
        which matches Lightroom's qualitative behavior.
        """
        if value == 0.0:
            return image

        adjustment = float(value) / 100.0
        clipped = np.clip(image, 0.0, 1.0)
        hsv = cv2.cvtColor(clipped, cv2.COLOR_RGB2HSV)
        s = hsv[..., 1]
        boost = adjustment * (1.0 - s) * 0.5
        hsv[..., 1] = np.clip(s + boost, 0.0, 1.0)
        rgb = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
        return rgb.astype(np.float32, copy=False)
