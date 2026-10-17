"""Synthetic photographic film grain for linear-light images.

Texture, Clarity, Dehaze, and Vignette (see
docs/planning/implementation-notes/2026-09-30-texture.md,
docs/planning/implementation-notes/2026-10-12-clarity.md,
docs/planning/implementation-notes/2026-10-12-dehaze.md, and
docs/planning/implementation-notes/2026-10-12-vignette.md) are all
deterministic -- each is a pure function of its input pixels and
parameters. Grain is different: it adds *noise*, which is inherently
stochastic. To keep this processor a pure function of ``(image, grain)``
anyway -- required by :class:`~src.processing.processing_worker
.ProcessingWorker`'s preview cache (which keys on an adjustment signature
and would otherwise miss on every call) and by this codebase's idempotency
tests (``process(x, p)`` called twice must return identical arrays) -- the
noise generator is seeded deterministically from the image's shape and the
grain amount. See :meth:`GrainProcessor._seed_for` for the exact formula
and docs/planning/implementation-notes/2026-10-12-grain.md section 5 for
why this matters.
"""

from __future__ import annotations

import numpy as np
import cv2

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage


class GrainProcessor(BaseProcessor):
    """Add synthetic, spatially-correlated film grain.

    Unlike the other four Effects controls, Grain is one-directional
    (``0``..``100``, matching Lightroom's "Amount" -- there is no "remove
    grain" direction here). The amount scales the standard deviation of
    additive Gaussian noise. To approximate real film grain's spatial
    correlation (rather than harsh per-pixel static), the noise is
    generated at roughly a third of the image's linear dimensions and
    upsampled back to full size with bilinear interpolation, which blurs
    it into soft correlated blobs. The same 2-D noise field is broadcast
    across all channels, so grain reads as luminance texture rather than
    colored confetti.
    """

    _MAX_STD = 0.04
    _DOWNSAMPLE_FACTOR = 3

    def process(self, image: LinearImage, grain: float = 0.0) -> LinearImage:
        """Apply Grain in the range ``0`` (none) to ``100`` (heaviest)."""
        source = np.asarray(image, dtype=np.float32)
        value = float(np.clip(grain, 0.0, 100.0))
        if value == 0.0:
            return source.copy()

        height, width = source.shape[0], source.shape[1]
        std = (value / 100.0) * self._MAX_STD

        # Clamp the downsample target to at least 1x1 so tiny images (even
        # 1x1) cannot produce a zero-size intermediate array.
        small_h = max(1, round(height / self._DOWNSAMPLE_FACTOR))
        small_w = max(1, round(width / self._DOWNSAMPLE_FACTOR))

        seed = self._seed_for(source.shape, value)
        rng = np.random.default_rng(seed)
        noise_small = rng.normal(0.0, std, size=(small_h, small_w)).astype(
            np.float32
        )

        if (small_h, small_w) == (height, width):
            noise = noise_small
        else:
            noise = cv2.resize(
                noise_small, (width, height), interpolation=cv2.INTER_LINEAR
            )
        noise = noise.astype(np.float32, copy=False)

        if source.ndim > 2:
            noise = noise[..., np.newaxis]

        result = source + noise
        return result.astype(np.float32, copy=False)

    @staticmethod
    def _seed_for(shape, value: float) -> int:
        """Derive a deterministic RNG seed from image shape and grain amount.

        ``process(same_image, grain=X)`` must return byte-identical output
        on every call (for the preview cache and idempotency tests), while
        a different image shape or a different grain amount must produce
        different noise. Hashing the (shape, rounded-value) tuple and
        masking to 32 bits satisfies both: Python's ``hash()`` of a tuple
        of ints and a float is deterministic within a process (unlike
        ``str``/``bytes`` hashing, floats and ints are never subject to
        ``PYTHONHASHSEED`` randomization), so the same inputs always
        hash the same way, while different shapes or amounts overwhelmingly
        hash differently. The value is rounded to 4 decimal places first so
        float jitter from upstream float32/float64 conversions cannot
        change the seed.
        """
        key = (tuple(int(dim) for dim in shape), round(value, 4))
        return hash(key) & 0xFFFFFFFF
