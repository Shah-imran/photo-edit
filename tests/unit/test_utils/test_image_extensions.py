"""Tests for src.utils.image_extensions."""

from pathlib import Path

from src.utils.image_extensions import (
    RAW_IMAGE_EXTENSIONS,
    is_raw_path,
    open_image_file_dialog_filter,
)


class TestIsRawPath:
    def test_common_raw_extensions(self):
        assert is_raw_path("/folder/image.NEF") is True
        assert is_raw_path(Path("x.cr3")) is True
        assert is_raw_path("photo.dng") is True

    def test_standard_images_false(self):
        assert is_raw_path("a.jpg") is False
        assert is_raw_path("b.PNG") is False


class TestOpenDialogFilter:
    def test_contains_jpeg_and_raw_globs(self):
        filt = open_image_file_dialog_filter()
        assert "*.jpg" in filt
        assert "*.nef" in filt or "*.cr2" in filt
        assert ";;All Files (*)" in filt


class TestRawExtensionSetNonEmpty:
    def test_raw_set_covers_major_brands(self):
        assert ".nef" in RAW_IMAGE_EXTENSIONS
        assert ".cr2" in RAW_IMAGE_EXTENSIONS
        assert ".arw" in RAW_IMAGE_EXTENSIONS
        assert ".dng" in RAW_IMAGE_EXTENSIONS
