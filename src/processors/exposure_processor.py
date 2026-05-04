"""Exposure processor for linear-light exposure, contrast, and brightness."""

from __future__ import annotations

import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage, linear_to_srgb, srgb_to_linear


class ExposureProcessor(BaseProcessor):
    """Processor for exposure-related adjustments.

    Operates on the canonical pipeline format: float32, ``(H, W, 3)``,
    linear-light, ``[0, 1]`` (out-of-gamut highlights are allowed to
    flow through and are clipped only at the PIL/QImage boundary).
    """

    def process(
        self,
        image: LinearImage,
        exposure: float = 0.0,
        contrast: float = 0.0,
        brightness: float = 0.0,
    ) -> LinearImage:
        """Apply exposure-family adjustments.

        Args:
            image: Input ``LinearImage``.
            exposure: Exposure adjustment in stops (-5.0 .. +5.0).
            contrast: Contrast adjustment (-100 .. +100).
            brightness: Brightness adjustment (-100 .. +100).

        Returns:
            New ``LinearImage`` with adjustments applied.
        """
        result = np.asarray(image, dtype=np.float32).copy()

        if exposure != 0.0:
            result = self._adjust_exposure(result, exposure)
        if brightness != 0.0:
            result = self._adjust_brightness(result, brightness)
        if contrast != 0.0:
            result = self._adjust_contrast(result, contrast)
        return result

    def _adjust_exposure(self, image: LinearImage, stops: float) -> LinearImage:
        """Multiply linear values by ``2 ** stops`` (true camera-stop math).

        This is now physically correct because the pipeline is linear.
        Values may exceed 1.0; they are not clipped here.
        """
        return image * np.float32(2.0 ** stops)

    def _adjust_brightness(self, image: LinearImage, value: float) -> LinearImage:
        """Multiplicative brightness in linear space.

        Slider range -100..+100 maps to a 0..2 multiplier so the visual
        feel matches the previous PIL ``ImageEnhance.Brightness`` for
        small values.
        """
        factor = float(np.clip(1.0 + (value / 100.0), 0.0, 2.0))
        return image * np.float32(factor)

    def _adjust_contrast(self, image: LinearImage, value: float) -> LinearImage:
        """Contrast that preserves the slider's perceptual feel.

        The contrast curve is applied around perceptual mid-grey in
        sRGB-encoded space so that sliding the control feels the same
        as it did before this slice. Implementation: encode -> apply
        ``(x - 0.5) * factor + 0.5`` -> decode.

        A future Phase E slice can replace this with a proper
        tone-mapped contrast curve in linear space; that is intentionally
        out of scope here.
        """
        factor = float(np.clip(1.0 + (value / 100.0), 0.0, 2.0))
        srgb = linear_to_srgb(image)
        adjusted = (srgb - 0.5) * factor + 0.5
        # We deliberately do not clip here; ``srgb_to_linear`` accepts
        # extrapolated values and the boundary clips on output.
        return srgb_to_linear(adjusted)
