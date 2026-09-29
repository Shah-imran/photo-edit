"""Image model for storing image data and state.

The model stores the canonical pipeline format
(:data:`src.utils.color_pipeline.LinearImage`) for both the original
and the current (post-adjustment) image. Conversions to/from PIL or
``QImage`` happen at the boundaries (``ImageService``, ``ImageView``).
"""

from __future__ import annotations

from typing import Optional, Tuple

from src.utils.color_pipeline import LinearImage


class ImageModel:
    """Holds the loaded image plus its current edited state."""

    def __init__(self, file_path: Optional[str] = None):
        """Initialize ImageModel.

        Args:
            file_path: Optional path to the image file.
        """
        self.file_path: Optional[str] = file_path
        self.original_image: Optional[LinearImage] = None
        self.current_image: Optional[LinearImage] = None
        self._is_modified: bool = False

    def set_original_image(self, image: LinearImage) -> None:
        """Set the original (unmodified) image and reset current to it."""
        self.original_image = image
        self.current_image = image
        self._is_modified = False

    def get_original_image(self) -> Optional[LinearImage]:
        """Return the original (unmodified) image, or ``None``."""
        return self.original_image

    def get_current_image(self) -> Optional[LinearImage]:
        """Return the current (potentially modified) image, or ``None``."""
        return self.current_image

    def has_image(self) -> bool:
        """Whether an image is loaded."""
        return self.original_image is not None

    def get_image_size(self) -> Tuple[int, int]:
        """Return ``(width, height)`` of the current image, or ``(0, 0)``."""
        if self.current_image is None:
            return (0, 0)
        h, w = self.current_image.shape[:2]
        return (w, h)

    def reset_to_original(self) -> None:
        """Reset the current image back to the original."""
        if self.original_image is not None:
            self.current_image = self.original_image
            self._is_modified = False

    def is_modified(self) -> bool:
        """Whether the current image differs from the original."""
        if not self.has_image():
            return False
        return self._is_modified

    def set_modified(self, modified: bool = True) -> None:
        """Update the modification flag."""
        self._is_modified = modified
