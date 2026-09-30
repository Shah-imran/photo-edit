"""Mid-frequency texture adjustment for linear-light images."""

from __future__ import annotations

import cv2
import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage


class TextureProcessor(BaseProcessor):
    """Enhance or soften mid-frequency detail without clipping headroom."""

    _SIGMA = 2.0
    _MAX_AMOUNT = 0.75

    def process(self, image: LinearImage, texture: float = 0.0) -> LinearImage:
        """Apply Texture in the range ``-100`` (soft) to ``100`` (crisp)."""
        source = np.asarray(image, dtype=np.float32)
        value = float(np.clip(texture, -100.0, 100.0))
        if value == 0.0:
            return source.copy()
        blurred = cv2.GaussianBlur(
            source, (0, 0), sigmaX=self._SIGMA, sigmaY=self._SIGMA,
            borderType=cv2.BORDER_REFLECT_101,
        )
        detail = source - blurred
        result = source + (value / 100.0) * self._MAX_AMOUNT * detail
        return result.astype(np.float32, copy=False)
