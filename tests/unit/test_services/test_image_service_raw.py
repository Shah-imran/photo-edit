"""ImageService integration points for camera RAW (mocked RawService)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.services.image_service import ImageService


class TestImageServiceRawDispatch:
    def test_load_image_calls_raw_service_for_dng(self, tmp_path: Path):
        path = tmp_path / "test.dng"
        path.write_bytes(b"\0")

        arr = np.full((8, 8, 3), 0.5, dtype=np.float32)
        raw = MagicMock()
        raw.load_linear = MagicMock(return_value=arr)

        svc = ImageService(raw_service=raw)
        out = svc.load_image(str(path))

        raw.load_linear.assert_called_once_with(str(path))
        assert out is arr

    def test_load_preview_thumbnail_uses_thumbnail_linear(self, tmp_path: Path):
        path = tmp_path / "x.cr2"
        path.write_bytes(b"\0")

        thumb = np.zeros((40, 40, 3), dtype=np.float32)
        raw = MagicMock()
        raw.thumbnail_linear = MagicMock(return_value=thumb)

        svc = ImageService(raw_service=raw)
        out = svc.load_preview_thumbnail(str(path), (80, 80))

        raw.thumbnail_linear.assert_called_once_with(str(path), 80)
        assert out is thumb

    def test_get_image_info_raw(self, tmp_path: Path):
        path = tmp_path / "a.arw"
        path.write_bytes(b"\0")

        raw = MagicMock()
        raw.get_raw_dimensions = MagicMock(return_value=(6000, 4000))

        svc = ImageService(raw_service=raw)
        info = svc.get_image_info(str(path))

        assert info["width"] == 6000
        assert info["height"] == 4000
        assert info["format"] == "RAW"
