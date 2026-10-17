"""Local-contrast (midtone contrast) adjustment for linear-light images."""

from __future__ import annotations

import cv2
import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils import pixel_kernels
from src.utils.color_pipeline import LinearImage
from src.utils.spatial import gaussian_blur, relative_sigma


class ClarityProcessor(BaseProcessor):
    """Enhance or soften local/midtone contrast without clipping headroom.

    Shares Texture's signed-residual approach, but uses a much coarser
    blur radius so it expresses broad local contrast rather than
    medium-scale detail -- see
    docs/planning/implementation-notes/2026-09-30-texture.md section 6.
    """

    _SIGMA = 20.0
    _MAX_AMOUNT = 0.75

    def process(self, image: LinearImage, clarity: float = 0.0) -> LinearImage:
        """Apply Clarity in the range ``-100`` (soft) to ``100`` (punchy)."""
        source = np.asarray(image, dtype=np.float32)
        value = float(np.clip(clarity, -100.0, 100.0))
        if value == 0.0:
            return source.copy()
        blurred = gaussian_blur(source, relative_sigma(source, self._SIGMA))
        amount = (value / 100.0) * self._MAX_AMOUNT
        fused = pixel_kernels.unsharp(source, blurred, amount)
        if fused is not None:
            return fused
        detail = source - blurred
        result = source + (value / 100.0) * self._MAX_AMOUNT * detail
        return result.astype(np.float32, copy=False)
