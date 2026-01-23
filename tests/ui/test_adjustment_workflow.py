"""UI tests for complete adjustment workflows."""

import pytest
from pathlib import Path
from PIL import Image
import numpy as np
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from src.views.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def main_window(qapp, qtbot):
    """Create a MainWindow instance for testing."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    yield window
    window.close()


@pytest.fixture
def gray_image_file(tmp_path):
    """Create a gray test image for verifying adjustments."""
    image_path = tmp_path / "gray_test.jpg"
    # Create a mid-gray image
    img = Image.new('RGB', (200, 200), color=(128, 128, 128))
    img.save(image_path, 'JPEG', quality=95)
    return str(image_path)


class TestCompleteAdjustmentWorkflow:
    """End-to-end tests for adjustment workflows."""

    def test_load_adjust_workflow(self, main_window, gray_image_file, qtbot):
        """Test complete workflow: load image, adjust, verify changes."""
        # Step 1: Load image
        result = main_window._image_controller.load_image(gray_image_file)
        assert result is True
        qtbot.wait(100)
        
        # Step 2: Verify tools are enabled
        assert main_window._tools_panel._exposure_slider.isEnabled() is True
        
        # Step 3: Make an adjustment
        main_window._tools_panel._brightness_slider.set_value(50.0)
        qtbot.wait(200)  # Wait for processing
        
        # Step 4: Verify image was modified
        current_image = main_window._image_controller.get_current_image()
        assert current_image is not None
        
        # Get pixel value - should be brighter than original
        pixel = current_image.getpixel((100, 100))
        # Original was (128, 128, 128), with +50 brightness should be brighter
        assert pixel[0] > 128  # R channel should be higher

    def test_multiple_adjustments_workflow(self, main_window, gray_image_file, qtbot):
        """Test applying multiple adjustments."""
        main_window._image_controller.load_image(gray_image_file)
        qtbot.wait(100)
        
        # Apply exposure adjustment
        main_window._tools_panel._exposure_slider.set_value(1.0)
        qtbot.wait(100)
        
        # Apply contrast
        main_window._tools_panel._contrast_slider.set_value(20.0)
        qtbot.wait(100)
        
        # Apply saturation
        main_window._tools_panel._saturation_slider.set_value(30.0)
        qtbot.wait(100)
        
        # Verify all adjustments are stored
        adjustments = main_window._tools_panel.get_adjustments()
        assert adjustments['exposure'] == 1.0
        assert adjustments['contrast'] == 20.0
        assert adjustments['saturation'] == 30.0

    def test_reset_workflow(self, main_window, gray_image_file, qtbot):
        """Test adjusting and then resetting."""
        main_window._image_controller.load_image(gray_image_file)
        qtbot.wait(100)
        
        # Make adjustments
        main_window._tools_panel._exposure_slider.set_value(2.0)
        main_window._tools_panel._contrast_slider.set_value(50.0)
        qtbot.wait(100)
        
        # Reset
        QTest.mouseClick(
            main_window._tools_panel._reset_button,
            Qt.MouseButton.LeftButton
        )
        qtbot.wait(100)
        
        # Verify all sliders are reset
        adjustments = main_window._tools_panel.get_adjustments()
        assert adjustments['exposure'] == 0.0
        assert adjustments['contrast'] == 0.0

    def test_slider_double_click_reset(self, main_window, gray_image_file, qtbot):
        """Test double-clicking slider resets it."""
        main_window._image_controller.load_image(gray_image_file)
        qtbot.wait(100)
        
        slider = main_window._tools_panel._exposure_slider
        slider.set_value(3.0)
        
        # Double-click to reset
        QTest.mouseDClick(slider, Qt.MouseButton.LeftButton)
        
        assert slider.get_value() == 0.0


class TestAdjustmentSignalFlow:
    """Tests for signal flow during adjustments."""

    def test_adjustment_triggers_processing(self, main_window, gray_image_file, qtbot):
        """Test that slider adjustment triggers image processing."""
        main_window._image_controller.load_image(gray_image_file)
        qtbot.wait(100)
        
        # Get original image
        original = main_window._image_controller.image_model.get_original_image()
        original_pixel = original.getpixel((100, 100))
        
        # Make significant adjustment
        main_window._tools_panel._brightness_slider.set_value(100.0)
        qtbot.wait(300)  # Wait for debounced processing
        
        # Check current image is different
        current = main_window._image_controller.get_current_image()
        current_pixel = current.getpixel((100, 100))
        
        # Pixels should be different (brighter)
        assert current_pixel != original_pixel

    def test_rapid_slider_movement(self, main_window, gray_image_file, qtbot):
        """Test rapid slider movements don't crash."""
        main_window._image_controller.load_image(gray_image_file)
        qtbot.wait(100)
        
        slider = main_window._tools_panel._exposure_slider
        
        # Simulate rapid slider movements
        for value in range(-50, 51, 5):
            slider.set_value(value / 10.0)  # -5.0 to 5.0
        
        qtbot.wait(200)  # Wait for processing
        
        # Should complete without crashing
        assert main_window._image_controller.has_image() is True


class TestPanelInteraction:
    """Tests for panel interactions."""

    def test_hide_show_tools_preserves_values(self, main_window, gray_image_file, qtbot):
        """Test hiding and showing tools panel preserves slider values."""
        main_window._image_controller.load_image(gray_image_file)
        qtbot.wait(100)
        
        # Set values
        main_window._tools_panel._exposure_slider.set_value(2.5)
        main_window._tools_panel._contrast_slider.set_value(30.0)
        
        # Hide panel
        QTest.keyClick(main_window, Qt.Key.Key_F6)
        qtbot.wait(50)
        
        # Show panel
        QTest.keyClick(main_window, Qt.Key.Key_F6)
        qtbot.wait(50)
        
        # Values should be preserved
        assert main_window._tools_panel._exposure_slider.get_value() == 2.5
        assert main_window._tools_panel._contrast_slider.get_value() == 30.0

    def test_zoom_status_bar_update(self, main_window, gray_image_file, qtbot):
        """Test that zoom updates the status bar."""
        main_window._image_controller.load_image(gray_image_file)
        qtbot.wait(100)
        
        # Set specific zoom
        main_window._image_view.set_zoom_factor(2.0)
        qtbot.wait(50)
        
        # Status bar should show 200%
        assert "200%" in main_window._zoom_label.text()
