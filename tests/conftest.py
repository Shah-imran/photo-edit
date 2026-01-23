"""Shared pytest fixtures for PhotoEdit tests."""

import pytest
from PIL import Image
from pathlib import Path
import tempfile
import os


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
