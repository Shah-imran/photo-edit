"""Exposure processor for linear-light exposure, contrast, and brightness."""

from __future__ import annotations

import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage


_LUT_SIZE = 65536
_SRGB_TO_LINEAR_MIN = -0.5
_SRGB_TO_LINEAR_MAX = 1.5
_LINEAR_TO_SRGB_LUT = None
_SRGB_TO_LINEAR_LUT = None


def _linear_to_srgb_lut() -> np.ndarray:
    """Return a cached linear-to-sRGB LUT for contrast processing."""
    global _LINEAR_TO_SRGB_LUT
    if _LINEAR_TO_SRGB_LUT is None:
        linear = np.linspace(0.0, 1.0, _LUT_SIZE, dtype=np.float32)
        low = linear * np.float32(12.92)
        high = np.float32(1.055) * np.power(
            linear, np.float32(1.0 / 2.4)
        ) - np.float32(0.055)
        _LINEAR_TO_SRGB_LUT = np.where(
            linear <= np.float32(0.0031308), low, high
        ).astype(np.float32)
    return _LINEAR_TO_SRGB_LUT


def _srgb_to_linear_lut() -> np.ndarray:
    """Return a cached sRGB-to-linear LUT over the contrast output range."""
    global _SRGB_TO_LINEAR_LUT
    if _SRGB_TO_LINEAR_LUT is None:
        srgb = np.linspace(
            _SRGB_TO_LINEAR_MIN,
            _SRGB_TO_LINEAR_MAX,
            _LUT_SIZE,
            dtype=np.float32,
        )
        sign = np.sign(srgb)
        abs_srgb = np.abs(srgb)
        low = abs_srgb / np.float32(12.92)
        high = np.power(
            (abs_srgb + np.float32(0.055)) / np.float32(1.055),
            np.float32(2.4),
        )
        _SRGB_TO_LINEAR_LUT = (
            sign
            * np.where(abs_srgb <= np.float32(0.04045), low, high)
        ).astype(np.float32)
    return _SRGB_TO_LINEAR_LUT


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
        factor = np.float32(np.clip(1.0 + (value / 100.0), 0.0, 2.0))
        srgb = self._linear_to_srgb_fast(image)
        adjusted = (srgb - 0.5) * factor + 0.5
        # We deliberately do not clip here; ``srgb_to_linear`` accepts
        # extrapolated values and the boundary clips on output.
        return self._srgb_to_linear_fast(adjusted)

    @staticmethod
    def _linear_to_srgb_fast(image: LinearImage) -> np.ndarray:
        """Fast LUT approximation of the sRGB OETF for contrast."""
        clipped = np.clip(np.asarray(image, dtype=np.float32), 0.0, 1.0)
        indices = (clipped * np.float32(_LUT_SIZE - 1)).astype(np.uint16)
        return _linear_to_srgb_lut()[indices]

    @staticmethod
    def _srgb_to_linear_fast(srgb: np.ndarray) -> np.ndarray:
        """Fast LUT approximation of the sRGB EOTF for contrast outputs."""
        clipped = np.clip(
            np.asarray(srgb, dtype=np.float32),
            _SRGB_TO_LINEAR_MIN,
            _SRGB_TO_LINEAR_MAX,
        )
        scale = np.float32((_LUT_SIZE - 1) / (_SRGB_TO_LINEAR_MAX - _SRGB_TO_LINEAR_MIN))
        indices = ((clipped - np.float32(_SRGB_TO_LINEAR_MIN)) * scale).astype(
            np.uint16
        )
        return _srgb_to_linear_lut()[indices]
