"""UI tests for MainWindow - simulates real user interactions."""

import pytest
from pathlib import Path
from PIL import Image
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
def sample_image_file(tmp_path):
    """Create a sample image file for testing."""
    image_path = tmp_path / "test_image.jpg"
    img = Image.new('RGB', (800, 600), color='blue')
    img.save(image_path, 'JPEG')
    return str(image_path)


class TestMainWindowUI:
    """UI tests for MainWindow."""

    def test_window_opens(self, main_window):
        """Test that the main window opens correctly."""
        assert main_window.isVisible()
        assert main_window.windowTitle() == "PhotoEdit"

    def test_window_has_panels(self, main_window):
        """Test that all panels are present."""
        assert main_window.library_dock is not None
        assert main_window.tools_dock is not None
        assert main_window._image_view is not None

    def test_tools_panel_disabled_initially(self, main_window):
        """Test that tools panel is disabled until image is loaded."""
        tools_panel = main_window._tools_panel
        assert tools_panel._exposure_slider.isEnabled() is False
        assert tools_panel._contrast_slider.isEnabled() is False

    def test_toggle_library_panel(self, main_window, qtbot):
        """Test toggling library panel visibility."""
        initial_visible = main_window.library_dock.isVisible()
        
        # Simulate F5 keypress
        QTest.keyClick(main_window, Qt.Key.Key_F5)
        
        assert main_window.library_dock.isVisible() != initial_visible

    def test_toggle_tools_panel(self, main_window, qtbot):
        """Test toggling tools panel visibility."""
        initial_visible = main_window.tools_dock.isVisible()
        
        # Simulate F6 keypress
        QTest.keyClick(main_window, Qt.Key.Key_F6)
        
        assert main_window.tools_dock.isVisible() != initial_visible


class TestImageLoading:
    """UI tests for image loading functionality."""

    def test_load_image_enables_tools(self, main_window, sample_image_file, qtbot):
        """Test that loading an image enables the tools panel."""
        # Load image directly (simulating file dialog result)
        result = main_window._image_controller.load_image(sample_image_file)
        
        assert result is True
        
        # Wait for image_loaded signal processing
        qtbot.wait(100)
        
        # Tools should now be enabled
        tools_panel = main_window._tools_panel
        assert tools_panel._exposure_slider.isEnabled() is True

    def test_load_image_updates_title(self, main_window, sample_image_file, qtbot):
        """Test that loading an image updates the window title."""
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        
        assert "test_image.jpg" in main_window.windowTitle()

    def test_image_displayed_after_load(self, main_window, sample_image_file, qtbot):
        """Test that image is displayed after loading."""
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        
        assert main_window._image_view.has_image() is True


class TestSliderInteraction:
    """UI tests for slider interactions."""

    def test_exposure_slider_movement(self, main_window, sample_image_file, qtbot):
        """Test moving the exposure slider updates the value."""
        # Load image first
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        
        slider = main_window._tools_panel._exposure_slider
        
        # Get initial value
        initial_value = slider.get_value()
        
        # Simulate slider movement by setting value
        slider.set_value(2.0)
        
        assert slider.get_value() == 2.0
        assert slider.get_value() != initial_value

    def test_contrast_slider_movement(self, main_window, sample_image_file, qtbot):
        """Test moving the contrast slider."""
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        
        slider = main_window._tools_panel._contrast_slider
        slider.set_value(50.0)
        
        assert slider.get_value() == 50.0

    def test_slider_emits_signal(self, main_window, sample_image_file, qtbot):
        """Test that slider emits adjustments_changed signal."""
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        
        # Connect a signal spy
        with qtbot.waitSignal(main_window._tools_panel.adjustments_changed, timeout=1000):
            main_window._tools_panel._exposure_slider.set_value(1.0)

    def test_reset_all_resets_sliders(self, main_window, sample_image_file, qtbot):
        """Test that Reset All button resets all sliders."""
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        
        # Set some values
        main_window._tools_panel._exposure_slider.set_value(2.0)
        main_window._tools_panel._contrast_slider.set_value(50.0)
        
        # Click reset button
        QTest.mouseClick(
            main_window._tools_panel._reset_button,
            Qt.MouseButton.LeftButton
        )
        
        # Values should be reset to 0
        assert main_window._tools_panel._exposure_slider.get_value() == 0.0
        assert main_window._tools_panel._contrast_slider.get_value() == 0.0


