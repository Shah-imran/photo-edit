"""Performance tests for proxy image system."""

import pytest
import time
import numpy as np
from src.processing.proxy_manager import ProxyManager


def linear_image(width: int, height: int, value: float = 0.25) -> np.ndarray:
    return np.full((height, width, 3), value, dtype=np.float32)


class TestProxyPerformance:
    """Test that proxy images provide performance benefits."""

    def test_proxy_processing_faster(self):
        """Test that processing proxy is significantly faster than full-res."""
        # Create large image (simulating 24MP DSLR)
        large_image = linear_image(6000, 4000)
        
        pm = ProxyManager(max_size=1200)
        pm.set_image(large_image)
        
        # Get images
        original = pm.get_original()
        proxy = pm.get_proxy()
        
        # Measure processing time for full resolution
        start = time.perf_counter()
        for _ in range(5):
            # Simulate processing (simple operation)
            result = original.copy()
            result *= np.float32(1.01)
        full_time = time.perf_counter() - start
        
        # Measure processing time for proxy
        start = time.perf_counter()
        for _ in range(5):
            result = proxy.copy()
            result *= np.float32(1.01)
        proxy_time = time.perf_counter() - start
        
        # Proxy should be at least 5x faster (usually much more)
        speedup = full_time / proxy_time
        assert speedup > 5.0, f"Proxy only {speedup:.1f}x faster, expected >5x"
        
        print(f"\nProxy processing: {proxy_time*1000:.1f}ms")
        print(f"Full processing: {full_time*1000:.1f}ms")
        print(f"Speedup: {speedup:.1f}x")

    def test_proxy_pixel_count_ratio(self):
        """Test that proxy has significantly fewer pixels."""
        large_image = linear_image(6000, 4000)
        
        pm = ProxyManager(max_size=1200)
        pm.set_image(large_image)
        
        ratio = pm.get_pixel_count_ratio()
        
        # Proxy should have < 5% of original pixels
        assert ratio < 0.05, f"Proxy has {ratio*100:.1f}% of pixels, expected <5%"
        
        # Verify actual pixel counts
        original_pixels = 6000 * 4000  # 24,000,000
        proxy_pixels = pm.proxy_size[0] * pm.proxy_size[1]
        
        assert proxy_pixels < original_pixels * 0.05

    def test_proxy_generation_time(self):
        """Test that proxy generation is fast."""
        large_image = linear_image(6000, 4000)
        
        pm = ProxyManager(max_size=1200)
        
        # Measure proxy generation time
        start = time.perf_counter()
        pm.set_image(large_image)
        generation_time = time.perf_counter() - start
        
        # Should generate in < 500ms even for large images
        assert generation_time < 0.5, f"Proxy generation took {generation_time*1000:.1f}ms"
        
        print(f"\nProxy generation time: {generation_time*1000:.1f}ms")

    def test_proxy_not_needed_for_small_images(self):
        """Test that small images don't use proxy."""
        small_image = linear_image(800, 600)
        
        pm = ProxyManager(max_size=1200)
        pm.set_image(small_image)
        
        # Should not need proxy
        assert pm.needs_proxy() is False
        assert pm.proxy_size == (800, 600)
        assert pm.scale_factor == 1.0

    def test_proxy_maintains_aspect_ratio(self):
        """Test that proxy maintains aspect ratio for accurate preview."""
        # Wide image
        wide_image = linear_image(4000, 2000)
        pm_wide = ProxyManager(max_size=1200)
        pm_wide.set_image(wide_image)
        
        original_ratio = 4000 / 2000  # 2.0
        proxy_ratio = pm_wide.proxy_size[0] / pm_wide.proxy_size[1]
        
        assert abs(proxy_ratio - original_ratio) < 0.01
        
        # Tall image
        tall_image = linear_image(2000, 4000)
        pm_tall = ProxyManager(max_size=1200)
        pm_tall.set_image(tall_image)
        
        original_ratio = 2000 / 4000  # 0.5
        proxy_ratio = pm_tall.proxy_size[0] / pm_tall.proxy_size[1]
        
        assert abs(proxy_ratio - original_ratio) < 0.01
