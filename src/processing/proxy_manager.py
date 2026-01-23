"""Proxy image manager for fast preview processing."""

from typing import Optional, Tuple
from PIL import Image


class ProxyManager:
    """Manages proxy (low-resolution) images for fast preview processing.
    
    The proxy system maintains a smaller version of the original image
    that can be processed much faster for live preview during slider
    adjustments. The full-resolution processing happens on slider release.
    
    Attributes:
        DEFAULT_PROXY_SIZE: Default maximum dimension for proxy images (1200px)
    """
    
    DEFAULT_PROXY_SIZE = 1200  # Maximum dimension in pixels
    
    def __init__(self, max_size: int = DEFAULT_PROXY_SIZE):
        """Initialize the proxy manager.
        
        Args:
            max_size: Maximum dimension (width or height) for proxy images
        """
        self._max_size = max_size
        self._original_image: Optional[Image.Image] = None
        self._proxy_image: Optional[Image.Image] = None
        self._original_size: Tuple[int, int] = (0, 0)
        self._proxy_size: Tuple[int, int] = (0, 0)
        self._scale_factor: float = 1.0
    
    @property
    def max_size(self) -> int:
        """Get the maximum proxy dimension."""
        return self._max_size
    
    @max_size.setter
    def max_size(self, value: int) -> None:
        """Set the maximum proxy dimension and regenerate proxy if needed."""
        if value != self._max_size:
            self._max_size = max(100, value)
            if self._original_image is not None:
                self._generate_proxy()
    
    @property
    def scale_factor(self) -> float:
        """Get the scale factor from proxy to original.
        
        Returns:
            Scale factor (original_size / proxy_size)
        """
        return self._scale_factor
    
    @property
    def original_size(self) -> Tuple[int, int]:
        """Get the original image size."""
        return self._original_size
    
    @property
    def proxy_size(self) -> Tuple[int, int]:
        """Get the proxy image size."""
        return self._proxy_size
    
    def set_image(self, image: Image.Image) -> None:
        """Set the original image and generate a proxy.
        
        Args:
            image: The original PIL Image
        """
        self._original_image = image.copy()
        self._original_size = image.size
        self._generate_proxy()
    
    def get_original(self) -> Optional[Image.Image]:
        """Get a copy of the original image.
        
        Returns:
            Copy of original image, or None if not set
        """
        if self._original_image is not None:
            return self._original_image.copy()
        return None
    
    def get_proxy(self) -> Optional[Image.Image]:
        """Get a copy of the proxy image.
        
        Returns:
            Copy of proxy image, or None if not set
        """
        if self._proxy_image is not None:
            return self._proxy_image.copy()
        return None
    
    def has_image(self) -> bool:
        """Check if an image is loaded.
        
        Returns:
            True if an image is loaded
        """
        return self._original_image is not None
    
    def needs_proxy(self) -> bool:
        """Check if the image is large enough to benefit from a proxy.
        
        Returns:
            True if the original is larger than proxy size
        """
        if self._original_image is None:
            return False
        width, height = self._original_size
        return width > self._max_size or height > self._max_size
    
    def clear(self) -> None:
        """Clear the stored images."""
        self._original_image = None
        self._proxy_image = None
        self._original_size = (0, 0)
        self._proxy_size = (0, 0)
        self._scale_factor = 1.0
    
    def get_pixel_count_ratio(self) -> float:
        """Get the ratio of proxy pixels to original pixels.
        
        This indicates how much faster proxy processing should be.
        
        Returns:
            Ratio of proxy pixels to original pixels (e.g., 0.03 = 3%)
        """
        if self._original_size[0] == 0 or self._proxy_size[0] == 0:
            return 1.0
        
        original_pixels = self._original_size[0] * self._original_size[1]
        proxy_pixels = self._proxy_size[0] * self._proxy_size[1]
        
        return proxy_pixels / original_pixels
    
    def _generate_proxy(self) -> None:
        """Generate the proxy image from the original."""
        if self._original_image is None:
            return
        
        width, height = self._original_size
        
        # Check if proxy is needed
        if width <= self._max_size and height <= self._max_size:
            # Image is small enough, use as-is
            self._proxy_image = self._original_image.copy()
            self._proxy_size = self._original_size
            self._scale_factor = 1.0
            return
        
        # Calculate new size maintaining aspect ratio
        if width > height:
            new_width = self._max_size
            new_height = int(height * (self._max_size / width))
        else:
            new_height = self._max_size
            new_width = int(width * (self._max_size / height))
        
        # Generate proxy using high-quality resampling
        self._proxy_image = self._original_image.resize(
            (new_width, new_height),
            Image.Resampling.LANCZOS
        )
        self._proxy_size = (new_width, new_height)
        self._scale_factor = width / new_width
    
    def upscale_to_original_size(self, processed_proxy: Image.Image) -> Image.Image:
        """Upscale a processed proxy image to original size.
        
        This is useful when you want to preview the proxy result at full size
        while waiting for the full-resolution processing to complete.
        
        Args:
            processed_proxy: The processed proxy image
            
        Returns:
            Upscaled image at original dimensions
        """
        if self._original_size == (0, 0):
            return processed_proxy
        
        return processed_proxy.resize(
            self._original_size,
            Image.Resampling.LANCZOS
        )


class ProxyResult:
    """Container for processing results with both proxy and full-res data."""
    
    def __init__(
        self,
        proxy_image: Optional[Image.Image] = None,
        full_image: Optional[Image.Image] = None,
        is_proxy: bool = True,
        request_id: int = 0
    ):
        """Initialize the proxy result.
        
        Args:
            proxy_image: The processed proxy image
            full_image: The processed full-resolution image
            is_proxy: Whether this result is from proxy processing
            request_id: The request ID this result corresponds to
        """
        self.proxy_image = proxy_image
        self.full_image = full_image
        self.is_proxy = is_proxy
        self.request_id = request_id
    
    def get_display_image(self) -> Optional[Image.Image]:
        """Get the best available image for display.
        
        Returns:
            Full image if available, otherwise proxy
        """
        return self.full_image if self.full_image is not None else self.proxy_image
