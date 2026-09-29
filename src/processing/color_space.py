"""Color space conversions between encoded (sRGB, gamma-compressed) and
linear-light representations.

This is the foundation the Lightroom-parity roadmap (see
``docs/planning/PRODUCT_ROADMAP.md`` and the design doc's Phase 0) calls
"the pipeline rewrite": every new Develop-panel processor operates on
float32 linear-light data rather than the 8-bit gamma-encoded buffers the
original ``ExposureProcessor``/``ColorProcessor`` pair used. Tonal recovery
(highlights/shadows), white balance, and anything else that needs to reason
about physical light quantities only behaves correctly in linear space -
doing the same math in gamma-encoded space is what produces the muddy,
non-physical results simple brightness/contrast filters are known for.

These functions are pure and allocate-and-return (never mutate their input),
so they compose safely in a processing pipeline and are trivial to unit
test with known reference values.
"""

from typing import Union

import numpy as np
from PIL import Image

# IEC 61966-2-1 sRGB transfer function constants.
_SRGB_LINEAR_THRESHOLD = 0.0031308
_SRGB_ENCODED_THRESHOLD = 0.04045
_SRGB_LINEAR_SLOPE = 12.92
_SRGB_GAMMA = 2.4
_SRGB_A = 0.055


def srgb_to_linear(encoded: np.ndarray) -> np.ndarray:
    """Convert sRGB-encoded values to linear light.

    Args:
        encoded: Array of sRGB-encoded values in [0.0, 1.0], any shape.
            Values outside this range are not clamped (a slightly
            over/under-range intermediate value is preserved rather than
            silently clipped, since a later step in the pipeline may still
            want the extra headroom).

    Returns:
        A new float32 array of the same shape holding linear-light values.
    """
    encoded = np.asarray(encoded, dtype=np.float32)
    linear = np.where(
        encoded <= _SRGB_ENCODED_THRESHOLD,
        encoded / _SRGB_LINEAR_SLOPE,
        ((encoded + _SRGB_A) / (1.0 + _SRGB_A)) ** _SRGB_GAMMA,
    )
    return linear.astype(np.float32)


def linear_to_srgb(linear: np.ndarray) -> np.ndarray:
    """Convert linear-light values to sRGB-encoded values.

    Args:
        linear: Array of linear-light values in [0.0, 1.0], any shape.

    Returns:
        A new float32 array of the same shape holding sRGB-encoded values.
    """
    linear = np.asarray(linear, dtype=np.float32)
    # Negative inputs would raise on fractional power; clip only the base
    # of the exponent, not the final result, so intentional out-of-range
    # highlights (> 1.0) still round-trip through the linear branch.
    safe_linear = np.clip(linear, 0.0, None)
    encoded = np.where(
        linear <= _SRGB_LINEAR_THRESHOLD,
        linear * _SRGB_LINEAR_SLOPE,
        (1.0 + _SRGB_A) * np.power(safe_linear, 1.0 / _SRGB_GAMMA) - _SRGB_A,
    )
    return encoded.astype(np.float32)


def image_to_linear(image: Image.Image) -> np.ndarray:
    """Decode a PIL Image (assumed sRGB-encoded, 8-bit) to a linear float32 array.

    Args:
        image: PIL Image in "RGB", "RGBA", or "L" mode.

    Returns:
        float32 array of shape (H, W, C) or (H, W) with values in [0.0, 1.0]
        in linear light. An alpha channel, if present, is left untouched
        (alpha is a coverage value, not a light quantity, so it is not
        gamma-decoded).
    """
    arr = np.asarray(image, dtype=np.float32) / 255.0
    if image.mode == "RGBA":
        rgb = srgb_to_linear(arr[..., :3])
        return np.concatenate([rgb, arr[..., 3:4]], axis=-1)
    return srgb_to_linear(arr)


def linear_to_image(linear: np.ndarray, mode: str) -> Image.Image:
    """Encode a linear float32 array back to an 8-bit PIL Image.

    Args:
        linear: float32 array of shape (H, W, C) or (H, W) in [0.0, 1.0]
            linear light, matching the layout :func:`image_to_linear` used
            for ``mode``.
        mode: Target PIL image mode ("RGB", "RGBA", or "L").

    Returns:
        An 8-bit PIL Image, values clipped to the valid [0, 255] range.
    """
    if mode == "RGBA":
        rgb = linear_to_srgb(linear[..., :3])
        encoded = np.concatenate([rgb, linear[..., 3:4]], axis=-1)
    else:
        encoded = linear_to_srgb(linear)
    quantized = np.clip(np.round(encoded * 255.0), 0, 255).astype(np.uint8)
    return Image.fromarray(quantized, mode=mode)
