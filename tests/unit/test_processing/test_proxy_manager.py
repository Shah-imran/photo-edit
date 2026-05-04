"""Unit tests for ProxyManager (LinearImage backed)."""

import numpy as np
import pytest

from src.processing.proxy_manager import ProxyManager, ProxyResult


def _flat_linear(width: int, height: int, value: float = 0.5) -> np.ndarray:
    """Build a flat ``LinearImage`` of the requested size."""
    return np.full((height, width, 3), value, dtype=np.float32)


class TestProxyManager:
    """Test cases for ProxyManager."""

    def test_proxy_manager_initialization(self):
        pm = ProxyManager()
        assert pm is not None
        assert pm.max_size == ProxyManager.DEFAULT_PROXY_SIZE

    def test_proxy_manager_custom_size(self):
        pm = ProxyManager(max_size=800)
        assert pm.max_size == 800

    def test_set_image(self):
        pm = ProxyManager()
        image = _flat_linear(2000, 1500)

        pm.set_image(image)

        assert pm.has_image() is True
        assert pm.original_size == (2000, 1500)

    def test_proxy_generation_large_image(self):
        pm = ProxyManager(max_size=1000)
        image = _flat_linear(4000, 3000)

        pm.set_image(image)

        assert pm.needs_proxy() is True
        assert pm.proxy_size[0] <= 1000
        assert pm.proxy_size[1] <= 1000

    def test_proxy_generation_small_image(self):
        pm = ProxyManager(max_size=1000)
        image = _flat_linear(800, 600)

        pm.set_image(image)

        assert pm.needs_proxy() is False
        assert pm.proxy_size == (800, 600)

    def test_get_original(self):
        pm = ProxyManager()
        image = _flat_linear(100, 100)
        pm.set_image(image)

        original = pm.get_original()
        assert original is not None
        h, w = original.shape[:2]
        assert (w, h) == (100, 100)
        assert original.dtype == np.float32

    def test_get_proxy(self):
        pm = ProxyManager(max_size=500)
        image = _flat_linear(2000, 1000)
        pm.set_image(image)

        proxy = pm.get_proxy()
        assert proxy is not None
        h, w = proxy.shape[:2]
        assert w <= 500
        assert proxy.dtype == np.float32

    def test_clear(self):
        pm = ProxyManager()
        image = _flat_linear(100, 100)
        pm.set_image(image)

        pm.clear()

        assert pm.has_image() is False
        assert pm.original_size == (0, 0)

    def test_scale_factor(self):
        pm = ProxyManager(max_size=500)
        image = _flat_linear(2000, 1000)
        pm.set_image(image)
        # Original 2000px wide, proxy 500px wide -> factor ~4.0.
        assert pm.scale_factor == pytest.approx(4.0, rel=0.1)

    def test_pixel_count_ratio(self):
        pm = ProxyManager(max_size=500)
        image = _flat_linear(2000, 1000)
        pm.set_image(image)
        ratio = pm.get_pixel_count_ratio()
        assert ratio < 0.1

    def test_upscale_to_original_size(self):
        pm = ProxyManager(max_size=500)
        image = _flat_linear(2000, 1000)
        pm.set_image(image)

        proxy = pm.get_proxy()
        upscaled = pm.upscale_to_original_size(proxy)
        h, w = upscaled.shape[:2]
        assert (w, h) == (2000, 1000)
        assert upscaled.dtype == np.float32

    def test_aspect_ratio_preserved(self):
        pm = ProxyManager(max_size=500)
        image = _flat_linear(3000, 2000)
        pm.set_image(image)

        original_ratio = 3000 / 2000
        proxy_ratio = pm.proxy_size[0] / pm.proxy_size[1]
        assert proxy_ratio == pytest.approx(original_ratio, rel=0.01)


class TestProxyResult:
    """Test cases for ProxyResult."""

    def test_proxy_result_initialization(self):
        result = ProxyResult()
        assert result is not None
        assert result.is_proxy is True

    def test_proxy_result_with_images(self):
        proxy = _flat_linear(100, 100)
        full = _flat_linear(1000, 1000)

        result = ProxyResult(
            proxy_image=proxy,
            full_image=full,
            is_proxy=False,
            request_id=42,
        )

        assert result.request_id == 42
        assert result.is_proxy is False

    def test_get_display_image_prefers_full(self):
        proxy = _flat_linear(100, 100)
        full = _flat_linear(1000, 1000)

        result = ProxyResult(proxy_image=proxy, full_image=full)
        out = result.get_display_image()
        assert out is full

    def test_get_display_image_fallback_to_proxy(self):
        proxy = _flat_linear(100, 100)
        result = ProxyResult(proxy_image=proxy)
        assert result.get_display_image() is proxy
