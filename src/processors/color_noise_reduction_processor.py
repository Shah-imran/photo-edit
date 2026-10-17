"""Chrominance-only noise reduction for linear-light images.

Luminance Noise Reduction ("Luminance NR") smooths the image's
**luminance** channel while leaving per-pixel color ratios untouched (see
docs/planning/implementation-notes/2026-10-12-luminance-noise-reduction.md).
Color Noise Reduction ("Color NR") is its exact complement: it smooths the
image's **chrominance** (color) while leaving luminance/brightness detail
untouched. This is the standard Lightroom division of labor -- Color NR
targets color speckle/blotches (chroma noise) without softening edge
detail the way Luminance NR targets brightness grain.

Unlike Luminance NR's "add a luminance-only delta to every channel" trick,
Color NR uses an explicit, exactly-invertible luminance/chrominance
decomposition: it derives two opponent chroma channels (``Cr = R - Y`` and
``Cb = B - Y``), smooths each independently with a plain (non-edge-aware)
Gaussian blur, blends the smoothed chroma toward the original by the
requested amount, and reconstructs RGB from ``(Y, Cr_blended, Cb_blended)``
using the algebraic inverse of the decomposition. See
docs/planning/implementation-notes/2026-10-12-color-noise-reduction.md
section 3 for the exact formulas and a note on verifying the round trip.
"""

from __future__ import annotations

import cv2
import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage


class ColorNoiseReductionProcessor(BaseProcessor):
    """Reduce chrominance-channel noise with a plain Gaussian chroma blur.

    A Rec.709 luminance channel ``Y`` is derived from the linear-light RGB
    source, along with two opponent chroma channels ``Cr = R - Y`` and
    ``Cb = B - Y``. Each chroma channel is smoothed independently with
    ``cv2.GaussianBlur`` (deliberately *not* edge-aware, unlike Luminance
    NR's bilateral filter -- color blotches don't need edge-awareness the
    way luminance grain does, and Lightroom's own Color NR is itself a
    fairly aggressive, non-edge-aware chroma blur), blended toward the
    original chroma by the requested amount, and the RGB image is
    reconstructed from ``(Y, Cr_blended, Cb_blended)`` using the exact
    algebraic inverse of the decomposition. Because luminance ``Y`` is
    carried through unchanged, this never shifts brightness -- only color
    speckle is smoothed.
    """

    _LUMINANCE_WEIGHTS = (0.2126, 0.7152, 0.0722)

    # Gaussian sigma for the chroma blur. Moderate and fixed, in the same
    # spirit as the other Detail/Effects processors' internal constants
    # (Sharpening's sigma=1.0, Luminance NR's d=9 bilateral neighborhood).
    # 4.0 sits in the middle of the documented 3.0-5.0 range: large enough
    # to meaningfully average down color-speckle-scale chroma noise over a
    # several-pixel neighborhood, small enough that it does not bleed color
    # across unrelated, large-scale color regions of a typical photo. See
    # docs/planning/implementation-notes/2026-10-12-color-noise-reduction.md
    # section 5 for the full rationale.
    _CHROMA_SIGMA = 4.0

    def process(
        self, image: LinearImage, color_nr: float = 0.0
    ) -> LinearImage:
        """Apply Color NR in the range ``0`` (none) to ``100`` (strongest)."""
        source = np.asarray(image, dtype=np.float32)
        value = float(np.clip(color_nr, 0.0, 100.0))
        if value == 0.0:
            return source.copy()

        wr, wg, wb = self._LUMINANCE_WEIGHTS
        r, g, b = source[..., 0], source[..., 1], source[..., 2]
        luminance = (wr * r + wg * g + wb * b).astype(np.float32)
        cr = (r - luminance).astype(np.float32)
        cb = (b - luminance).astype(np.float32)

        smoothed_cr = cv2.GaussianBlur(
            cr,
            (0, 0),
            sigmaX=self._CHROMA_SIGMA,
            borderType=cv2.BORDER_REFLECT_101,
        )
        smoothed_cb = cv2.GaussianBlur(
            cb,
            (0, 0),
            sigmaX=self._CHROMA_SIGMA,
            borderType=cv2.BORDER_REFLECT_101,
        )

        t = value / 100.0
        cr_blended = cr + t * (smoothed_cr - cr)
        cb_blended = cb + t * (smoothed_cb - cb)

        # Exact algebraic inverse of (Y, Cr, Cb) = (wr*R+wg*G+wb*B, R-Y, B-Y):
        #   R = Y + Cr_blended
        #   B = Y + Cb_blended
        #   G = Y - (wr*Cr_blended + wb*Cb_blended) / wg   (wg is never 0)
        new_r = luminance + cr_blended
        new_b = luminance + cb_blended
        new_g = luminance - (wr * cr_blended + wb * cb_blended) / wg

        result = np.stack([new_r, new_g, new_b], axis=-1)
        return result.astype(np.float32, copy=False)