class TestZoomControls:
    """UI tests for zoom functionality."""

    def test_zoom_in_keyboard(self, main_window, sample_image_file, qtbot):
        """Test zoom in with keyboard shortcut."""
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        
        initial_zoom = main_window._image_controller.get_zoom_factor()
        
        # Simulate Ctrl+= (zoom in)
        QTest.keyClick(
            main_window,
            Qt.Key.Key_Equal,
            Qt.KeyboardModifier.ControlModifier
        )
        
        new_zoom = main_window._image_controller.get_zoom_factor()
        assert new_zoom > initial_zoom

    def test_zoom_out_keyboard(self, main_window, sample_image_file, qtbot):
        """Test zoom out with keyboard shortcut."""
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        
        # First zoom in to have room to zoom out
        main_window._image_view.set_zoom_factor(2.0)
        
        # Simulate Ctrl+- (zoom out)
        QTest.keyClick(
            main_window,
            Qt.Key.Key_Minus,
            Qt.KeyboardModifier.ControlModifier
        )
        
        new_zoom = main_window._image_controller.get_zoom_factor()
        assert new_zoom < 2.0

    def test_view_100_percent(self, main_window, sample_image_file, qtbot):
        """Test 100% view with keyboard shortcut."""
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        
        # Set to different zoom
        main_window._image_view.set_zoom_factor(0.5)
        
        # Press '1' for 100%
        QTest.keyClick(main_window, Qt.Key.Key_1)
        
        assert main_window._image_controller.get_zoom_factor() == 1.0

    def test_fit_to_window(self, main_window, sample_image_file, qtbot):
        """Test fit to window with keyboard shortcut."""
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        
        # Press '0' for fit to window
        QTest.keyClick(main_window, Qt.Key.Key_0)
        
        # Zoom should be set (we can't predict exact value without knowing window size)
        # Just verify it doesn't crash and zoom is reasonable
        zoom = main_window._image_controller.get_zoom_factor()
        assert 0.05 <= zoom <= 10.0


class TestUndoRedo:
    """UI tests for undo/redo functionality."""

    def test_undo_keyboard_shortcut(self, main_window, sample_image_file, qtbot):
        """Test undo with Ctrl+Z."""
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        
        # Initially no undo available
        assert main_window._image_controller.can_undo() is False
        
        # Ctrl+Z should not crash when nothing to undo
        QTest.keyClick(
            main_window,
            Qt.Key.Key_Z,
            Qt.KeyboardModifier.ControlModifier
        )

    def test_reset_adjustments_keyboard(self, main_window, sample_image_file, qtbot):
        """Test reset with Ctrl+R."""
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        
        # Ctrl+R should reset without crashing
        QTest.keyClick(
            main_window,
            Qt.Key.Key_R,
            Qt.KeyboardModifier.ControlModifier
        )


class TestLibraryPanel:
    """UI tests for library panel."""

    def test_add_image_to_library(self, main_window, sample_image_file, qtbot):
        """Test adding an image to the library."""
        library = main_window._library_view
        
        library.add_image(sample_image_file)
        
        assert library.get_image_count() == 1

    def test_select_image_from_library(self, main_window, sample_image_file, qtbot):
        """Test selecting an image from library loads it."""
        library = main_window._library_view
        library.add_image(sample_image_file)
        
        # Emit selection signal
        library.image_selected.emit(sample_image_file)
        qtbot.wait(100)
        
        assert main_window._image_controller.has_image() is True

    def test_clear_library(self, main_window, sample_image_file, qtbot):
        """Test clearing the library."""
        library = main_window._library_view
        library.add_image(sample_image_file)
        
        library.clear()
        
        assert library.get_image_count() == 0
