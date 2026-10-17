"""Straighten (small-angle rigid rotation) for linear-light images.

Phase I ("Geometry and Crop", PDF sections 19-20) starts with this slice.
See docs/planning/implementation-notes/2026-10-12-straighten.md for the
full design rationale, including why this is deliberately *only* a
dimension-preserving rotation and not any part of a full interactive
Crop tool or Upright/distortion correction (both explicitly out of
scope for this slice -- see that note's section 1).

Straighten rotates the whole image by a small angle around its own
center, to correct a tilted horizon/vertical, while keeping the output
array's ``(H, W, C)`` shape byte-for-byte identical to the input's --
this is the one hard invariant every processor in this codebase relies
on (preview caching, undo/redo buffers, zoom/display math, export).
The corners newly exposed by the rotation (which would otherwise be
empty/black) are filled by reflecting the existing image content back
into them (``cv2.BORDER_REFLECT_101``), the same border convention this
codebase's other geometric/blur-based processors
(``RemoveChromaticAberrationProcessor``, Texture/Clarity/Dehaze's
Gaussian blurs) already use.
"""

from __future__ import annotations

import cv2
import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage


class StraightenProcessor(BaseProcessor):
    """Rotate the image by a small angle, preserving its exact shape.

    Range is ``-45`` (degrees, rotates clockwise) to ``+45`` (degrees,
    rotates counter-clockwise) -- see the implementation note section 5
    for the empirically-verified sign convention. Zero returns an
    identity copy immediately, without building a rotation matrix or
    calling ``cv2.warpAffine`` at all, both for performance and so the
    zero case is an exact identity test.
    """

    _MIN_DEGREES = -45.0
    _MAX_DEGREES = 45.0

    def process(self, image: LinearImage, straighten: float = 0.0) -> LinearImage:
        """Apply Straighten in the range ``-45`` to ``+45`` degrees."""
        source = np.asarray(image, dtype=np.float32)
        value = float(np.clip(straighten, self._MIN_DEGREES, self._MAX_DEGREES))
        if value == 0.0:
            return source.copy()

        height, width = source.shape[0], source.shape[1]
        center = ((width - 1) / 2.0, (height - 1) / 2.0)
        rotation_matrix = cv2.getRotationMatrix2D(center, value, 1.0)
        result = cv2.warpAffine(
            source,
            rotation_matrix,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )
        return result.astype(np.float32, copy=False)
