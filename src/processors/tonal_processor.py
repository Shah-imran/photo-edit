"""Highlights/Shadows/Whites/Blacks tonal recovery processor.

This is the first slice of the "Basic" panel gap called out in the
Lightroom-parity gap analysis (today's Basic panel only has
Exposure/Contrast/a non-Lightroom "Brightness"): Highlights and Shadows
are luminance-masked adjustments that only affect the bright or dark end
of the tonal range, and Whites/Blacks remap the input black/white points
before the rest of the tone curve runs.

Like ``ExposureProcessor``/``ColorProcessor``, this operates directly on
the canonical pipeline format (:data:`src.utils.color_pipeline.LinearImage`:
float32, ``(H, W, 3)``, linear-light, ``[0, 1]``) - luminance-masked
recovery only behaves physically plausibly in linear light, since
gamma-encoded values already have a nonlinear relationship with perceived
brightness baked in. Conversions to/from PIL or ``QImage`` happen at the
pipeline boundaries (``ImageService``, ``ImageView``), not here.
"""

import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage


class TonalProcessor(BaseProcessor):
    """Processor for Highlights/Shadows/Whites/Blacks tonal adjustments.

    All four parameters use Lightroom's -100..+100 range and operate on a
    ``LinearImage`` (values nominally in [0.0, 1.0]). The result is not
    clipped here; that happens once, at final re-encoding, so multiple
    processors can stack without each one separately clamping intermediate
    headroom.
    """

    # Rec. 709 luma weights, used to build the luminance mask that confines
    # Highlights/Shadows to the bright/dark end of the tonal range.
    _LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

    # How strongly Highlights/Shadows push toward black/white at the
    # extreme end of their mask; keeps a +100 adjustment strong but not a
    # full snap to 0/1 (which would look like a hard clip, not a recovery).
    _RECOVERY_STRENGTH = 0.6

    def process(
        self,
        linear_rgb: LinearImage,
        highlights: float = 0.0,
        shadows: float = 0.0,
        whites: float = 0.0,
        blacks: float = 0.0,
    ) -> LinearImage:
        """Apply tonal adjustments to a ``LinearImage``.

        Args:
            linear_rgb: ``LinearImage`` (float32, ``(H, W, 3)``, linear
                light, ``[0, 1]``).
            highlights: -100..100. Positive recovers/brightens highlights,
                negative darkens them (pulls back blown-out areas).
            shadows: -100..100. Positive lifts shadow detail, negative
                deepens shadows.
            whites: -100..100. Moves the white input point.
            blacks: -100..100. Moves the black input point.

        Returns:
            A new float32 array of the same shape. Values are not clamped.
        """
        result = np.array(linear_rgb, dtype=np.float32, copy=True)

        if whites != 0.0 or blacks != 0.0:
            result = self._adjust_black_white_points(result, whites, blacks)

        if highlights != 0.0:
            result = self._adjust_highlights(result, highlights)

        if shadows != 0.0:
            result = self._adjust_shadows(result, shadows)

        return result

    def _luminance(self, rgb: np.ndarray) -> np.ndarray:
        """Per-pixel Rec. 709 luminance from the first 3 channels."""
        return rgb[..., :3] @ self._LUMA_WEIGHTS

    @staticmethod
    def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
        """Hermite smoothstep, clamped to [0, 1] outside [edge0, edge1]."""
        denom = edge1 - edge0
        t = np.clip((x - edge0) / denom, 0.0, 1.0)
        return t * t * (3.0 - 2.0 * t)

    def _adjust_highlights(self, rgb: np.ndarray, amount: float) -> np.ndarray:
        """Recover/brighten only pixels above mid-gray luminance."""
        luminance = self._luminance(rgb)
        weight = self._smoothstep(0.5, 1.0, luminance)[..., np.newaxis]
        factor = amount / 100.0
        adjusted_rgb = rgb.copy()
        adjusted_rgb[..., :3] = rgb[..., :3] + (
            factor * weight * (1.0 - rgb[..., :3]) * self._RECOVERY_STRENGTH
        )
        return adjusted_rgb

    def _adjust_shadows(self, rgb: np.ndarray, amount: float) -> np.ndarray:
        """Lift/deepen only pixels below mid-gray luminance."""
        luminance = self._luminance(rgb)
        weight = self._smoothstep(0.5, 0.0, luminance)[..., np.newaxis]
        factor = amount / 100.0
        adjusted_rgb = rgb.copy()
        adjusted_rgb[..., :3] = rgb[..., :3] + (
            factor * weight * rgb[..., :3] * self._RECOVERY_STRENGTH
        )
        return adjusted_rgb

    def _adjust_black_white_points(
        self, rgb: np.ndarray, whites: float, blacks: float
    ) -> np.ndarray:
        """Remap the input black/white points before the rest of the tone
        curve runs, the way Lightroom's Whites/Blacks sliders behave.

        Positive Blacks lifts/opens up shadow detail (moves the black point
        down, away from the data), while negative Blacks crushes shadows
        toward pure black (moves the black point up, into the data) -
        hence the sign flip relative to Whites, which brightens/clips
        highlights as it increases.
        """
        white_point = 1.0 - whites / 200.0
        black_point = -blacks / 200.0
        # A pathological combination (e.g. whites=-100, blacks=100) could
        # invert or zero the span; floor it so the divide stays finite
        # rather than raising or emitting NaN/inf for a rare slider extreme.
        span = max(white_point - black_point, 1e-6)

        adjusted_rgb = rgb.copy()
        adjusted_rgb[..., :3] = (rgb[..., :3] - black_point) / span
        return adjusted_rgb
