"""Image service for loading, saving, and processing images.

All public APIs operate on the canonical pipeline format
(:data:`src.utils.color_pipeline.LinearImage`). Disk I/O still uses
PIL under the hood; conversion happens at this boundary so processors
and the model only ever see linear float arrays.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from src.utils.color_pipeline import (
    LinearImage,
    linear_to_pil,
    pil_to_linear,
)


logger = logging.getLogger(__name__)


class ImageService:
    """Service for image loading, saving, and basic operations."""

    SUPPORTED_FORMATS = ["JPEG", "PNG", "TIFF", "BMP", "WEBP"]

    def __init__(self):
        """Initialize ImageService."""
        pass

    def load_image(self, file_path: str) -> LinearImage:
        """Load an image and return it in the canonical linear format.

        Args:
            file_path: Path to the image file.

        Returns:
            ``LinearImage`` (float32, ``(H, W, 3)``, linear sRGB primaries).

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file is not a valid image.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {file_path}")

        try:
            with Image.open(file_path) as pil:
                pil.load()
                return pil_to_linear(pil)
        except Exception as e:
            raise ValueError(f"Failed to load image: {file_path}") from e

    def save_image(
        self,
        image: LinearImage,
        file_path: str,
        format: Optional[str] = None,
        quality: int = 95,
        **kwargs,
    ) -> None:
        """Save a ``LinearImage`` to disk via the PIL boundary.

        Args:
            image: ``LinearImage`` to save.
            file_path: Destination path.
            format: PIL format string (``"JPEG"``, ``"PNG"``, ...).
                If ``None``, inferred from the file extension.
            quality: JPEG quality (1-100).
            **kwargs: Extra options forwarded to ``PIL.Image.save``.
        """
        if format is None:
            ext = Path(file_path).suffix.lower()
            format_map = {
                ".jpg": "JPEG",
                ".jpeg": "JPEG",
                ".png": "PNG",
                ".tiff": "TIFF",
                ".tif": "TIFF",
                ".bmp": "BMP",
                ".webp": "WEBP",
            }
            format = format_map.get(ext, "JPEG")

        pil = linear_to_pil(image)

        save_kwargs: Dict[str, Any] = {"format": format}
        if format == "JPEG":
            save_kwargs["quality"] = quality
        save_kwargs.update(kwargs)

        pil.save(file_path, **save_kwargs)

    def get_supported_formats(self) -> List[str]:
        """Return the supported format names."""
        return self.SUPPORTED_FORMATS.copy()

    def is_format_supported(self, format: str) -> bool:
        """Check whether a format string is supported."""
        return format.upper() in self.SUPPORTED_FORMATS

    def create_thumbnail(
        self,
        image: LinearImage,
        size: Tuple[int, int],
        maintain_aspect: bool = True,
    ) -> LinearImage:
        """Resize a ``LinearImage`` to a thumbnail.

        Uses ``cv2.resize`` with ``INTER_AREA`` (the recommended
        downscaling kernel) so we avoid PIL's uint8 round-trip.
        """
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError(
                f"create_thumbnail expected (H, W, 3); got {image.shape}"
            )

        max_w, max_h = size
        h, w = image.shape[:2]

        if maintain_aspect:
            scale = min(max_w / float(w), max_h / float(h), 1.0)
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
        else:
            new_w, new_h = max_w, max_h

        if (new_w, new_h) == (w, h):
            return image.copy()

        resized = cv2.resize(
            image,
            (new_w, new_h),
            interpolation=cv2.INTER_AREA,
        )
        return resized.astype(np.float32, copy=False)

    def get_image_info(self, file_path: str) -> Dict[str, Any]:
        """Return basic metadata for an image file (size, format, mode).

        Reads via PIL without loading pixels so this is cheap.
        """
        try:
            with Image.open(file_path) as img:
                return {
                    "width": img.width,
                    "height": img.height,
                    "format": img.format,
                    "mode": img.mode,
                    "size": img.size,
                }
        except Exception as e:
            raise ValueError(f"Failed to get image info: {file_path}") from e
