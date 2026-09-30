"""Export service for saving edited images."""

import logging
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from src.services.image_service import ImageService
from src.utils.color_pipeline import LinearImage


logger = logging.getLogger(__name__)


class ExportService:
    """Service for exporting images to various formats.
    
    Handles image export with format-specific options like quality,
    compression, and resizing.
    """

    def __init__(self, image_service: Optional[ImageService] = None):
        """Initialize ExportService.
        
        Args:
            image_service: Optional ImageService for save operations
        """
        self._image_service = image_service or ImageService()

    def export_image(
        self,
        image: LinearImage,
        output_path: str,
        format: Optional[str] = None,
        quality: int = 95,
        resize: Optional[Tuple[int, int]] = None,
        preserve_aspect: bool = True,
        **kwargs,
    ) -> bool:
        """Export a ``LinearImage`` to disk.

        Args:
            image: ``LinearImage`` (float32, ``(H, W, 3)``, linear sRGB).
            output_path: Output file path.
            format: PIL format name (``"JPEG"``, ``"PNG"``, ``"TIFF"``).
                When ``None``, inferred from the file extension.
            quality: JPEG quality (1-100).
            resize: Optional ``(width, height)`` target.
            preserve_aspect: When True, downscale fits inside the box.
            **kwargs: Forwarded to ``PIL.Image.save``.
        """
        try:
            if resize:
                image = self._resize_image(image, resize, preserve_aspect)

            self._image_service.save_image(
                image,
                output_path,
                format=format,
                quality=quality,
                **kwargs,
            )
            return True
        except Exception:
            logger.exception("Export failed for %s", output_path)
            return False

    def _resize_image(
        self,
        image: LinearImage,
        size: Tuple[int, int],
        preserve_aspect: bool = True,
    ) -> LinearImage:
        """Resize a ``LinearImage`` using ``cv2.resize``."""
        target_w, target_h = size
        h, w = image.shape[:2]

        if preserve_aspect:
            scale = min(target_w / float(w), target_h / float(h), 1.0)
            new_w = max(1, int(round(w * scale)))
            new_h = max(1, int(round(h * scale)))
        else:
            new_w, new_h = target_w, target_h

        if (new_w, new_h) == (w, h):
            return image.copy()

        # ``INTER_AREA`` is the canonical choice for downscale;
        # ``INTER_LANCZOS4`` is the canonical choice for upscale.
        interp = cv2.INTER_AREA if (new_w * new_h) <= (w * h) else cv2.INTER_LANCZOS4
        resized = cv2.resize(image, (new_w, new_h), interpolation=interp)
        return resized.astype(np.float32, copy=False)

    def get_export_formats(self) -> List[Dict[str, Any]]:
        """Get available export formats with their options.
        
        Returns:
            List of format dictionaries with name, extension, and options
        """
        return [
            {
                'name': 'JPEG',
                'extension': '.jpg',
                'options': {
                    'quality': {'min': 1, 'max': 100, 'default': 95},
                    'progressive': {'type': 'bool', 'default': True}
                }
            },
            {
                'name': 'PNG',
                'extension': '.png',
                'options': {
                    'compress_level': {'min': 0, 'max': 9, 'default': 6}
                }
            },
            {
                'name': 'TIFF',
                'extension': '.tiff',
                'options': {
                    'compression': {'choices': ['none', 'lzw', 'jpeg'], 'default': 'none'}
                }
            }
        ]

    def get_resize_presets(self) -> List[Dict[str, Any]]:
        """Get common resize presets.
        
        Returns:
            List of preset dictionaries with name and dimensions
        """
        return [
            {'name': 'Original Size', 'size': None},
            {'name': '4K (3840x2160)', 'size': (3840, 2160)},
            {'name': 'Full HD (1920x1080)', 'size': (1920, 1080)},
            {'name': 'HD (1280x720)', 'size': (1280, 720)},
            {'name': 'Web Large (1200x800)', 'size': (1200, 800)},
            {'name': 'Web Medium (800x600)', 'size': (800, 600)},
            {'name': 'Web Small (640x480)', 'size': (640, 480)},
            {'name': 'Thumbnail (200x200)', 'size': (200, 200)}
        ]
