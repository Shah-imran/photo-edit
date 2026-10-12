"""Haze/atmospheric-veil removal (and creative fog addition) for
linear-light images.

Unlike Texture and Clarity (both signed-residual/unsharp local-contrast
tricks that differ only by blur scale -- see
docs/planning/implementation-notes/2026-09-30-texture.md section 6 and
docs/planning/implementation-notes/2026-10-12-clarity.md section 3),
Dehaze is a genuinely different operation: a lightweight approximation
of Lightroom's dark-channel-style haze removal. It estimates a per-pixel
haze "veil" from the minimum across RGB channels (a dark-channel/airlight
approximation), lightly blurs that estimate to approximate a transmission
map, and subtracts a fraction of it while rescaling to restore overall
level. This is deliberately an approximation, not a physically-accurate
atmospheric scattering model.
"""

from __future__ import annotations

import cv2
import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage


class DehazeProcessor(BaseProcessor):
    """Remove (or add) a haze veil without clipping headroom.

    Positive values (0..100) estimate and subtract a haze veil, rescaling
    to restore overall level -- an approximation of dark-channel haze
    removal. Negative values (-100..0) blend toward a light gray/white
    haze color proportional to magnitude, adding creative fog (Lightroom
    also supports this on its single -100..100 Dehaze slider).
    """

    _SIGMA = 15.0
    _VEIL_STRENGTH_FACTOR = 0.9
    _EPSILON = 1e-3
    _HAZE_COLOR = 0.85

    def process(self, image: LinearImage, dehaze: float = 0.0) -> LinearImage:
        """Apply Dehaze in the range ``-100`` (add fog) to ``100`` (remove haze)."""
        source = np.asarray(image, dtype=np.float32)
        value = float(np.clip(dehaze, -100.0, 100.0))
        if value == 0.0:
            return source.copy()

        if value > 0.0:
            strength = value / 100.0
            dark_channel = np.min(source, axis=-1)
            veil = cv2.GaussianBlur(
                dark_channel, (0, 0), sigmaX=self._SIGMA, sigmaY=self._SIGMA,
                borderType=cv2.BORDER_REFLECT_101,
            )[..., np.newaxis]
            denom = max(1.0 - strength * self._VEIL_STRENGTH_FACTOR, self._EPSILON)
            result = (source - strength * veil) / denom
        else:
            strength = -value / 100.0
            result = source + strength * (self._HAZE_COLOR - source)

        return result.astype(np.float32, copy=False)
