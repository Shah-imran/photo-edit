"""Base processor class for image processing operations."""

from abc import ABC, abstractmethod
from PIL import Image


class BaseProcessor(ABC):
    """Abstract base class for image processors.
    
    All image processing operations should extend this class.
    """

    @abstractmethod
    def process(self, image: Image.Image, **kwargs) -> Image.Image:
        """Process an image with the given parameters.
        
        Args:
            image: PIL Image to process
            **kwargs: Processing parameters
            
        Returns:
            Processed PIL Image
        """
        pass
