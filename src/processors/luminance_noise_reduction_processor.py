"""Edge-preserving luminance noise reduction for linear-light images.

Every prior Effects/Detail processor (Texture, Clarity, Dehaze, Vignette,
Grain, Sharpening) is built from a Gaussian blur residual, a radial mask,
or seeded noise. Luminance Noise Reduction ("Luminance NR") is
deliberately different: it uses an *edge-preserving* smoothing filter
(OpenCV's bilateral filter) applied to the image's **luminance channel
only**, leaving per-pixel chrominance (color) ratios untouched. This
reduces grain/noise-scale brightness variation without smearing color
edges or flattening the image the way an ordinary blur would. See
docs/planning/implementation-notes/2026-10-12-luminance-noise-reduction.md
section 3 for the exact formula and section 5 for the rationale behind
the chosen bilateral-filter constants.
"""

from __future__ import annotations

import cv2
import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage


class LuminanceNoiseReductionProcessor(BaseProcessor):
    """Reduce luminance-channel noise with an edge-preserving bilateral filter.

    A Rec.709 luminance channel is derived from the linear-light RGB
    source, smoothed with ``cv2.bilateralFilter`` (which preserves edges
    far better than a Gaussian blur, since its range term suppresses
    smoothing across large intensity jumps), and the resulting luminance
    *delta* (smoothed minus original) is added equally to all three
    channels. Adding the same scalar delta to every channel shifts each
    pixel's luminance toward its smoothed value while leaving its
    chrominance ratios (and thus its color) unchanged -- the entire point
    of "luminance-only" noise reduction, as opposed to a plain blur which
    would also soften color detail and edges.
    """

    # Bilateral filter diameter: a 9x9 neighborhood, matching the other
    # Detail/Effects processors' modest, fixed spatial extents (e.g.
    # Sharpening's sigma=1 Gaussian, Grain's ~1/3-resolution noise field).
    _DIAMETER = 9
    # sigmaColor is in the same linear-light units as the image itself
    # (nominally [0, 1], though HDR headroom can exceed 1). 0.1 is a small
    # fraction of that range -- large enough to smooth sensor-noise-scale
    # luminance jitter, small enough that genuine edges (a meaningfully
    # large fraction of the full range) are still treated as edges rather
    # than smoothed across.
    _SIGMA_COLOR = 0.1
    # sigmaSpace matches the diameter in spatial extent (both ~9), the
    # usual OpenCV convention when d > 0.
    _SIGMA_SPACE = 9.0
    # Below this minimum dimension, cv2.bilateralFilter is skipped as a
    # defensive bypass -- see the implementation note section 5. In
    # testing, cv2.bilateralFilter did not crash even on 1x1/2x2 inputs,
    # but the bypass is kept anyway as cheap insurance against degenerate
    # OpenCV edge cases on future OpenCV versions, and it avoids running a
    # non-trivial filter on geometry too small for its neighborhood to be
    # meaningful.
    _MIN_FILTER_DIMENSION = 3

    _LUMINANCE_WEIGHTS = (0.2126, 0.7152, 0.0722)

    def process(
        self, image: LinearImage, luminance_nr: float = 0.0
    ) -> LinearImage:
        """Apply Luminance NR in the range ``0`` (none) to ``100`` (strongest)."""
        source = np.asarray(image, dtype=np.float32)
        value = float(np.clip(luminance_nr, 0.0, 100.0))
        if value == 0.0:
            return source.copy()

        height, width = source.shape[0], source.shape[1]
        if min(height, width) < self._MIN_FILTER_DIMENSION:
            # Too small for the bilateral filter's neighborhood to mean
            # anything; treat as a no-op smoothing (delta == 0).
            return source.copy()

        r, g, b = self._LUMINANCE_WEIGHTS
        luminance = (
            r * source[..., 0] + g * source[..., 1] + b * source[..., 2]
        ).astype(np.float32)

        smoothed = cv2.bilateralFilter(
            luminance,
            d=self._DIAMETER,
            sigmaColor=self._SIGMA_COLOR,
            sigmaSpace=self._SIGMA_SPACE,
        )
        delta = smoothed - luminance

        t = value / 100.0
        result = source + (t * delta)[..., np.newaxis]
        return result.astype(np.float32, copy=False)
