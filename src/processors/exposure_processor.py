"""Exposure processor for adjusting image exposure, contrast, and brightness."""

from PIL import Image, ImageEnhance
import numpy as np
from src.processors.base_processor import BaseProcessor


class ExposureProcessor(BaseProcessor):
    """Processor for exposure-related adjustments.
    
    Handles exposure, contrast, brightness adjustments.
    """

    def process(
        self,
        image: Image.Image,
        exposure: float = 0.0,
        contrast: float = 0.0,
        brightness: float = 0.0
    ) -> Image.Image:
        """Apply exposure adjustments to an image.
        
        Args:
            image: PIL Image to process
            exposure: Exposure adjustment (-5.0 to +5.0 stops)
            contrast: Contrast adjustment (-100 to +100)
            brightness: Brightness adjustment (-100 to +100)
            
        Returns:
            Processed PIL Image
        """
        result = image.copy()
        
        # Apply exposure adjustment (simulates camera exposure stops)
        if exposure != 0.0:
            result = self._adjust_exposure(result, exposure)
        
        # Apply brightness adjustment
        if brightness != 0.0:
            result = self._adjust_brightness(result, brightness)
        
        # Apply contrast adjustment
        if contrast != 0.0:
            result = self._adjust_contrast(result, contrast)
        
        return result

    def _adjust_exposure(self, image: Image.Image, stops: float) -> Image.Image:
        """Adjust exposure by simulating camera stops.
        
        Args:
            image: PIL Image to adjust
            stops: Number of stops (-5.0 to +5.0)
            
        Returns:
            Adjusted PIL Image
        """
        # Convert to numpy for faster processing
        arr = np.array(image, dtype=np.float32)
        
        # Apply exposure multiplier (2^stops simulates camera exposure)
        multiplier = 2.0 ** stops
        arr = arr * multiplier
        
        # Clip values to valid range
        arr = np.clip(arr, 0, 255).astype(np.uint8)
        
        return Image.fromarray(arr, mode=image.mode)

    def _adjust_brightness(self, image: Image.Image, value: float) -> Image.Image:
        """Adjust brightness.
        
        Args:
            image: PIL Image to adjust
            value: Brightness adjustment (-100 to +100)
            
        Returns:
            Adjusted PIL Image
        """
        # Convert value to enhancer factor (0.0 = black, 1.0 = original, 2.0 = max bright)
        factor = 1.0 + (value / 100.0)
        factor = max(0.0, min(2.0, factor))
        
        enhancer = ImageEnhance.Brightness(image)
        return enhancer.enhance(factor)

    def _adjust_contrast(self, image: Image.Image, value: float) -> Image.Image:
        """Adjust contrast.
        
        Args:
            image: PIL Image to adjust
            value: Contrast adjustment (-100 to +100)
            
        Returns:
            Adjusted PIL Image
        """
        # Convert value to enhancer factor (0.0 = gray, 1.0 = original, 2.0 = max contrast)
        factor = 1.0 + (value / 100.0)
        factor = max(0.0, min(2.0, factor))
        
        enhancer = ImageEnhance.Contrast(image)
        return enhancer.enhance(factor)
