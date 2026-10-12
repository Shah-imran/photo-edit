"""Classic unsharp-mask sharpening for linear-light images.

Texture (see docs/planning/implementation-notes/2026-09-30-texture.md)
already enhances medium-scale detail with a signed, bidirectional
residual at ``sigma=2``. Sharpening is deliberately different in both
scale and direction: it targets fine, pixel-level edge detail at a
smaller blur radius (``sigma=1.0``), and -- matching Lightroom's
"Amount" semantics -- only ever adds sharpening (``0..100``, no
softening direction), unlike Texture/Clarity/Dehaze/Vignette's
``-100..100`` range. See
docs/planning/implementation-notes/2026-10-12-sharpening.md section 3
for the exact formula and section 5 for why the masking safeguard is
needed.
"""

from __future__ import annotations

import cv2
import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage


class SharpeningProcessor(BaseProcessor):
    """Add fine-detail unsharp-mask sharpening with an edge-aware safeguard.

    A Gaussian base at a small ``sigma`` isolates fine, pixel-level
    detail (the opposite end of the spatial-frequency spectrum from
    Texture's medium-scale ``sigma=2`` enhancement). The signed residual
    (``source - blurred``) is scaled by a soft, edge-aware mask derived
    from the residual's own magnitude, so flat or already-smooth regions
    (where the residual is near zero) receive little to no added
    sharpening, while high-contrast edges (large residual) receive close
    to the full effect. This keeps Sharpening from amplifying sensor
    noise or banding in flat skies and shadows, without a separate
    user-facing Masking slider.
    """

    _SIGMA = 1.0
    _MAX_AMOUNT = 1.25
    _MASK_EPSILON = 0.02

    def process(self, image: LinearImage, sharpening: float = 0.0) -> LinearImage:
        """Apply Sharpening in the range ``0`` (none) to ``100`` (strongest)."""
        source = np.asarray(image, dtype=np.float32)
        value = float(np.clip(sharpening, 0.0, 100.0))
        if value == 0.0:
            return source.copy()

        blurred = cv2.GaussianBlur(
            source, (0, 0), sigmaX=self._SIGMA, sigmaY=self._SIGMA,
            borderType=cv2.BORDER_REFLECT_101,
        )
        detail = source - blurred

        # Soft edge mask: near 0 where the residual is near 0 (flat/smooth
        # regions), approaching 1 where the residual is large relative to
        # ``_MASK_EPSILON`` (real edges). This is a cheap, non-"full
        # edge-detector" safeguard against over-sharpening flat areas --
        # see the implementation note section 3 for the exact derivation.
        edge_strength = np.abs(detail)
        mask = edge_strength / (edge_strength + self._MASK_EPSILON)

        amount = (value / 100.0) * self._MAX_AMOUNT
        result = source + amount * detail * mask
        return result.astype(np.float32, copy=False)
