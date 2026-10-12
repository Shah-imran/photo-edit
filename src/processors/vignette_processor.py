"""Radial vignette (periphery darkening/lightening) for linear-light images.

Unlike Texture, Clarity, and Dehaze (all blur-based local operations that
differ by scale or formula shape -- see
docs/planning/implementation-notes/2026-09-30-texture.md section 6,
docs/planning/implementation-notes/2026-10-12-clarity.md section 3, and
docs/planning/implementation-notes/2026-10-12-dehaze.md section 3), Vignette
is a genuinely different operation again: a spatially radial mask built
from pixel-center-relative distance from the image center, with no blur
involved at all. Positive values darken the periphery relative to the
center (an approximation of Lightroom's "Amount" vignette control);
negative values lighten it instead (a creative fog/flash-style lift).
"""

from __future__ import annotations

import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage


class VignetteProcessor(BaseProcessor):
    """Darken (or lighten) the image periphery relative to its center.

    Positive values (0..100) darken the periphery by multiplying by a
    smooth radial falloff mask that stays at 1.0 near the center and
    falls to ``1 - strength`` at the extreme corners. Negative values
    (-100..0) lighten the periphery instead, pushing peripheral pixels
    toward brighter values proportional to the same falloff, without
    clipping, so highlight headroom is preserved.
    """

    _MIDPOINT = 0.6
    _LIGHTEN_COLOR = 1.0

    def process(self, image: LinearImage, vignette: float = 0.0) -> LinearImage:
        """Apply Vignette in the range ``-100`` (lighten) to ``100`` (darken)."""
        source = np.asarray(image, dtype=np.float32)
        value = float(np.clip(vignette, -100.0, 100.0))
        if value == 0.0:
            return source.copy()

        height, width = source.shape[0], source.shape[1]
        half_h = max(height / 2.0, 1e-6)
        half_w = max(width / 2.0, 1e-6)

        rows = (np.arange(height, dtype=np.float32) + 0.5) - half_h
        cols = (np.arange(width, dtype=np.float32) + 0.5) - half_w
        dy = (rows / half_h)[:, np.newaxis]
        dx = (cols / half_w)[np.newaxis, :]
        radius = np.sqrt(dx ** 2 + dy ** 2) / np.sqrt(2.0)
        radius = np.clip(radius, 0.0, 1.0)

        # Cubic smoothstep from _MIDPOINT (0) to 1.0 (1).
        span = max(1.0 - self._MIDPOINT, 1e-6)
        t = np.clip((radius - self._MIDPOINT) / span, 0.0, 1.0)
        edge_t = (t * t * (3.0 - 2.0 * t))[..., np.newaxis]

        if value > 0.0:
            strength = value / 100.0
            mask = 1.0 - edge_t * strength
            result = source * mask
        else:
            strength = -value / 100.0
            result = source + (self._LIGHTEN_COLOR - source) * edge_t * strength

        return result.astype(np.float32, copy=False)
