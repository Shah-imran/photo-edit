"""Image model for storing image data and state."""

from typing import Optional
from PIL import Image
from pathlib import Path


class ImageModel:
    """Model for storing image data and managing image state.
    
    This model holds both the original (unmodified) image and the current
    (potentially modified) image, enabling non-destructive editing.
    """

    def __init__(self, file_path: Optional[str] = None):
        """Initialize ImageModel.
        
        Args:
            file_path: Optional path to the image file
        """
        self.file_path: Optional[str] = file_path
        self.original_image: Optional[Image.Image] = None
        self.current_image: Optional[Image.Image] = None
        self._is_modified: bool = False

    def set_original_image(self, image: Image.Image) -> None:
        """Set the original (unmodified) image.
        
        This also sets the current image to the original, resetting any modifications.
        
        Args:
            image: PIL Image object
        """
        self.original_image = image
        self.current_image = image
        self._is_modified = False

    def get_original_image(self) -> Optional[Image.Image]:
        """Get the original (unmodified) image.
        
        Returns:
            Original PIL Image or None if no image is loaded
        """
        return self.original_image

    def get_current_image(self) -> Optional[Image.Image]:
        """Get the current (potentially modified) image.
        
        Returns:
            Current PIL Image or None if no image is loaded
        """
        return self.current_image

    def has_image(self) -> bool:
        """Check if an image is loaded.
        
        Returns:
            True if an image is loaded, False otherwise
        """
        return self.original_image is not None

    def get_image_size(self) -> tuple[int, int]:
        """Get the size of the current image.
        
        Returns:
            Tuple of (width, height) in pixels, or (0, 0) if no image
        """
        if self.current_image is not None:
            return self.current_image.size
        return (0, 0)

    def reset_to_original(self) -> None:
        """Reset the current image to the original (unmodified) state."""
        if self.original_image is not None:
            self.current_image = self.original_image
            self._is_modified = False

    def is_modified(self) -> bool:
        """Check if the current image has been modified from the original.
        
        Returns:
            True if modified, False if same as original or no image loaded
        """
        if not self.has_image():
            return False
        return self._is_modified
    
    def set_modified(self, modified: bool = True) -> None:
        """Set the modification state.
        
        Args:
            modified: True to mark as modified, False to mark as unmodified
        """
        self._is_modified = modified
