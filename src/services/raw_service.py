"""Load camera RAW files into the canonical :class:`~src.utils.color_pipeline.LinearImage`.

``rawpy`` demosaics and applies camera white balance; output is treated as
sRGB-encoded (gamma) before applying the sRGB EOTF to linear-light space,
matching the JPEG path in :mod:`src.utils.color_pipeline`.

**Non-goals for this slice:** Adobe DCP profiles, Lensfun, lens corrections,
custom WB UI, or 16-bit TIFF export of linear data -- those are separate
slices (R2/R3).
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Optional

import cv2
import numpy as np
import rawpy
from PIL import Image, ImageOps

from src.utils.color_pipeline import LinearImage, pil_to_linear, srgb_to_linear


logger = logging.getLogger(__name__)


class RawService:
    """Decode RAW files to ``LinearImage`` via rawpy / LibRaw."""

    def load_linear(
        self,
        path: str,
        *,
        use_camera_wb: bool = True,
    ) -> LinearImage:
        """Full-resolution demosaic to linear-light float32 sRGB primaries."""
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(
                output_bps=16,
                use_camera_wb=use_camera_wb,
                use_auto_wb=False,
                no_auto_bright=True,
                output_color=rawpy.ColorSpace.sRGB,
            )
        return self._uint16_srgb_to_linear(rgb)

    def thumbnail_linear(self, path: str, max_side: int) -> LinearImage:
        """Fast preview for library thumbnails.

        Tries an embedded JPEG/bitmap thumbnail first; falls back to
        ``half_size`` postprocess (still demosaiced, but quarter pixels)
        when no usable thumb exists.
        """
        max_side = max(1, int(max_side))
        with rawpy.imread(path) as raw:
            try:
                thumb = raw.extract_thumb()
            except (
                rawpy.LibRawNoThumbnailError,
                rawpy.LibRawUnsupportedThumbnailError,
            ):
                logger.debug("No embedded thumbnail for %s; using half decode", path)
                return self._half_postprocess_and_resize(raw, max_side)

            arr = self._decode_thumbnail_object(thumb)
            if arr is None:
                logger.debug("Could not decode embedded thumbnail for %s; using half decode", path)
                return self._half_postprocess_and_resize(raw, max_side)

            return self._resize_max_side(arr, max_side)

    def get_raw_dimensions(self, path: str) -> tuple[int, int]:
        """Return ``(width, height)`` of the processed image without demosaicing fully."""
        with rawpy.imread(path) as raw:
            w, h = raw.sizes.width, raw.sizes.height
        return (int(w), int(h))

    def _decode_thumbnail_object(self, thumb: rawpy.Thumbnail) -> Optional[LinearImage]:
        if thumb.format == rawpy.ThumbFormat.JPEG:
            pil = ImageOps.exif_transpose(Image.open(BytesIO(thumb.data))).convert("RGB")
            return pil_to_linear(pil)

        if thumb.format == rawpy.ThumbFormat.BITMAP:
            data = thumb.data
            if isinstance(data, np.ndarray):
                if data.ndim == 2:
                    u8 = np.stack([data, data, data], axis=-1)
                elif data.ndim == 3:
                    u8 = data[..., :3]
                else:
                    return None
                if u8.dtype != np.uint8:
                    u8 = np.clip(u8, 0, 255).astype(np.uint8)
                srgb = u8.astype(np.float32) / 255.0
                return srgb_to_linear(srgb).astype(np.float32)

        return None

    def _half_postprocess_and_resize(self, raw: rawpy.RawPy, max_side: int) -> LinearImage:
        rgb = raw.postprocess(
            output_bps=16,
            use_camera_wb=True,
            use_auto_wb=False,
            no_auto_bright=True,
            output_color=rawpy.ColorSpace.sRGB,
            half_size=True,
        )
        linear = self._uint16_srgb_to_linear(rgb)
        return self._resize_max_side(linear, max_side)

    @staticmethod
    def _uint16_srgb_to_linear(rgb: np.ndarray) -> LinearImage:
        arr_srgb = rgb.astype(np.float32) / 65535.0
        return srgb_to_linear(arr_srgb).astype(np.float32)

    @staticmethod
    def _resize_max_side(arr: LinearImage, max_side: int) -> LinearImage:
        h, w = arr.shape[:2]
        if max(h, w) <= max_side:
            return arr.copy()
        scale = max_side / float(max(h, w))
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        out = cv2.resize(arr, (new_w, new_h), interpolation=cv2.INTER_AREA)
        return out.astype(np.float32, copy=False)
