"""Lateral chromatic aberration correction for linear-light images.

Lateral chromatic aberration ("CA") shows up as the red and blue channels
being radially misaligned relative to green, growing worse toward the
image edges -- a real lens focuses different wavelengths at slightly
different magnifications. A faithful correction needs a per-lens
calibration profile (Lightroom's "Enable Lens Corrections" --
out of scope here, see
docs/planning/implementation-notes/2026-10-12-remove-chromatic-aberration.md
section 1 for why). Without one, this processor approximates the
correction with a small, fixed, uniform radial re-scale of the red and
blue channels around the image center, leaving green untouched as the
reference channel -- the same simplification most consumer tools fall
back to when no lens profile is available.
"""

from __future__ import annotations

import cv2
import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage


class RemoveChromaticAberrationProcessor(BaseProcessor):
    """Approximate lateral CA correction via a uniform radial channel remap.

    Builds a per-output-pixel source coordinate grid
    (``map_x[y, x] = x``, ``map_y[y, x] = y``, i.e. identity) and scales it
    around the image center by a small factor ``k`` before sampling with
    ``cv2.remap``. A positive ``k`` samples each output pixel from further
    out, which pulls that channel's content *inward* (toward the center --
    i.e. shrinks it); a negative ``k`` pulls content *outward* (expands
    it). This was verified empirically (not just derived) before being
    relied on -- see the implementation note section 5 for the test.

    The arbitrary-but-conventional choice made here is: shrink red
    (``k = +_MAX_K``), expand blue (``k = -_MAX_K``). Direction has no
    "correct" answer without a real lens to measure, since this is a
    fixed uniform approximation rather than a measured correction --
    only *some* consistent direction is needed for a believable effect.
    Green is always left completely unmodified, matching how real CA
    correction treats green as the untouched reference channel.
    """

    # Maximum per-channel radial scale at value=100, as a fraction of the
    # distance from the image center (0.15%). Small enough to read as a
    # subtle, plausible correction rather than a visible warp.
    _MAX_K = 0.0015

    def process(
        self, image: LinearImage, remove_ca: float = 0.0
    ) -> LinearImage:
        """Apply Remove CA in the range ``0`` (none) to ``100`` (strongest)."""
        source = np.asarray(image, dtype=np.float32)
        value = float(np.clip(remove_ca, 0.0, 100.0))
        if value == 0.0:
            return source.copy()

        height, width = source.shape[0], source.shape[1]
        k = self._MAX_K * (value / 100.0)

        map_x, map_y = np.meshgrid(
            np.arange(width, dtype=np.float32),
            np.arange(height, dtype=np.float32),
        )
        cx = (width - 1) / 2.0
        cy = (height - 1) / 2.0

        def _remap_channel(channel: np.ndarray, scale: float) -> np.ndarray:
            scaled_x = (cx + (map_x - cx) * (1.0 + scale)).astype(np.float32)
            scaled_y = (cy + (map_y - cy) * (1.0 + scale)).astype(np.float32)
            return cv2.remap(
                channel,
                scaled_x,
                scaled_y,
                interpolation=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT_101,
            )

        # Shrink red (pull inward, k > 0), expand blue (push outward,
        # k < 0) -- an arbitrary-but-conventional direction choice, not a
        # real measurement. See the class docstring and the implementation
        # note for the empirical verification of the sign convention.
        new_r = _remap_channel(source[..., 0], k)
        new_b = _remap_channel(source[..., 2], -k)
        new_g = source[..., 1]

        result = np.stack([new_r, new_g, new_b], axis=-1)
        return result.astype(np.float32, copy=False)
