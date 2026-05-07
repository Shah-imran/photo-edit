"""Proxy image manager for fast preview processing.

Holds the original ``LinearImage`` plus a smaller proxy that processors
operate on during interactive slider drags. The full-resolution image
is processed only on slider release. All values are float32 linear-light
(see :mod:`src.utils.color_pipeline`).
"""

from __future__ import annotations

from typing import Optional, Tuple

import cv2
import numpy as np

from src.utils.color_pipeline import LinearImage


class ProxyManager:
    """Maintain a downscaled proxy alongside the original ``LinearImage``."""

    DEFAULT_PROXY_SIZE = 1400  # Quality preview maximum dimension
    DEFAULT_INTERACTIVE_PROXY_SIZE = 600  # Drag preview maximum dimension

    def __init__(
        self,
        max_size: int = DEFAULT_PROXY_SIZE,
        interactive_max_size: int = DEFAULT_INTERACTIVE_PROXY_SIZE,
    ):
        """Initialize the proxy manager.

        Args:
            max_size: Maximum width or height of the proxy.
        """
        self._max_size = max_size
        self._interactive_max_size = interactive_max_size
        self._original_image: Optional[LinearImage] = None
        self._proxy_image: Optional[LinearImage] = None
        self._interactive_proxy_image: Optional[LinearImage] = None
        self._original_size: Tuple[int, int] = (0, 0)
        self._proxy_size: Tuple[int, int] = (0, 0)
        self._interactive_proxy_size: Tuple[int, int] = (0, 0)
        self._scale_factor: float = 1.0

    @property
    def max_size(self) -> int:
        return self._max_size

    @max_size.setter
    def max_size(self, value: int) -> None:
        if value != self._max_size:
            self._max_size = max(100, value)
            if self._original_image is not None:
                self._generate_proxy()

    @property
    def interactive_max_size(self) -> int:
        return self._interactive_max_size

    @property
    def scale_factor(self) -> float:
        return self._scale_factor

    @property
    def original_size(self) -> Tuple[int, int]:
        return self._original_size

    @property
    def proxy_size(self) -> Tuple[int, int]:
        return self._proxy_size

    def set_image(self, image: LinearImage) -> None:
        """Store a copy of ``image`` as the original and (re)build the proxy."""
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError(
                f"ProxyManager.set_image expected (H, W, 3); got {image.shape}"
            )
        self._original_image = image.copy()
        h, w = image.shape[:2]
        self._original_size = (w, h)
        self._generate_proxy()

    def get_original(self) -> Optional[LinearImage]:
        """Return a copy of the original image, or ``None``."""
        if self._original_image is None:
            return None
        return self._original_image.copy()

    def get_proxy(self, interactive: bool = False) -> Optional[LinearImage]:
        """Return a copy of the proxy image, or ``None``."""
        if interactive:
            if self._interactive_proxy_image is None:
                return None
            return self._interactive_proxy_image.copy()
        if self._proxy_image is None:
            return None
        return self._proxy_image.copy()

    def has_image(self) -> bool:
        return self._original_image is not None

    def needs_proxy(self) -> bool:
        if self._original_image is None:
            return False
        width, height = self._original_size
        return width > self._max_size or height > self._max_size

    def clear(self) -> None:
        self._original_image = None
        self._proxy_image = None
        self._interactive_proxy_image = None
        self._original_size = (0, 0)
        self._proxy_size = (0, 0)
        self._interactive_proxy_size = (0, 0)
        self._scale_factor = 1.0

    def get_pixel_count_ratio(self) -> float:
        if self._original_size[0] == 0 or self._proxy_size[0] == 0:
            return 1.0
        original_pixels = self._original_size[0] * self._original_size[1]
        proxy_pixels = self._proxy_size[0] * self._proxy_size[1]
        return proxy_pixels / original_pixels

    def _generate_proxy(self) -> None:
        if self._original_image is None:
            return

        quality = self._resize_max_side(self._original_image, self._max_size)
        interactive = self._resize_max_side(
            self._original_image, self._interactive_max_size
        )
        self._proxy_image = quality
        self._interactive_proxy_image = interactive
        self._proxy_size = (quality.shape[1], quality.shape[0])
        self._interactive_proxy_size = (interactive.shape[1], interactive.shape[0])
        self._scale_factor = self._original_size[0] / float(self._proxy_size[0])

    @staticmethod
    def _resize_max_side(image: LinearImage, max_size: int) -> LinearImage:
        h, w = image.shape[:2]
        if w <= max_size and h <= max_size:
            return image.copy()
        if w > h:
            new_w = max_size
            new_h = max(1, int(round(h * (max_size / w))))
        else:
            new_h = max_size
            new_w = max(1, int(round(w * (max_size / h))))
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        return resized.astype(np.float32, copy=False)

    def upscale_to_original_size(self, processed_proxy: LinearImage) -> LinearImage:
        """Upscale a processed proxy back to original dimensions.

        Used when we want to preview the proxy result at full size while
        the full-resolution processing is still running.
        """
        if self._original_size == (0, 0):
            return processed_proxy

        target_w, target_h = self._original_size
        h, w = processed_proxy.shape[:2]
        if (w, h) == (target_w, target_h):
            return processed_proxy.copy()

        upscaled = cv2.resize(
            processed_proxy,
            (target_w, target_h),
            interpolation=cv2.INTER_LANCZOS4,
        )
        return upscaled.astype(np.float32, copy=False)


class ProxyResult:
    """Container for processing results with both proxy and full-res data."""

    def __init__(
        self,
        proxy_image: Optional[LinearImage] = None,
        full_image: Optional[LinearImage] = None,
        is_proxy: bool = True,
        request_id: int = 0,
    ):
        self.proxy_image = proxy_image
        self.full_image = full_image
        self.is_proxy = is_proxy
        self.request_id = request_id

    def get_display_image(self) -> Optional[LinearImage]:
        return self.full_image if self.full_image is not None else self.proxy_image
