"""Shared pytest fixtures for PhotoEdit tests."""

import pytest
from PIL import Image
from pathlib import Path

from src.services.library_catalog_service import LibraryCatalogService
from src.services.library_image_preview_cache_service import (
    LibraryImagePreviewCacheService,
)
from src.services.library_thumbnail_cache_service import LibraryThumbnailCacheService


@pytest.fixture
def sample_image():
    """Create a sample test image (RGB, 100x100, red)."""
    img = Image.new('RGB', (100, 100), color='red')
    return img


@pytest.fixture
def sample_image_path(tmp_path):
    """Create a temporary image file."""
    img = Image.new('RGB', (100, 100), color='blue')
    path = tmp_path / "test_image.jpg"
    img.save(path)
    return str(path)


@pytest.fixture
def sample_png_path(tmp_path):
    """Create a temporary PNG image file."""
    img = Image.new('RGB', (200, 200), color='green')
    path = tmp_path / "test_image.png"
    img.save(path)
    return str(path)


@pytest.fixture
def temp_dir(tmp_path):
    """Create a temporary directory for testing."""
    return tmp_path


@pytest.fixture
def library_catalog_path(tmp_path):
    """Per-test persistent catalog path."""
    return tmp_path / "appdata" / "library_catalog.json"


@pytest.fixture
def thumbnail_cache_dir(tmp_path):
    """Per-test thumbnail cache directory."""
    return tmp_path / "cache"


@pytest.fixture
def image_preview_cache_dir(tmp_path):
    """Per-test edited-preview cache directory."""
    return tmp_path / "preview-cache"


@pytest.fixture
def library_catalog_service(library_catalog_path):
    """Per-test library catalog service."""
    return LibraryCatalogService(catalog_path=library_catalog_path)


@pytest.fixture
def thumbnail_cache_service(thumbnail_cache_dir):
    """Per-test thumbnail cache service."""
    return LibraryThumbnailCacheService(cache_dir=thumbnail_cache_dir)


@pytest.fixture
def image_preview_cache_service(image_preview_cache_dir):
    """Per-test edited-preview cache service."""
    return LibraryImagePreviewCacheService(cache_dir=image_preview_cache_dir)
