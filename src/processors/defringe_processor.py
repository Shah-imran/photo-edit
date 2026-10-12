"""Defringe (purple/green edge-fringe desaturation) for linear-light images.

Lateral chromatic aberration (see
``src/processors/remove_chromatic_aberration_processor.py``) is a
*geometric* misregistration between channels. Even after a fixed,
profile-free approximate correction (Remove CA), a visible side-effect
often remains at high-contrast edges: a thin band of purple/magenta or
green fringing where the uncorrected channel misalignment partially
survives. Lightroom's Defringe targets this residual artifact directly,
as a color-domain cleanup rather than a geometric one -- it desaturates
only pixels that are *both* near a strong luminance edge *and* sitting
in the purple or green hue band, leaving strongly saturated purple/green
subject matter away from edges untouched. See
docs/planning/implementation-notes/2026-10-12-defringe.md for the full
design rationale, including why 25 degrees was chosen as the hue-band
half-width.
"""

from __future__ import annotations

import cv2
import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage


def _circular_hue_distance(hue_deg: np.ndarray, center_deg: float) -> np.ndarray:
    """Shortest distance between ``hue_deg`` and ``center_deg`` on a circle."""
    diff = np.abs(hue_deg - center_deg) % 360.0
    return np.minimum(diff, 360.0 - diff)


class DefringeProcessor(BaseProcessor):
    """Desaturate purple/green color fringing specifically at edges.

    Builds a per-pixel desaturation strength that is the product of:

    - an edge-strength mask (Sobel gradient magnitude on Rec.709
      luminance, normalized with the same soft ratio
      ``grad_mag / (grad_mag + 0.1)`` that Sharpening's own edge mask
      uses, for consistency with this codebase's established pattern),
      and
    - a hue-band membership mask (a circular Gaussian bump around the
      purple ~290 degree and green ~110 degree hue centers, weighted
      down for near-neutral pixels where hue is numerically unstable).

    Pixels are desaturated toward their own luminance (brightness is
    preserved; only color is removed), scaled by ``value / 100.0``.
    Zero returns an identity copy immediately, without computing any of
    the Sobel/hue machinery, both for performance and so the zero case
    is an exact identity test.
    """

    # Gaussian hue-band half-width in degrees. Narrow enough that
    # ordinary strongly-saturated purple/green subjects (which sit near
    # but not exactly at these fringe-characteristic hues) are not
    # heavily desaturated when away from edges, but wide enough to catch
    # the hue variation that real fringing actually exhibits. See the
    # implementation note section 5 for the empirical check that this
    # value discriminates edge-fringe from flat saturated color.
    _HUE_BAND_WIDTH_DEG = 25.0
    _PURPLE_HUE_DEG = 290.0
    _GREEN_HUE_DEG = 110.0
    # Soft edge-mask epsilon, matching Sharpening's ``_MASK_EPSILON``
    # pattern in spirit (a soft 0..1 ratio), using the exact 0.1 value
    # specified for Defringe's own gradient-magnitude scale.
    _EDGE_EPSILON = 0.1
    # Chroma below which hue is considered numerically unreliable
    # (near-neutral/gray pixels) and hue-band membership is suppressed.
    _CHROMA_GATE = 0.05

    def process(self, image: LinearImage, defringe: float = 0.0) -> LinearImage:
        """Apply Defringe in the range ``0`` (none) to ``100`` (strongest)."""
        source = np.asarray(image, dtype=np.float32)
        value = float(np.clip(defringe, 0.0, 100.0))
        if value == 0.0:
            return source.copy()

        r, g, b = source[..., 0], source[..., 1], source[..., 2]
        y = 0.2126 * r + 0.7152 * g + 0.0722 * b

        gx = cv2.Sobel(y, cv2.CV_32F, 1, 0, ksize=3) / 8.0
        gy = cv2.Sobel(y, cv2.CV_32F, 0, 1, ksize=3) / 8.0
        grad_mag = np.sqrt(gx ** 2 + gy ** 2)
        edge_mask = grad_mag / (grad_mag + self._EDGE_EPSILON)

        # Hue/chroma are computed from a clipped copy -- clipping only
        # affects this hue/chroma computation, never the actual output
        # pixels, preserving HDR headroom in the result.
        c = np.clip(source, 0.0, 1.0)
        cr, cg, cb = c[..., 0], c[..., 1], c[..., 2]
        maxc = np.maximum(np.maximum(cr, cg), cb)
        minc = np.minimum(np.minimum(cr, cg), cb)
        delta = maxc - minc
        safe_delta = np.where(delta < 1e-6, 1.0, delta)
        hue_r = 60.0 * (((cg - cb) / safe_delta) % 6.0)
        hue_g = 60.0 * (((cb - cr) / safe_delta) + 2.0)
        hue_b = 60.0 * (((cr - cg) / safe_delta) + 4.0)
        hue = np.where(maxc == cr, hue_r, np.where(maxc == cg, hue_g, hue_b))
        chroma_weight = np.clip(delta / self._CHROMA_GATE, 0.0, 1.0)

        purple_membership = np.exp(
            -0.5 * (_circular_hue_distance(hue, self._PURPLE_HUE_DEG)
                    / self._HUE_BAND_WIDTH_DEG) ** 2
        )
        green_membership = np.exp(
            -0.5 * (_circular_hue_distance(hue, self._GREEN_HUE_DEG)
                    / self._HUE_BAND_WIDTH_DEG) ** 2
        )
        hue_mask = np.clip(purple_membership + green_membership, 0.0, 1.0) * chroma_weight

        strength = (value / 100.0) * edge_mask * hue_mask

        neutral = np.stack([y, y, y], axis=-1)
        result = source + strength[..., np.newaxis] * (neutral - source)
        return result.astype(np.float32, copy=False)
