"""UI tests for MainWindow - simulates real user interactions."""

import pytest
from pathlib import Path
from PIL import Image
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtTest import QTest

from src.services.library_catalog_service import LibraryCatalogService
from src.services.library_image_preview_cache_service import (
    LibraryImagePreviewCacheService,
)
from src.services.library_thumbnail_cache_service import LibraryThumbnailCacheService
from src.services.settings_service import SettingsService
from src.views.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def main_window(qapp, qtbot, tmp_path):
    """Create a MainWindow instance for testing."""
    settings = SettingsService(
        QSettings(str(tmp_path / "main-window.ini"), QSettings.Format.IniFormat)
    )
    catalog = LibraryCatalogService(catalog_path=tmp_path / "catalog.json")
    cache = LibraryThumbnailCacheService(cache_dir=tmp_path / "cache")
    preview_cache = LibraryImagePreviewCacheService(
        cache_dir=tmp_path / "preview-cache"
    )
    window = MainWindow(
        settings_service=settings,
        catalog_service=catalog,
        thumbnail_cache_service=cache,
        image_preview_cache_service=preview_cache,
    )
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

    def test_default_library_exists(self, main_window):
        assert main_window._library_view.get_library_count() == 1
        assert main_window._library_view.is_library_section_expanded() is True

    def test_add_image_to_library(self, main_window, sample_image_file, qtbot):
        """Test adding an image to the library."""
        main_window._library_controller.add_image(sample_image_file)

        assert main_window._library_view.get_image_count() == 1

    def test_select_image_from_library(self, main_window, sample_image_file, qtbot):
        """Test selecting an image from library loads it."""
        main_window._library_controller.add_image(sample_image_file)
        library = main_window._library_view

        # Emit selection signal
        with qtbot.waitSignal(
            main_window._image_controller.image_load_finished,
            timeout=3000,
        ):
            library.image_selected.emit(sample_image_file)

        assert main_window._image_controller.has_image() is True

    def test_switching_between_images_restores_saved_adjustments(
        self, main_window, sample_image_file, tmp_path, qtbot
    ):
        other = tmp_path / "other.jpg"
        Image.new("RGB", (80, 60), color="green").save(other)

        main_window._library_controller.import_images([sample_image_file, str(other)])
        library = main_window._library_view

        with qtbot.waitSignal(
            main_window._image_controller.image_load_finished,
            timeout=3000,
        ):
            library.image_selected.emit(sample_image_file)
        main_window._tools_panel._exposure_slider.set_value(1.25)
        first_exposure = main_window._tools_panel._exposure_slider.get_value()
        qtbot.wait(500)

        with qtbot.waitSignal(
            main_window._image_controller.image_load_finished,
            timeout=3000,
        ):
            library.image_selected.emit(str(other))
        main_window._tools_panel._contrast_slider.set_value(30.0)
        qtbot.wait(500)

        with qtbot.waitSignal(
            main_window._image_controller.image_load_finished,
            timeout=3000,
        ):
            library.image_selected.emit(sample_image_file)
        qtbot.waitUntil(
            lambda: main_window._tools_panel.get_adjustments()["exposure"] == first_exposure,
            timeout=3000,
        )
        assert main_window._tools_panel.get_adjustments()["contrast"] == 0.0

        with qtbot.waitSignal(
            main_window._image_controller.image_load_finished,
            timeout=3000,
        ):
            library.image_selected.emit(str(other))
        qtbot.waitUntil(
            lambda: main_window._tools_panel.get_adjustments()["contrast"] == 30.0,
            timeout=3000,
        )
        assert main_window._tools_panel.get_adjustments()["exposure"] == 0.0

    def test_clear_library(self, main_window, sample_image_file, qtbot):
        """Test clearing the library."""
        main_window._library_controller.add_image(sample_image_file)

        main_window._library_controller.clear_current_library()

        assert main_window._library_view.get_image_count() == 0

    def test_switching_libraries_updates_grid(self, main_window, sample_image_file, tmp_path):
        other = tmp_path / "other.jpg"
        Image.new("RGB", (40, 40), color="green").save(other)

        library = main_window._library_view
        controller = main_window._library_controller
        current_id = controller.current_library_id
        controller.create_library("Travel")
        second_id = controller.current_library_id
        controller.select_library(current_id)
        controller.import_images([sample_image_file])
        controller.select_library(second_id)
        controller.import_images([str(other)])

        assert library.get_image_count() == 1
        current_grid = library._grid_by_library_id[second_id]
        assert current_grid.item(0).data(Qt.ItemDataRole.UserRole) == str(other)

    def test_startup_restores_selected_library(self, qapp, qtbot, tmp_path, sample_image_file):
        settings = SettingsService(
            QSettings(str(tmp_path / "persist.ini"), QSettings.Format.IniFormat)
        )
        catalog = LibraryCatalogService(catalog_path=tmp_path / "catalog.json")
        cache = LibraryThumbnailCacheService(cache_dir=tmp_path / "cache")
        second = catalog.create_library("Travel")
        catalog.add_entries(second.id, [sample_image_file])
        catalog.set_current_library(second.id)

        first = MainWindow(
            settings_service=settings,
            catalog_service=catalog,
            thumbnail_cache_service=cache,
            image_preview_cache_service=LibraryImagePreviewCacheService(
                cache_dir=tmp_path / "preview-cache"
            ),
        )
        qtbot.addWidget(first)
        first.show()
        qtbot.waitExposed(first)
        first.close()

        reopened = MainWindow(
            settings_service=SettingsService(
                QSettings(str(tmp_path / "persist.ini"), QSettings.Format.IniFormat)
            ),
            catalog_service=LibraryCatalogService(catalog_path=tmp_path / "catalog.json"),
            thumbnail_cache_service=LibraryThumbnailCacheService(cache_dir=tmp_path / "cache"),
            image_preview_cache_service=LibraryImagePreviewCacheService(
                cache_dir=tmp_path / "preview-cache"
            ),
        )
        qtbot.addWidget(reopened)
        reopened.show()
        qtbot.waitExposed(reopened)

        assert reopened._library_view.get_current_library_id() == second.id
        assert reopened._library_view.get_image_count() == 1
        reopened.close()

    def test_library_section_can_be_collapsed(self, main_window):
        main_window._library_view.set_library_section_expanded(False)
        assert main_window._library_view.is_library_section_expanded() is False

    def test_same_library_header_can_toggle_closed(self, main_window):
        current_id = main_window._library_view.get_current_library_id()
        main_window._library_view._library_sections[current_id].set_expanded(False)
        assert main_window._library_view.is_library_section_expanded() is False

    def test_switching_libraries_persists_current_image_adjustments(
        self, main_window, sample_image_file, tmp_path, qtbot
    ):
        other = tmp_path / "travel.jpg"
        Image.new("RGB", (80, 60), color="red").save(other)

        controller = main_window._library_controller
        first_id = controller.current_library_id
        second = controller._catalog_service.create_library("Travel")
        second_id = second.id
        controller.select_library(first_id)
        controller.import_images([sample_image_file])
        controller.select_library(second_id)
        controller.import_images([str(other)])
        controller.select_library(first_id)

        with qtbot.waitSignal(
            main_window._image_controller.image_load_finished,
            timeout=3000,
        ):
            main_window._library_view.image_selected.emit(sample_image_file)
        main_window._tools_panel._saturation_slider.set_value(22.0)
        qtbot.wait(500)

        with qtbot.waitSignal(main_window._library_controller.entries_rebuilt, timeout=1000):
            main_window._library_view.library_selected.emit(second_id)

        with qtbot.waitSignal(
            main_window._image_controller.image_load_finished,
            timeout=3000,
        ):
            main_window._library_view.image_selected.emit(str(other))

        with qtbot.waitSignal(main_window._library_controller.entries_rebuilt, timeout=1000):
            main_window._library_view.library_selected.emit(first_id)

        with qtbot.waitSignal(
            main_window._image_controller.image_load_finished,
            timeout=3000,
        ):
            main_window._library_view.image_selected.emit(sample_image_file)

        qtbot.waitUntil(
            lambda: main_window._tools_panel.get_adjustments()["saturation"] == 22.0,
            timeout=3000,
        )


