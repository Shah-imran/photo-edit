"""Project model for managing project state and image collections."""

from typing import Optional, List


class ProjectModel:
    """Model for managing project state and collections of images.
    
    This model tracks which images are in the project and which one
    is currently being edited.
    """

    def __init__(self, project_path: Optional[str] = None):
        """Initialize ProjectModel.
        
        Args:
            project_path: Optional path to the project file
        """
        self.project_path: Optional[str] = project_path
        self.images: List[str] = []
        self.current_image_index: Optional[int] = None

    def add_image(self, image_path: str) -> None:
        """Add an image to the project.
        
        Args:
            image_path: Path to the image file
        """
        if image_path not in self.images:
            self.images.append(image_path)

    def remove_image(self, image_path: str) -> None:
        """Remove an image from the project.
        
        Args:
            image_path: Path to the image file to remove
        """
        if image_path in self.images:
            index = self.images.index(image_path)
            self.images.remove(image_path)
            
            # Adjust current index if needed
            if self.current_image_index is not None:
                if self.current_image_index == index:
                    self.current_image_index = None
                elif self.current_image_index > index:
                    self.current_image_index -= 1

    def get_image_count(self) -> int:
        """Get the number of images in the project.
        
        Returns:
            Number of images
        """
        return len(self.images)

    def set_current_image_index(self, index: int) -> None:
        """Set the index of the currently active image.
        
        Args:
            index: Index of the image (0-based)
        """
        if 0 <= index < len(self.images):
            self.current_image_index = index

    def get_current_image_path(self) -> Optional[str]:
        """Get the path of the currently active image.
        
        Returns:
            Path to the current image, or None if no image is selected
        """
        if self.current_image_index is not None and 0 <= self.current_image_index < len(self.images):
            return self.images[self.current_image_index]
        return None

    def clear_images(self) -> None:
        """Clear all images from the project."""
        self.images.clear()
        self.current_image_index = None

    def has_images(self) -> bool:
        """Check if the project has any images.
        
        Returns:
            True if project has images, False otherwise
        """
        return len(self.images) > 0
