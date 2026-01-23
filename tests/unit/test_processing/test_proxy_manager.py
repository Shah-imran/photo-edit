"""Unit tests for ProxyManager."""

import pytest
from PIL import Image
from src.processing.proxy_manager import ProxyManager, ProxyResult


class TestProxyManager:
    """Test cases for ProxyManager class."""

    def test_proxy_manager_initialization(self):
        """Test ProxyManager can be initialized."""
        pm = ProxyManager()
        assert pm is not None
        assert pm.max_size == ProxyManager.DEFAULT_PROXY_SIZE

    def test_proxy_manager_custom_size(self):
        """Test ProxyManager with custom max size."""
        pm = ProxyManager(max_size=800)
        assert pm.max_size == 800

    def test_set_image(self):
        """Test setting an image."""
        pm = ProxyManager()
        image = Image.new('RGB', (2000, 1500), color='red')
        
        pm.set_image(image)
        
        assert pm.has_image() is True
        assert pm.original_size == (2000, 1500)

    def test_proxy_generation_large_image(self):
        """Test proxy is generated for large images."""
        pm = ProxyManager(max_size=1000)
        image = Image.new('RGB', (4000, 3000), color='blue')
        
        pm.set_image(image)
        
        assert pm.needs_proxy() is True
        assert pm.proxy_size[0] <= 1000
        assert pm.proxy_size[1] <= 1000

    def test_proxy_generation_small_image(self):
        """Test no proxy needed for small images."""
        pm = ProxyManager(max_size=1000)
        image = Image.new('RGB', (800, 600), color='green')
        
        pm.set_image(image)
        
        assert pm.needs_proxy() is False
        assert pm.proxy_size == (800, 600)

    def test_get_original(self):
        """Test getting original image."""
        pm = ProxyManager()
        image = Image.new('RGB', (100, 100), color='red')
        pm.set_image(image)
        
        original = pm.get_original()
        
        assert original is not None
        assert original.size == (100, 100)

    def test_get_proxy(self):
        """Test getting proxy image."""
        pm = ProxyManager(max_size=500)
        image = Image.new('RGB', (2000, 1000), color='red')
        pm.set_image(image)
        
        proxy = pm.get_proxy()
        
        assert proxy is not None
        assert proxy.size[0] <= 500

    def test_clear(self):
        """Test clearing images."""
        pm = ProxyManager()
        image = Image.new('RGB', (100, 100), color='red')
        pm.set_image(image)
        
        pm.clear()
        
        assert pm.has_image() is False
        assert pm.original_size == (0, 0)

    def test_scale_factor(self):
        """Test scale factor calculation."""
        pm = ProxyManager(max_size=500)
        image = Image.new('RGB', (2000, 1000), color='red')
        pm.set_image(image)
        
        # Original is 2000px wide, proxy is 500px wide
        # Scale factor should be 4.0
        assert pm.scale_factor == pytest.approx(4.0, rel=0.1)

    def test_pixel_count_ratio(self):
        """Test pixel count ratio calculation."""
        pm = ProxyManager(max_size=500)
        image = Image.new('RGB', (2000, 1000), color='red')
        pm.set_image(image)
        
        ratio = pm.get_pixel_count_ratio()
        
        # Proxy has ~1/16 the pixels of original (500*250 vs 2000*1000)
        assert ratio < 0.1  # Less than 10% of original pixels

    def test_upscale_to_original_size(self):
        """Test upscaling processed proxy to original size."""
        pm = ProxyManager(max_size=500)
        image = Image.new('RGB', (2000, 1000), color='red')
        pm.set_image(image)
        
        proxy = pm.get_proxy()
        upscaled = pm.upscale_to_original_size(proxy)
        
        assert upscaled.size == (2000, 1000)

    def test_aspect_ratio_preserved(self):
        """Test that aspect ratio is preserved in proxy."""
        pm = ProxyManager(max_size=500)
        image = Image.new('RGB', (3000, 2000), color='red')
        pm.set_image(image)
        
        original_ratio = 3000 / 2000
        proxy_ratio = pm.proxy_size[0] / pm.proxy_size[1]
        
        assert proxy_ratio == pytest.approx(original_ratio, rel=0.01)


class TestProxyResult:
    """Test cases for ProxyResult class."""

    def test_proxy_result_initialization(self):
        """Test ProxyResult can be initialized."""
        result = ProxyResult()
        assert result is not None
        assert result.is_proxy is True

    def test_proxy_result_with_images(self):
        """Test ProxyResult with images."""
        proxy = Image.new('RGB', (100, 100), color='red')
        full = Image.new('RGB', (1000, 1000), color='blue')
        
        result = ProxyResult(
            proxy_image=proxy,
            full_image=full,
            is_proxy=False,
            request_id=42
        )
        
        assert result.request_id == 42
        assert result.is_proxy is False

    def test_get_display_image_prefers_full(self):
        """Test get_display_image returns full if available."""
        proxy = Image.new('RGB', (100, 100), color='red')
        full = Image.new('RGB', (1000, 1000), color='blue')
        
        result = ProxyResult(proxy_image=proxy, full_image=full)
        
        assert result.get_display_image() == full

    def test_get_display_image_fallback_to_proxy(self):
        """Test get_display_image returns proxy if full not available."""
        proxy = Image.new('RGB', (100, 100), color='red')
        
        result = ProxyResult(proxy_image=proxy)
        
        assert result.get_display_image() == proxy
