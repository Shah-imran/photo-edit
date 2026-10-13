"""Local-adjustment mask (linear/radial gradient) for linear-light images.

Phase J ("Masking", roadmap bullet: "start with brush / linear gradient /
radial + adjustment stack; AI/sky/subject later") begins here with the
data/processing-layer half of a single-mask-slot local adjustment
system -- see docs/planning/implementation-notes/
2026-10-13-mask-processor.md for the full design rationale. The
interactive drag UI (a draggable gradient line for linear, a draggable
ellipse for radial) is a SEPARATE, later slice -- this one only adds the
geometry math, the processor that blends a small local adjustment
sub-stack through it, and the adjustment-state/pipeline wiring, plus a
programmatic (non-mouse-driven) way to set the mask
(``ImageController.on_mask_changed``) that the later UI slice will call
into.

Unlike :class:`~src.processors.crop_processor.CropProcessor` (the one
processor that deliberately changes output shape), ``MaskProcessor``
preserves the exact input ``(H, W, C)`` shape -- masking blends pixel
VALUES through a per-pixel alpha field, it never removes or adds pixels.
This is why it can safely sit anywhere in the pipeline before Crop
without breaking any other step's shape-preservation invariant; the
pipeline wiring applies it immediately after every other adjustment
(including Straighten) and strictly BEFORE Crop (see section on pipeline
ordering in the implementation note: the mask's geometry is expressed in
the full, pre-crop frame's own normalized coordinates, so it never needs
to account for a separate, edit-time-dependent crop rectangle).

Two mask types only (brush/AI/sky/subject are explicitly deferred, per
the roadmap's own phasing): ``"linear"`` (a gradient ramping from 0 to 1
along a line segment -- the line's own length sets the transition
width, matching Lightroom's linear gradient behavior) and ``"radial"``
(an aspect-ratio-correct ellipse, 1 at the center, falling to 0 at the
ellipse boundary over a feathered outer band, reusing the exact
``t * t * (3 - 2 * t)`` cubic smoothstep
:class:`~src.processors.vignette_processor.VignetteProcessor` already
uses). The local adjustment sub-stack is a small, fixed 4-parameter
subset -- Exposure, Contrast, Saturation, Clarity -- reusing the
EXISTING :class:`~src.processors.exposure_processor.ExposureProcessor`
(for exposure/contrast), :class:`~src.processors.color_processor.ColorProcessor`
(for saturation; vibrance is left at its neutral 0.0), and
:class:`~src.processors.clarity_processor.ClarityProcessor` instances --
no new processor math is written here, only a blend step composing
already-built processors. Every other global adjustment parameter
(temperature/tint, texture, dehaze, vignette, grain, sharpening, both
noise-reduction sliders, remove CA, defringe, within a mask) is an
explicit, documented future-slice gap -- see the implementation note.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

from src.processors.base_processor import BaseProcessor
from src.processors.clarity_processor import ClarityProcessor
from src.processors.color_processor import ColorProcessor
from src.processors.exposure_processor import ExposureProcessor
from src.utils.color_pipeline import LinearImage

_MASK_TYPES = ("linear", "radial")


class MaskProcessor(BaseProcessor):
    """Blend a local Exposure/Contrast/Saturation/Clarity sub-stack through
    a single linear- or radial-gradient alpha mask.

    ``mask is None`` (or an unrecognized/missing ``"type"``) is the
    documented "no mask" sentinel and returns an identity copy
    immediately, matching every other processor's zero-cost-skip
    convention (see :class:`~src.processors.crop_processor.CropProcessor`
    and :class:`~src.processors.vignette_processor.VignetteProcessor`).
    """

    def __init__(
        self,
        exposure_processor: Optional[ExposureProcessor] = None,
        color_processor: Optional[ColorProcessor] = None,
        clarity_processor: Optional[ClarityProcessor] = None,
    ) -> None:
        # Reuse already-built processor instances (constructor-injectable
        # for tests, defaulting to fresh instances) rather than writing new
        # processor math -- see module docstring.
        self._exposure_processor = exposure_processor or ExposureProcessor()
        self._color_processor = color_processor or ColorProcessor()
        self._clarity_processor = clarity_processor or ClarityProcessor()

    def process(
        self, image: LinearImage, mask: Optional[Dict[str, Any]] = None
    ) -> LinearImage:
        """Apply the mask's local adjustment sub-stack within its geometry.

        Args:
            image: Input ``LinearImage``.
            mask: ``None`` (or a dict whose ``"type"`` is not ``"linear"``/
                ``"radial"``) for "no mask" -- returns an identity copy.
                Otherwise a dict shaped per the module's state-shape
                contract (see the implementation note): ``"type"``,
                ``"invert"``, the type-specific geometry keys, and the
                4 local adjustment keys (``"exposure"``, ``"contrast"``,
                ``"saturation"``, ``"clarity"``).

        Returns:
            New ``LinearImage``, same shape/dtype as the input.
        """
        source = np.asarray(image, dtype=np.float32)
        if not mask or mask.get("type") not in _MASK_TYPES:
            return source.copy()

        height, width = source.shape[0], source.shape[1]
        alpha = self._compute_alpha(height, width, mask)
        if bool(mask.get("invert", False)):
            alpha = 1.0 - alpha

        local = source.copy()
        local = self._exposure_processor.process(
            local,
            exposure=float(mask.get("exposure", 0.0)),
            contrast=float(mask.get("contrast", 0.0)),
        )
        local = self._color_processor.process(
            local,
            saturation=float(mask.get("saturation", 0.0)),
            vibrance=0.0,
        )
        local = self._clarity_processor.process(
            local, clarity=float(mask.get("clarity", 0.0))
        )

        alpha3 = alpha[..., np.newaxis]
        result = source * (1.0 - alpha3) + local * alpha3
        return result.astype(np.float32, copy=False)

    @staticmethod
    def _compute_alpha(
        height: int, width: int, mask: Dict[str, Any]
    ) -> np.ndarray:
        """Return an ``(H, W)`` float32 alpha field in ``[0, 1]``."""
        if mask.get("type") == "linear":
            return MaskProcessor._linear_alpha(height, width, mask)
        return MaskProcessor._radial_alpha(height, width, mask)

    @staticmethod
    def _linear_alpha(
        height: int, width: int, mask: Dict[str, Any]
    ) -> np.ndarray:
        """Project every pixel onto the ``(x0,y0)``-``(x1,y1)`` line.

        The projection is done in actual PIXEL coordinates (normalized
        fractions multiplied by the image's real width/height), not in
        raw normalized-fraction space -- a naive projection in raw
        fraction space would make the gradient's visual angle depend on
        the image's aspect ratio (e.g. a diagonal corner-to-corner
        gradient on a 2:1-wide image would not look like a line drawn at
        a consistent angle, and the perpendicular isolines -- the actual
        bands of the gradient -- would be skewed relative to what the
        line looks like on screen). Projecting in pixel space keeps the
        gradient's isolines genuinely perpendicular to the line as drawn,
        regardless of image shape.
        """
        w = max(float(width), 1.0)
        h = max(float(height), 1.0)
        x0 = float(mask.get("x0", 0.0)) * w
        y0 = float(mask.get("y0", 0.0)) * h
        x1 = float(mask.get("x1", 1.0)) * w
        y1 = float(mask.get("y1", 1.0)) * h

        cols = (np.arange(width, dtype=np.float64) + 0.5)[np.newaxis, :]
        rows = (np.arange(height, dtype=np.float64) + 0.5)[:, np.newaxis]

        dx = x1 - x0
        dy = y1 - y0
        length_sq = dx * dx + dy * dy
        if length_sq < 1e-9:
            # Degenerate (zero-length) gradient: there is no direction to
            # ramp across. Treat the mask as fully "on" everywhere rather
            # than dividing by (near) zero.
            return np.ones((height, width), dtype=np.float32)

        t = ((cols - x0) * dx + (rows - y0) * dy) / length_sq
        return np.clip(t, 0.0, 1.0).astype(np.float32)

    @staticmethod
    def _radial_alpha(
        height: int, width: int, mask: Dict[str, Any]
    ) -> np.ndarray:
        """Aspect-ratio-correct elliptical falloff from ``(cx, cy)``.

        ``rx``/``ry`` are each independently scaled by the image's own
        width/height (exactly how
        :class:`~src.processors.vignette_processor.VignetteProcessor`
        normalizes its own ``dy``/``dx`` by ``half_h``/``half_w``
        separately rather than by one shared scale) so the SAME
        ``(cx, cy, rx, ry)`` geometry produces a shape that scales
        proportionally to each axis's own dimension on any image, square
        or not -- a circle stays a circle only when the caller picks
        ``rx``/``ry`` so that ``rx * width == ry * height``, but a given
        ellipse's shape relative to the frame is always preserved,
        regardless of the image's actual aspect ratio.
        """
        cx = float(mask.get("cx", 0.5))
        cy = float(mask.get("cy", 0.5))
        rx = max(float(mask.get("rx", 0.25)), 1e-4)
        ry = max(float(mask.get("ry", 0.25)), 1e-4)
        feather = float(np.clip(mask.get("feather", 0.5), 0.0, 1.0))

        cols = (np.arange(width, dtype=np.float64) + 0.5) / max(float(width), 1.0)
        rows = (np.arange(height, dtype=np.float64) + 0.5) / max(float(height), 1.0)
        px = cols[np.newaxis, :]
        py = rows[:, np.newaxis]

        dx = (px - cx) / rx
        dy = (py - cy) / ry
        dist = np.sqrt(dx * dx + dy * dy)

        # Cubic smoothstep over the outer `feather` fraction of the
        # radius -- the exact same t * t * (3 - 2*t) curve
        # VignetteProcessor already uses, for consistency with this
        # codebase's established convention. A near-zero feather keeps
        # the denominator from hitting exactly zero (a hard step, in the
        # limit) while a feather near 1.0 softens the whole radius.
        inner = max(1.0 - feather, 0.0)
        span = max(feather, 1e-6)
        t = np.clip((dist - inner) / span, 0.0, 1.0)
        edge = t * t * (3.0 - 2.0 * t)
        alpha = 1.0 - edge
        return np.clip(alpha, 0.0, 1.0).astype(np.float32)