class TestMainWindowSettingsPersistence:
    """Window-geometry round-trip via SettingsService."""

    def test_close_persists_window_geometry(self, qapp, qtbot, tmp_path):
        ini_path = tmp_path / "main-window.ini"
        settings = SettingsService(
            QSettings(str(ini_path), QSettings.Format.IniFormat)
        )
        assert settings.get_window_geometry() is None

        window = MainWindow(
            settings_service=settings,
            catalog_service=LibraryCatalogService(catalog_path=tmp_path / "catalog.json"),
            thumbnail_cache_service=LibraryThumbnailCacheService(
                cache_dir=tmp_path / "cache"
            ),
            image_preview_cache_service=LibraryImagePreviewCacheService(
                cache_dir=tmp_path / "preview-cache"
            ),
        )
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        window.resize(1300, 850)
        qtbot.wait(20)
        window.close()

        blob = settings.get_window_geometry()
        assert blob is not None
        assert isinstance(blob, bytes) and len(blob) > 0

    def test_geometry_is_restored_on_next_launch(self, qapp, qtbot, tmp_path):
        ini_path = tmp_path / "main-window-restore.ini"
        first = MainWindow(
            settings_service=SettingsService(
                QSettings(str(ini_path), QSettings.Format.IniFormat)
            ),
            catalog_service=LibraryCatalogService(catalog_path=tmp_path / "catalog.json"),
            thumbnail_cache_service=LibraryThumbnailCacheService(
                cache_dir=tmp_path / "cache"
            ),
            image_preview_cache_service=LibraryImagePreviewCacheService(
                cache_dir=tmp_path / "preview-cache"
            ),
        )
        qtbot.addWidget(first)
        first.show()
        qtbot.waitExposed(first)
        first.resize(1320, 870)
        qtbot.wait(20)
        first.close()

        second = MainWindow(
            settings_service=SettingsService(
                QSettings(str(ini_path), QSettings.Format.IniFormat)
            ),
            catalog_service=LibraryCatalogService(catalog_path=tmp_path / "catalog.json"),
            thumbnail_cache_service=LibraryThumbnailCacheService(
                cache_dir=tmp_path / "cache"
            ),
            image_preview_cache_service=LibraryImagePreviewCacheService(
                cache_dir=tmp_path / "preview-cache"
            ),
        )
        qtbot.addWidget(second)
        second.show()
        qtbot.waitExposed(second)
        # Allow the window manager to apply the restored geometry.
        qtbot.wait(50)
        assert second.size().width() == 1320
        assert second.size().height() == 870
        second.close()

    def test_dock_state_is_restored_on_next_launch(self, qapp, qtbot, tmp_path):
        ini_path = tmp_path / "main-window-docks.ini"
        first = MainWindow(
            settings_service=SettingsService(
                QSettings(str(ini_path), QSettings.Format.IniFormat)
            ),
            catalog_service=LibraryCatalogService(catalog_path=tmp_path / "catalog.json"),
            thumbnail_cache_service=LibraryThumbnailCacheService(
                cache_dir=tmp_path / "cache"
            ),
            image_preview_cache_service=LibraryImagePreviewCacheService(
                cache_dir=tmp_path / "preview-cache"
            ),
        )
        qtbot.addWidget(first)
        first.show()
        qtbot.waitExposed(first)
        first.resize(1320, 870)
        first.resizeDocks(
            [first.library_dock, first.tools_dock],
            [360, 420],
            Qt.Orientation.Horizontal,
        )
        first.tools_dock.hide()
        qtbot.wait(50)
        first.close()

        second = MainWindow(
            settings_service=SettingsService(
                QSettings(str(ini_path), QSettings.Format.IniFormat)
            ),
            catalog_service=LibraryCatalogService(catalog_path=tmp_path / "catalog.json"),
            thumbnail_cache_service=LibraryThumbnailCacheService(
                cache_dir=tmp_path / "cache"
            ),
            image_preview_cache_service=LibraryImagePreviewCacheService(
                cache_dir=tmp_path / "preview-cache"
            ),
        )
        qtbot.addWidget(second)
        second.show()
        qtbot.waitExposed(second)
        qtbot.wait(50)
        assert second.tools_dock.isVisible() is False
        assert second.library_dock.width() >= 320
        second.close()

    def test_last_image_reopens_with_saved_adjustments(
        self, qapp, qtbot, tmp_path, sample_image_file
    ):
        ini_path = tmp_path / "main-window-session.ini"
        settings = SettingsService(
            QSettings(str(ini_path), QSettings.Format.IniFormat)
        )
        catalog = LibraryCatalogService(catalog_path=tmp_path / "catalog.json")
        cache = LibraryThumbnailCacheService(cache_dir=tmp_path / "cache")

        first = MainWindow(
            settings_service=settings,
            catalog_service=catalog,
            thumbnail_cache_service=cache,
            image_preview_cache_service=LibraryImagePreviewCacheService(
                cache_dir=tmp_path / "preview-cache"
            ),
        )
        qtbot.addWidget(first)
        first.show()
        qtbot.waitExposed(first)
        first._library_controller.add_image(sample_image_file)

        with qtbot.waitSignal(
            first._image_controller.image_load_finished,
            timeout=3000,
        ):
            first._library_view.image_selected.emit(sample_image_file)

        first._tools_panel._exposure_slider.set_value(1.5)
        first._tools_panel._contrast_slider.set_value(25.0)
        qtbot.wait(500)
        first.close()

        reopened = MainWindow(
            settings_service=SettingsService(
                QSettings(str(ini_path), QSettings.Format.IniFormat)
            ),
            catalog_service=LibraryCatalogService(catalog_path=tmp_path / "catalog.json"),
            thumbnail_cache_service=LibraryThumbnailCacheService(cache_dir=tmp_path / "cache"),
            image_preview_cache_service=LibraryImagePreviewCacheService(
                cache_dir=tmp_path / "preview-cache"
            ),
        )
        qtbot.addWidget(reopened)
        reopened.show()
        qtbot.waitExposed(reopened)
        qtbot.waitUntil(lambda: reopened._image_controller.has_image(), timeout=3000)
        qtbot.waitUntil(
            lambda: reopened._tools_panel.get_adjustments()["exposure"] == 1.5,
            timeout=3000,
        )
        assert reopened._tools_panel.get_adjustments()["contrast"] == 25.0
        reopened.close()
