"""Export service for saving edited images."""

from typing import Optional, Dict, Any, List
from pathlib import Path
from PIL import Image
from src.services.image_service import ImageService


class ExportService:
    """Service for exporting images to various formats.
    
    Handles image export with format-specific options like quality,
    compression, and resizing.
    """

    def __init__(self, image_service: Optional[ImageService] = None):
        """Initialize ExportService.
        
        Args:
            image_service: Optional ImageService for save operations
        """
        self._image_service = image_service or ImageService()

    def export_image(
        self,
        image: Image.Image,
        output_path: str,
        format: Optional[str] = None,
        quality: int = 95,
        resize: Optional[tuple] = None,
        preserve_aspect: bool = True,
        **kwargs
    ) -> bool:
        """Export an image to a file.
        
        Args:
            image: PIL Image to export
            output_path: Output file path
            format: Image format (JPEG, PNG, TIFF). If None, inferred from extension
            quality: JPEG quality (1-100, default 95)
            resize: Optional (width, height) to resize to
            preserve_aspect: If True, preserve aspect ratio when resizing
            **kwargs: Additional format-specific options
            
        Returns:
            True if export successful, False otherwise
        """
        try:
            # Apply resize if specified
            if resize:
                image = self._resize_image(image, resize, preserve_aspect)
            
            # Save the image
            self._image_service.save_image(
                image,
                output_path,
                format=format,
                quality=quality,
                **kwargs
            )
            return True
        except Exception as e:
            print(f"Export failed: {e}")
            return False

    def _resize_image(
        self,
        image: Image.Image,
        size: tuple,
        preserve_aspect: bool = True
    ) -> Image.Image:
        """Resize an image.
        
        Args:
            image: PIL Image to resize
            size: Target (width, height)
            preserve_aspect: If True, preserve aspect ratio
            
        Returns:
            Resized image
        """
        if preserve_aspect:
            image.thumbnail(size, Image.Resampling.LANCZOS)
            return image.copy()
        else:
            return image.resize(size, Image.Resampling.LANCZOS)

    def get_export_formats(self) -> List[Dict[str, Any]]:
        """Get available export formats with their options.
        
        Returns:
            List of format dictionaries with name, extension, and options
        """
        return [
            {
                'name': 'JPEG',
                'extension': '.jpg',
                'options': {
                    'quality': {'min': 1, 'max': 100, 'default': 95},
                    'progressive': {'type': 'bool', 'default': True}
                }
            },
            {
                'name': 'PNG',
                'extension': '.png',
                'options': {
                    'compress_level': {'min': 0, 'max': 9, 'default': 6}
                }
            },
            {
                'name': 'TIFF',
                'extension': '.tiff',
                'options': {
                    'compression': {'choices': ['none', 'lzw', 'jpeg'], 'default': 'none'}
                }
            }
        ]

    def get_resize_presets(self) -> List[Dict[str, Any]]:
        """Get common resize presets.
        
        Returns:
            List of preset dictionaries with name and dimensions
        """
        return [
            {'name': 'Original Size', 'size': None},
            {'name': '4K (3840x2160)', 'size': (3840, 2160)},
            {'name': 'Full HD (1920x1080)', 'size': (1920, 1080)},
            {'name': 'HD (1280x720)', 'size': (1280, 720)},
            {'name': 'Web Large (1200x800)', 'size': (1200, 800)},
            {'name': 'Web Medium (800x600)', 'size': (800, 600)},
            {'name': 'Web Small (640x480)', 'size': (640, 480)},
            {'name': 'Thumbnail (200x200)', 'size': (200, 200)}
        ]
