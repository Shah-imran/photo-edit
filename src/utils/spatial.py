"""Resolution-independent neighbourhood operations.

Spatial effects used fixed pixel radii, so the same slider value looked
different on the 600 px drag preview, the 1400 px release preview and the
6000 px export -- what the user approved on screen was not what got
exported (Clarity differed by more than half its visible effect). Two
rules fix that, as Lightroom does:

* **Local-contrast effects** (clarity, dehaze, texture) scale their radius
  with the image: :func:`relative_sigma` keeps the look the preview had at
  ``REFERENCE_LONG_EDGE`` and reproduces it at any size.
* **Pixel-level effects** (sharpening, noise reduction) act on the photo's
  native pixels; a proxy passes its ``pixel_scale`` (proxy size / full
  size) so the preview shows what the downscaled export will look like.

:func:`gaussian_blur` keeps very wide blurs fast by blurring a reduced
copy and scaling back up (a Gaussian this wide has no detail to lose).
"""

from __future__ import annotations

import cv2
import numpy as np

# Long edge of the quality preview the effects were tuned on; at this size
# relative radii equal the old fixed ones, so the look users approved is
# unchanged.
REFERENCE_LONG_EDGE = 1400.0

# Above this sigma, blur a reduced copy (sigma stays >= this after scaling).
_PYRAMID_MIN_SIGMA = 6.0


def relative_sigma(image: np.ndarray, sigma_at_reference: float) -> float:
    """Radius for ``image`` that matches ``sigma_at_reference`` px at the
    reference preview size."""
    long_edge = max(image.shape[0], image.shape[1])
    return sigma_at_reference * long_edge / REFERENCE_LONG_EDGE


def gaussian_blur(image: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur (reflect-101 borders) that stays fast for large sigma."""
    sigma = float(sigma)
    if sigma <= 0.0:
        return image.copy()
    height, width = image.shape[0], image.shape[1]
    factor = 1
    while sigma / (factor * 2) >= _PYRAMID_MIN_SIGMA and min(height, width) // (factor * 2) >= 16:
        factor *= 2
    if factor == 1:
        return cv2.GaussianBlur(
            image, (0, 0), sigmaX=sigma, sigmaY=sigma, borderType=cv2.BORDER_REFLECT_101
        )
    small = cv2.resize(
        image,
        (max(1, width // factor), max(1, height // factor)),
        interpolation=cv2.INTER_AREA,
    )
    small = cv2.GaussianBlur(
        small, (0, 0), sigmaX=sigma / factor, sigmaY=sigma / factor,
        borderType=cv2.BORDER_REFLECT_101,
    )
    return cv2.resize(small, (width, height), interpolation=cv2.INTER_LINEAR).astype(
        np.float32, copy=False
    )
