"""Display-ready preview frames for the Qt presentation path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from PyQt6.QtGui import QImage

from src.utils.color_pipeline import LinearImage


_DISPLAY_LUT_SIZE = 65536
_DISPLAY_LUT: Optional[np.ndarray] = None


def _display_lut() -> np.ndarray:
    """Return a cached linear-light to sRGB uint8 lookup table."""
    global _DISPLAY_LUT
    if _DISPLAY_LUT is None:
        linear = np.linspace(0.0, 1.0, _DISPLAY_LUT_SIZE, dtype=np.float32)
        low = linear * np.float32(12.92)
        high = np.float32(1.055) * np.power(
            linear, np.float32(1.0 / 2.4)
        ) - np.float32(0.055)
        srgb = np.where(linear <= np.float32(0.0031308), low, high)
        _DISPLAY_LUT = np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)
    return _DISPLAY_LUT


def linear_to_display_rgb(arr: LinearImage) -> np.ndarray:
    """Convert a linear float image to display-ready RGB888 using a LUT.

    This is intended for interactive/preview presentation. It trades tiny
    quantization error for avoiding per-pixel power functions on the UI thread.
    """
    if not isinstance(arr, np.ndarray):
        raise TypeError(
            f"linear_to_display_rgb expected np.ndarray, got {type(arr).__name__}"
        )
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(
            f"linear_to_display_rgb expected shape (H, W, 3); got {arr.shape}"
        )

    clipped = np.clip(np.asarray(arr, dtype=np.float32), 0.0, 1.0)
    indices = (clipped * np.float32(_DISPLAY_LUT_SIZE - 1)).astype(np.uint16)
    return np.ascontiguousarray(_display_lut()[indices])


@dataclass
class DisplayFrame:
    """A preview frame whose display conversion already happened off the UI thread."""

    request_id: int
    tier: str
    adjustment_signature: Tuple
    rgb: np.ndarray
    linear_image: Optional[LinearImage] = None

    @classmethod
    def from_linear(
        cls,
        request_id: int,
        tier: str,
        adjustment_signature: Tuple,
        image: LinearImage,
    ) -> "DisplayFrame":
        """Build a display frame from a processed linear preview image."""
        return cls(
            request_id=request_id,
            tier=tier,
            adjustment_signature=adjustment_signature,
            rgb=linear_to_display_rgb(image),
            linear_image=image,
        )

    @property
    def shape(self) -> Tuple[int, int, int]:
        """Return the RGB buffer shape for logging/test compatibility."""
        return self.rgb.shape

    @property
    def size(self) -> Tuple[int, int]:
        """Return ``(width, height)``."""
        return self.rgb.shape[1], self.rgb.shape[0]

    def to_qimage(self) -> QImage:
        """Create a QImage view over the owned RGB buffer."""
        rgb = np.ascontiguousarray(self.rgb)
        if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError(f"DisplayFrame expected RGB888 buffer, got {rgb.shape}")
        self.rgb = rgb
        height, width, _ = rgb.shape
        return QImage(
            rgb.data,
            width,
            height,
            rgb.strides[0],
            QImage.Format.Format_RGB888,
        )
