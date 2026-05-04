"""File service for file system operations."""

import os
from pathlib import Path
from typing import List

from src.utils.image_extensions import ALL_IMAGE_EXTENSIONS


class FileService:
    """Service for file system operations and file management.
    
    This service handles file operations like directory scanning,
    file validation, and file metadata.
    """

    # Includes standard raster formats and camera RAW (see image_extensions)
    IMAGE_EXTENSIONS = ALL_IMAGE_EXTENSIONS

    def __init__(self):
        """Initialize FileService."""
        pass

    def get_image_files_from_directory(
        self,
        directory: str,
        recursive: bool = False
    ) -> List[str]:
        """Get all image files from a directory.
        
        Args:
            directory: Path to the directory
            recursive: If True, search subdirectories recursively
            
        Returns:
            List of file paths to image files
        """
        path = Path(directory)
        if not path.exists() or not path.is_dir():
            return []
        
        image_files = []
        
        if recursive:
            for file_path in path.rglob("*"):
                if file_path.is_file() and self.is_image_file(file_path.name):
                    image_files.append(str(file_path))
        else:
            for file_path in path.iterdir():
                if file_path.is_file() and self.is_image_file(file_path.name):
                    image_files.append(str(file_path))
        
        return sorted(image_files)

    def is_image_file(self, filename: str) -> bool:
        """Check if a filename has an image extension.
        
        Args:
            filename: Name of the file
            
        Returns:
            True if file appears to be an image, False otherwise
        """
        ext = self.get_file_extension(filename).lower()
        return ext in self.IMAGE_EXTENSIONS

    def get_file_extension(self, filename: str) -> str:
        """Get the file extension from a filename.
        
        Args:
            filename: Name of the file
            
        Returns:
            File extension including the dot (e.g., ".jpg")
        """
        return Path(filename).suffix

    def validate_file_path(self, file_path: str) -> bool:
        """Validate that a file path exists and is a file.
        
        Args:
            file_path: Path to validate
            
        Returns:
            True if path is valid and exists, False otherwise
        """
        path = Path(file_path)
        return path.exists() and path.is_file()

    def create_directory_if_not_exists(self, directory: str) -> None:
        """Create a directory if it doesn't exist.
        
        Args:
            directory: Path to the directory to create
        """
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)

    def get_file_size(self, file_path: str) -> int:
        """Get the size of a file in bytes.
        
        Args:
            file_path: Path to the file
            
        Returns:
            File size in bytes, or 0 if file doesn't exist
        """
        try:
            return os.path.getsize(file_path)
        except OSError:
            return 0
