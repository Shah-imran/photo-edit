"""Crop (normalized-rectangle slicing) for linear-light images.

Phase I ("Geometry and Crop", PDF sections 19-20) continues here with the
data/processing-layer half of the roadmap's Crop tool bullet -- see
docs/planning/implementation-notes/2026-10-13-crop-processor.md for the
full design rationale. The interactive drag-handle overlay UI, aspect
ratio presets, and the disabled "Crop" placeholder button in
``EditingToolStrip`` (``src/views/widgets/workspace_header.py``) are all
a SEPARATE, later slice -- this one only adds the processor, the
adjustment-state/pipeline wiring, undo/redo integration, and export
correctness, plus a programmatic (non-mouse-driven) way to set the crop
rectangle (``ImageController.on_crop_changed``) that the later UI slice
will call into.

``CropProcessor`` is the one processor in this codebase that
deliberately changes output shape -- every other processor (Texture,
Clarity, ..., Straighten, all ~20 of them) preserves the exact input
``(H, W, C)`` shape. This invariant is relied on throughout the
codebase: preview caching, undo/redo buffers, zoom/display math, and
export. To keep that invariant intact for every *other* step, Crop is
applied as the absolute LAST step in the entire processing pipeline --
after Straighten, after Grain, after literally everything else -- so
only the very last step of the chain ever changes shape. See the
implementation note's section 1 for the full architectural reasoning,
including confirmation that every downstream consumer of a processed
image (display, histogram, cache, export) already tolerates a variable
image size.
"""

from __future__ import annotations

import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage


class CropProcessor(BaseProcessor):
    """Slice a ``LinearImage`` to a normalized crop rectangle.

    ``x0``/``y0``/``x1``/``y1`` are normalized fractions of whatever
    image is handed to the processor at the time (full-res for final
    render/export, a smaller proxy for preview) -- the same crop state
    scales naturally to any resolution the pipeline happens to be
    working with at a given moment, exactly like
    :class:`~src.processors.vignette_processor.VignetteProcessor` computes
    its center from whatever image it is given rather than a fixed
    resolution. The default ``(0, 0, 1, 1)`` rectangle is the full frame
    and returns an identity copy.
    """

    def process(
        self,
        image: LinearImage,
        x0: float = 0.0,
        y0: float = 0.0,
        x1: float = 1.0,
        y1: float = 1.0,
    ) -> LinearImage:
        """Crop to the normalized rectangle ``(x0, y0)``-``(x1, y1)``."""
        source = np.asarray(image, dtype=np.float32)
        x0, y0, x1, y1 = (float(v) for v in (x0, y0, x1, y1))

        # Clamp/validate defensively -- this rectangle may come from
        # arbitrary persisted state (an old catalog entry, a malformed
        # imported preset) or interactive UI input in the later slice,
        # never trust it blindly.
        x0 = max(0.0, min(1.0, x0))
        x1 = max(0.0, min(1.0, x1))
        y0 = max(0.0, min(1.0, y0))
        y1 = max(0.0, min(1.0, y1))
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0

        if x0 <= 0.0 and y0 <= 0.0 and x1 >= 1.0 and y1 >= 1.0:
            return source.copy()  # identity: no crop

        height, width = source.shape[0], source.shape[1]
        left = int(round(x0 * width))
        right = int(round(x1 * width))
        top = int(round(y0 * height))
        bottom = int(round(y1 * height))
        # Guarantee a non-empty, in-bounds result even from a
        # degenerate/near-zero-area rectangle or a 1x1 source image.
        left = max(0, min(left, width - 1))
        right = max(left + 1, min(right, width))
        top = max(0, min(top, height - 1))
        bottom = max(top + 1, min(bottom, height))

        result = source[top:bottom, left:right]
        return result.astype(np.float32, copy=True)  # copy=True: a view into `source` must not alias it
