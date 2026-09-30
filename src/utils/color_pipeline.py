"""Boundary conversions between PIL/QImage and the internal float pipeline.

The internal canonical pixel format is::

    LinearImage = np.ndarray, shape (H, W, 3), dtype float32,
                  values in [0, 1], linear-light, sRGB primaries.

All processors and the model speak this format. Loaders and the viewer
go through this module to convert from / to sRGB-encoded uint8 PIL or
``QImage``. No other module should import ``PIL.ImageEnhance`` or build
a ``QImage`` directly from raw pixels -- this is the only chokepoint.

The sRGB OETF/EOTF used here is the standard piecewise IEC 61966-2-1
curve (not the gamma-2.2 approximation). ``rawpy`` produces the same
curve when configured with ``output_color=ColorSpace.sRGB`` so that
JPEG and RAW callers do not need a special-case path downstream.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from PIL import Image
from PyQt6.QtGui import QImage


logger = logging.getLogger(__name__)


LinearImage = np.ndarray  # type alias used throughout the codebase


_SRGB_THRESHOLD_LIN = 0.0031308
_SRGB_THRESHOLD_SRGB = 0.04045
_SRGB_GAMMA = 2.4
_SRGB_LINEAR_SLOPE = 12.92
_SRGB_OFFSET = 0.055
_SRGB_SCALE = 1.055


def srgb_to_linear(arr: np.ndarray) -> np.ndarray:
    """Apply the sRGB EOTF (sRGB-encoded -> linear-light).

    Operates element-wise. The function is **sign-symmetric** so that
    out-of-range negative inputs (which can appear transiently during
    contrast operations) are handled by extrapolating around zero
    rather than producing ``NaN`` from a fractional power on a
    negative number.
    """
    arr = np.asarray(arr, dtype=np.float32)
    sign = np.sign(arr)
    abs_arr = np.abs(arr)
    low = abs_arr / _SRGB_LINEAR_SLOPE
    high = ((abs_arr + _SRGB_OFFSET) / _SRGB_SCALE) ** _SRGB_GAMMA
    magnitude = np.where(abs_arr <= _SRGB_THRESHOLD_SRGB, low, high)
    return (sign * magnitude).astype(np.float32)


def linear_to_srgb(arr: np.ndarray) -> np.ndarray:
    """Apply the sRGB OETF (linear-light -> sRGB-encoded).

    Inputs are clipped to ``[0, 1]`` first so out-of-gamut highlights
    become 1.0 and negative values become 0.0 (matches how every
    desktop image viewer behaves).
    """
    arr = np.asarray(arr, dtype=np.float32)
    arr = np.clip(arr, 0.0, 1.0)
    low = arr * _SRGB_LINEAR_SLOPE
    high = _SRGB_SCALE * np.power(arr, 1.0 / _SRGB_GAMMA) - _SRGB_OFFSET
    return np.where(arr <= _SRGB_THRESHOLD_LIN, low, high).astype(np.float32)


_UINT8_TO_LINEAR_LUT: Optional[np.ndarray] = None
_UINT16_TO_LINEAR_LUT: Optional[np.ndarray] = None


def _uint8_to_linear_lut() -> np.ndarray:
    """Cached exact sRGB-uint8 -> linear-light LUT (256 entries).

    An 8-bit source only ever takes one of 256 values per channel, so
    unlike a display-side LUT this is not an approximation -- it holds
    the exact ``srgb_to_linear`` result for every possible input byte,
    computed once and reused for every image load. Measured cost of the
    ``np.power()`` path this replaces: ~3.4s for a single 6-megapixel
    JPEG in this environment's profiling (see
    docs/planning/implementation-notes/2026-09-30-srgb-decode-lut.md).
    """
    global _UINT8_TO_LINEAR_LUT
    if _UINT8_TO_LINEAR_LUT is None:
        srgb = np.linspace(0.0, 1.0, 256, dtype=np.float32)
        _UINT8_TO_LINEAR_LUT = srgb_to_linear(srgb)
    return _UINT8_TO_LINEAR_LUT


def uint8_srgb_to_linear(arr_u8: np.ndarray) -> LinearImage:
    """Convert an sRGB-encoded uint8 array to linear-light via an exact LUT.

    Equivalent to ``srgb_to_linear(arr_u8.astype(np.float32) / 255.0)``
    but avoids a per-pixel ``power()`` call -- see
    :func:`_uint8_to_linear_lut`.
    """
    return _uint8_to_linear_lut()[arr_u8].astype(np.float32, copy=False)


def _uint16_to_linear_lut() -> np.ndarray:
    """Cached exact sRGB-uint16 -> linear-light LUT (65536 entries).

    Same reasoning as :func:`_uint8_to_linear_lut`, sized for RAW
    ``rawpy`` postprocess's 16-bit output (65536 possible values per
    channel) -- exact, not an approximation.
    """
    global _UINT16_TO_LINEAR_LUT
    if _UINT16_TO_LINEAR_LUT is None:
        srgb = np.linspace(0.0, 1.0, 65536, dtype=np.float32)
        _UINT16_TO_LINEAR_LUT = srgb_to_linear(srgb)
    return _UINT16_TO_LINEAR_LUT


def uint16_srgb_to_linear(arr_u16: np.ndarray) -> LinearImage:
    """Convert an sRGB-encoded uint16 array to linear-light via an exact LUT.

    Equivalent to ``srgb_to_linear(arr_u16.astype(np.float32) / 65535.0)``
    but avoids a per-pixel ``power()`` call -- see
    :func:`_uint16_to_linear_lut`.
    """
    return _uint16_to_linear_lut()[arr_u16].astype(np.float32, copy=False)


def pil_to_linear(pil: Image.Image) -> LinearImage:
    """Convert an sRGB-encoded uint8 PIL image to a LinearImage.

    Accepts ``RGB``, ``RGBA``, and ``L`` modes:

    * ``RGB`` -- used as-is.
    * ``RGBA`` -- alpha is **dropped** (we do not yet carry alpha
      through the pipeline; planned for a future slice).
    * ``L`` -- broadcast to three identical channels.

    Other modes are converted to ``RGB`` first (matches today's
    coercion in ``ImageService.load_image``).
    """
    if pil.mode == "RGBA":
        pil = pil.convert("RGB")
    elif pil.mode == "L":
        pil = pil.convert("RGB")
    elif pil.mode != "RGB":
        pil = pil.convert("RGB")

    arr_u8 = np.asarray(pil, dtype=np.uint8)
    return uint8_srgb_to_linear(arr_u8)


def linear_to_pil(arr: LinearImage) -> Image.Image:
    """Convert a LinearImage to an sRGB-encoded 8-bit RGB ``PIL.Image``."""
    _validate_linear_shape(arr, "linear_to_pil")
    arr_u8 = _linear_to_srgb_u8(arr)
    return Image.fromarray(arr_u8, mode="RGB")


def linear_to_qimage(arr: LinearImage) -> QImage:
    """Convert a LinearImage to a ``Format_RGB888`` ``QImage``.

    The returned image owns a contiguous copy of its pixel buffer so it
    is safe to pass across thread boundaries and to outlive ``arr``.
    """
    _validate_linear_shape(arr, "linear_to_qimage")
    arr_u8 = np.ascontiguousarray(_linear_to_srgb_u8(arr))
    height, width, _ = arr_u8.shape
    bytes_per_line = 3 * width
    qimage = QImage(
        arr_u8.tobytes(),
        width,
        height,
        bytes_per_line,
        QImage.Format.Format_RGB888,
    )
    # ``tobytes()`` already produced an owned copy, but defensively make
    # one more so the lifetime of ``arr_u8`` cannot affect the QImage.
    return qimage.copy()


def _linear_to_srgb_u8(arr: np.ndarray) -> np.ndarray:
    """Apply OETF, scale to [0, 255], round to nearest, cast to uint8.

    The explicit ``np.round`` avoids an off-by-one issue where
    ``float32`` arithmetic can produce e.g. 254.9999 for an input of
    1.0 due to ``** (1/2.4)`` not being exact.
    """
    srgb = linear_to_srgb(arr)
    scaled = np.round(srgb * 255.0)
    return np.clip(scaled, 0.0, 255.0).astype(np.uint8)


def _validate_linear_shape(arr: np.ndarray, where: str) -> None:
    if not isinstance(arr, np.ndarray):
        raise TypeError(
            f"{where} expected np.ndarray, got {type(arr).__name__}"
        )
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(
            f"{where} expected shape (H, W, 3); got {arr.shape}"
        )
    if arr.dtype != np.float32:
        # Be tolerant of float64 -- common in tests -- but warn.
        logger.debug("%s received dtype=%s; coercing to float32", where, arr.dtype)


def to_linear(image) -> LinearImage:
    """Best-effort coercion of ``PIL.Image`` or ndarray to LinearImage.

    Used by the viewer's transitional ``set_image`` to accept either
    type during the migration. Should not be used inside processors.
    """
    if isinstance(image, np.ndarray):
        if image.dtype != np.float32:
            return image.astype(np.float32, copy=False)
        return image
    if isinstance(image, Image.Image):
        return pil_to_linear(image)
    raise TypeError(
        f"to_linear: expected np.ndarray or PIL.Image, got {type(image).__name__}"
    )


__all__ = [
    "LinearImage",
    "srgb_to_linear",
    "linear_to_srgb",
    "uint8_srgb_to_linear",
    "uint16_srgb_to_linear",
    "pil_to_linear",
    "linear_to_pil",
    "linear_to_qimage",
    "to_linear",
]
