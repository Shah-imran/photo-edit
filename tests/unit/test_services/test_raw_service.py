"""Unit tests for RawService (mocked rawpy where needed)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.services.raw_service import RawService


@pytest.fixture
def raw_svc():
    return RawService()


class TestUint16ToLinear:
    def test_full_scale_white_is_one_linear_after_pipeline(self, raw_svc):
        rgb = np.full((4, 4, 3), 65535, dtype=np.uint16)
        lin = raw_svc._uint16_srgb_to_linear(rgb)
        assert lin.shape == (4, 4, 3)
        np.testing.assert_allclose(lin, 1.0, atol=1e-5)


class TestResizeMaxSide:
    def test_no_resize_when_already_small(self, raw_svc):
        arr = np.zeros((10, 10, 3), dtype=np.float32)
        out = raw_svc._resize_max_side(arr, max_side=80)
        assert out.shape == (10, 10, 3)

    def test_downscales_to_fit(self, raw_svc):
        arr = np.zeros((200, 300, 3), dtype=np.float32)
        out = raw_svc._resize_max_side(arr, max_side=100)
        assert max(out.shape[0], out.shape[1]) <= 100


class TestDecodeThumbnailObject:
    def test_jpeg_bytes_to_linear(self, raw_svc):
        from io import BytesIO

        from PIL import Image
        import rawpy

        pil = Image.new("RGB", (32, 24), color=(100, 150, 200))
        buf = BytesIO()
        pil.save(buf, format="JPEG", quality=95)
        thumb = MagicMock()
        thumb.format = rawpy.ThumbFormat.JPEG
        thumb.data = buf.getvalue()

        out = raw_svc._decode_thumbnail_object(thumb)
        assert out is not None
        assert out.shape == (24, 32, 3)
        assert out.dtype == np.float32


@patch("src.services.raw_service.rawpy.imread")
def test_load_linear_calls_postprocess(mock_imread, raw_svc):
    rgb = np.zeros((20, 30, 3), dtype=np.uint16)
    rgb[..., :] = 32768

    fake_raw = MagicMock()
    fake_raw.postprocess = MagicMock(return_value=rgb)
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=fake_raw)
    ctx.__exit__ = MagicMock(return_value=False)
    mock_imread.return_value = ctx

    out = raw_svc.load_linear("/fake/path.nef")
    fake_raw.postprocess.assert_called_once()
    assert out.shape == (20, 30, 3)
    assert out.dtype == np.float32
    assert float(out.mean()) > 0.0
