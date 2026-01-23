"""Unit tests for ExportService."""

import pytest
from PIL import Image
from pathlib import Path
from src.services.export_service import ExportService


class TestExportService:
    """Test cases for ExportService class."""

    def test_service_initialization(self):
        """Test ExportService can be initialized."""
        service = ExportService()
        assert service is not None

    def test_export_jpeg(self, sample_image, tmp_path):
        """Test exporting as JPEG."""
        service = ExportService()
        output_path = str(tmp_path / "output.jpg")
        
        result = service.export_image(sample_image, output_path, format="JPEG")
        
        assert result is True
        assert Path(output_path).exists()

    def test_export_png(self, sample_image, tmp_path):
        """Test exporting as PNG."""
        service = ExportService()
        output_path = str(tmp_path / "output.png")
        
        result = service.export_image(sample_image, output_path, format="PNG")
        
        assert result is True
        assert Path(output_path).exists()

    def test_export_with_quality(self, sample_image, tmp_path):
        """Test exporting with quality setting."""
        service = ExportService()
        output_path = str(tmp_path / "output.jpg")
        
        result = service.export_image(sample_image, output_path, format="JPEG", quality=50)
        
        assert result is True
        assert Path(output_path).exists()

    def test_export_with_resize(self, sample_image, tmp_path):
        """Test exporting with resize."""
        service = ExportService()
        output_path = str(tmp_path / "output.jpg")
        
        result = service.export_image(
            sample_image,
            output_path,
            format="JPEG",
            resize=(50, 50)
        )
        
        assert result is True
        # Check the exported file size
        exported = Image.open(output_path)
        assert exported.size[0] <= 50
        assert exported.size[1] <= 50

    def test_export_with_resize_preserve_aspect(self, sample_image, tmp_path):
        """Test exporting with resize preserving aspect ratio."""
        service = ExportService()
        output_path = str(tmp_path / "output.jpg")
        
        result = service.export_image(
            sample_image,
            output_path,
            format="JPEG",
            resize=(50, 30),
            preserve_aspect=True
        )
        
        assert result is True
        exported = Image.open(output_path)
        # Should maintain aspect ratio
        assert exported.size[0] == exported.size[1]  # Original is square

    def test_export_invalid_path(self, sample_image):
        """Test exporting to invalid path."""
        service = ExportService()
        # Invalid path (non-existent directory)
        result = service.export_image(
            sample_image,
            "/nonexistent/directory/output.jpg",
            format="JPEG"
        )
        
        assert result is False

    def test_get_export_formats(self):
        """Test getting export formats."""
        service = ExportService()
        formats = service.get_export_formats()
        
        assert isinstance(formats, list)
        assert len(formats) > 0
        
        format_names = [f['name'] for f in formats]
        assert 'JPEG' in format_names
        assert 'PNG' in format_names

    def test_get_resize_presets(self):
        """Test getting resize presets."""
        service = ExportService()
        presets = service.get_resize_presets()
        
        assert isinstance(presets, list)
        assert len(presets) > 0
        
        preset_names = [p['name'] for p in presets]
        assert 'Original Size' in preset_names
        assert 'Full HD (1920x1080)' in preset_names

    def test_export_infer_format_from_extension(self, sample_image, tmp_path):
        """Test exporting with format inferred from extension."""
        service = ExportService()
        output_path = str(tmp_path / "output.png")
        
        # Don't specify format, should infer from .png extension
        result = service.export_image(sample_image, output_path)
        
        assert result is True
        exported = Image.open(output_path)
        assert exported.format == 'PNG'
