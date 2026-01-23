"""Color processor for adjusting image saturation and color properties."""

from PIL import Image, ImageEnhance
import numpy as np
from src.processors.base_processor import BaseProcessor


class ColorProcessor(BaseProcessor):
    """Processor for color-related adjustments.
    
    Handles saturation, vibrance, and color adjustments.
    """

    def process(
        self,
        image: Image.Image,
        saturation: float = 0.0,
        vibrance: float = 0.0
    ) -> Image.Image:
        """Apply color adjustments to an image.
        
        Args:
            image: PIL Image to process
            saturation: Saturation adjustment (-100 to +100)
            vibrance: Vibrance adjustment (-100 to +100)
            
        Returns:
            Processed PIL Image
        """
        result = image.copy()
        
        # Apply vibrance first (affects less saturated colors more)
        if vibrance != 0.0:
            result = self._adjust_vibrance(result, vibrance)
        
        # Apply saturation adjustment
        if saturation != 0.0:
            result = self._adjust_saturation(result, saturation)
        
        return result

    def _adjust_saturation(self, image: Image.Image, value: float) -> Image.Image:
        """Adjust saturation.
        
        Args:
            image: PIL Image to adjust
            value: Saturation adjustment (-100 to +100)
            
        Returns:
            Adjusted PIL Image
        """
        # Convert value to enhancer factor (0.0 = grayscale, 1.0 = original, 2.0 = max)
        factor = 1.0 + (value / 100.0)
        factor = max(0.0, min(2.0, factor))
        
        enhancer = ImageEnhance.Color(image)
        return enhancer.enhance(factor)

    def _adjust_vibrance(self, image: Image.Image, value: float) -> Image.Image:
        """Adjust vibrance (smart saturation that preserves skin tones).
        
        Vibrance increases saturation of less saturated colors more than
        already saturated colors, giving a more natural look.
        
        Args:
            image: PIL Image to adjust
            value: Vibrance adjustment (-100 to +100)
            
        Returns:
            Adjusted PIL Image
        """
        if value == 0.0:
            return image
        
        # Convert to HSV for smarter saturation adjustment
        hsv = image.convert('HSV')
        arr = np.array(hsv, dtype=np.float32)
        
        # Get saturation channel
        saturation_channel = arr[:, :, 1]
        
        # Calculate adjustment factor based on current saturation
        # Less saturated pixels get more boost
        max_sat = 255.0
        sat_normalized = saturation_channel / max_sat
        
        # Adjustment is stronger for less saturated pixels
        adjustment_factor = value / 100.0
        
        # Apply vibrance formula: boost = adjustment * (1 - current_saturation)
        boost = adjustment_factor * (1.0 - sat_normalized)
        new_saturation = saturation_channel + (boost * max_sat * 0.5)
        
        # Clip to valid range
        arr[:, :, 1] = np.clip(new_saturation, 0, 255)
        
        # Convert back to RGB
        result_hsv = Image.fromarray(arr.astype(np.uint8), mode='HSV')
        return result_hsv.convert(image.mode)
