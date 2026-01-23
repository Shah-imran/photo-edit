"""Image service for loading, saving, and processing images."""

from typing import Optional, Dict, List, Tuple
from PIL import Image
from pathlib import Path


class ImageService:
    """Service for image loading, saving, and basic operations.
    
    This service handles file I/O operations for images and provides
    utilities for image manipulation.
    """

    # Supported image formats
    SUPPORTED_FORMATS = ["JPEG", "PNG", "TIFF", "BMP", "WEBP"]

    def __init__(self):
        """Initialize ImageService."""
        pass

    def load_image(self, file_path: str) -> Image.Image:
        """Load an image from a file path.
        
        Args:
            file_path: Path to the image file
            
        Returns:
            PIL Image object
            
        Raises:
            FileNotFoundError: If the file doesn't exist
            ValueError: If the file is not a valid image
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {file_path}")
        
        try:
            image = Image.open(file_path)
            # Convert to RGB if necessary (for JPEG compatibility)
            if image.mode not in ("RGB", "RGBA", "L"):
                image = image.convert("RGB")
            return image
        except Exception as e:
            raise ValueError(f"Failed to load image: {file_path}") from e

    def save_image(
        self,
        image: Image.Image,
        file_path: str,
        format: Optional[str] = None,
        quality: int = 95,
        **kwargs
    ) -> None:
        """Save an image to a file.
        
        Args:
            image: PIL Image object to save
            file_path: Path where to save the image
            format: Image format (JPEG, PNG, etc.). If None, inferred from extension
            quality: Quality for JPEG (1-100, default 95)
            **kwargs: Additional format-specific options
        """
        if format is None:
            # Infer format from file extension
            ext = Path(file_path).suffix.lower()
            format_map = {
                ".jpg": "JPEG",
                ".jpeg": "JPEG",
                ".png": "PNG",
                ".tiff": "TIFF",
                ".tif": "TIFF",
                ".bmp": "BMP",
                ".webp": "WEBP"
            }
            format = format_map.get(ext, "JPEG")
        
        save_kwargs = {"format": format}
        if format == "JPEG":
            save_kwargs["quality"] = quality
            # Convert RGBA to RGB for JPEG
            if image.mode == "RGBA":
                # Create white background
                rgb_image = Image.new("RGB", image.size, (255, 255, 255))
                rgb_image.paste(image, mask=image.split()[3])
                image = rgb_image
        
        save_kwargs.update(kwargs)
        image.save(file_path, **save_kwargs)

    def get_supported_formats(self) -> List[str]:
        """Get list of supported image formats.
        
        Returns:
            List of format names
        """
        return self.SUPPORTED_FORMATS.copy()

    def is_format_supported(self, format: str) -> bool:
        """Check if an image format is supported.
        
        Args:
            format: Format name (e.g., "JPEG", "PNG")
            
        Returns:
            True if format is supported, False otherwise
        """
        return format.upper() in self.SUPPORTED_FORMATS

    def create_thumbnail(
        self,
        image: Image.Image,
        size: Tuple[int, int],
        maintain_aspect: bool = True
    ) -> Image.Image:
        """Create a thumbnail of an image.
        
        Args:
            image: PIL Image to create thumbnail from
            size: Target size as (width, height)
            maintain_aspect: If True, maintain aspect ratio
            
        Returns:
            Thumbnail Image
        """
        if maintain_aspect:
            image.thumbnail(size, Image.Resampling.LANCZOS)
            return image.copy()
        else:
            return image.resize(size, Image.Resampling.LANCZOS)

    def get_image_info(self, file_path: str) -> Dict[str, any]:
        """Get information about an image file.
        
        Args:
            file_path: Path to the image file
            
        Returns:
            Dictionary with image information (width, height, format, etc.)
        """
        try:
            with Image.open(file_path) as img:
                return {
                    "width": img.width,
                    "height": img.height,
                    "format": img.format,
                    "mode": img.mode,
                    "size": img.size
                }
        except Exception as e:
            raise ValueError(f"Failed to get image info: {file_path}") from e
