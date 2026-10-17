"""UI tests for File > Export/Import Preset (Import presets subset slice).

See docs/planning/implementation-notes/2026-10-13-import-export-presets.md
for the scope boundary: single-file export/import of one user-authored
preset, reusing ImageController.get_adjustment_state()/
restore_adjustment_state() exactly as Copy/Paste Edit Settings and the
Profile selector already do. Not a browsable preset library, not
LUT-based.

Fixtures (qapp, main_window, sample_image_file) are provided by the
module-scoped/session conftest-equivalent fixtures already defined in
tests/ui/test_main_window.py's module; pytest only auto-shares fixtures
declared in conftest.py, so this file defines its own copies matching
that module's exact setup, following the same precedent other sibling
test files in tests/ui/ use (each UI test module is self-contained).
"""

import json

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from PIL import Image
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
from PyQt6.QtCore import QSettings

from src.services.library_catalog_service import LibraryCatalogService
from src.services.library_image_preview_cache_service import (
    LibraryImagePreviewCacheService,
)
from src.services.library_thumbnail_cache_service import LibraryThumbnailCacheService
from src.services.settings_service import SettingsService
from src.views.main_window import MainWindow, PRESET_FILE_VERSION


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
    img = Image.new("RGB", (800, 600), color="blue")
    img.save(image_path, "JPEG")
    return str(image_path)


class TestExportPreset:
    """MainWindow._export_preset."""

    def test_export_with_no_image_shows_message_and_no_dialog(self, main_window):
        main_window._image_controller.has_image = MagicMock(return_value=False)

        with patch.object(main_window._status_bar, "showMessage") as mock_status, \
                patch.object(QFileDialog, "getSaveFileName") as mock_dialog:
            main_window._export_preset()

        mock_dialog.assert_not_called()
        mock_status.assert_called_once_with(
            "No image to export a preset from", 2000
        )

    def test_export_with_image_writes_expected_envelope(
        self, main_window, sample_image_file, tmp_path, qtbot
    ):
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        main_window._tools_panel._exposure_slider.set_value(1.25)
        qtbot.wait(100)

        expected_adjustments = main_window._image_controller.get_adjustment_state()
        dest = tmp_path / "my_preset.json"

        with patch.object(
            QFileDialog, "getSaveFileName", return_value=(str(dest), "")
        ), patch.object(main_window._status_bar, "showMessage") as mock_status:
            main_window._export_preset()

        assert dest.exists()
        written = json.loads(dest.read_text(encoding="utf-8"))
        assert written["photoedit_preset_version"] == PRESET_FILE_VERSION
        assert written["name"] == "my_preset"
        assert written["adjustments"] == expected_adjustments
        mock_status.assert_called_once_with("Exported preset: my_preset", 2000)

    def test_export_adds_json_extension_when_missing(
        self, main_window, sample_image_file, tmp_path, qtbot
    ):
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        dest = tmp_path / "no_extension"

        with patch.object(
            QFileDialog, "getSaveFileName", return_value=(str(dest), "")
        ):
            main_window._export_preset()

        assert dest.with_suffix(".json").exists()

    def test_export_failure_shows_critical_and_does_not_crash(
        self, main_window, sample_image_file, tmp_path, qtbot
    ):
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        dest = tmp_path / "preset.json"

        with patch.object(
            QFileDialog, "getSaveFileName", return_value=(str(dest), "")
        ), patch(
            "src.views.main_window.Path.write_text",
            side_effect=OSError("disk full"),
        ), patch.object(QMessageBox, "critical") as mock_critical:
            main_window._export_preset()

        mock_critical.assert_called_once()


class TestImportPreset:
    """MainWindow._import_preset."""

    def test_import_with_no_image_shows_message_and_no_dialog(self, main_window):
        main_window._image_controller.has_image = MagicMock(return_value=False)

        with patch.object(main_window._status_bar, "showMessage") as mock_status, \
                patch.object(QFileDialog, "getOpenFileName") as mock_dialog:
            main_window._import_preset()

        mock_dialog.assert_not_called()
        mock_status.assert_called_once_with("No image to apply a preset to", 2000)

    def test_import_well_formed_preset_applies_adjustments(
        self, main_window, sample_image_file, tmp_path, qtbot
    ):
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)

        preset_file = tmp_path / "vivid_look.json"
        adjustments = {"exposure": 1.5, "contrast": 20.0, "saturation": 10.0}
        preset_file.write_text(
            json.dumps(
                {
                    "photoedit_preset_version": PRESET_FILE_VERSION,
                    "name": "Vivid Look",
                    "adjustments": adjustments,
                }
            ),
            encoding="utf-8",
        )

        main_window._tools_panel.set_adjustments = MagicMock(
            wraps=main_window._tools_panel.set_adjustments
        )
        main_window._image_controller.restore_adjustment_state = MagicMock()

        with patch.object(
            QFileDialog, "getOpenFileName", return_value=(str(preset_file), "")
        ), patch.object(main_window._status_bar, "showMessage") as mock_status:
            main_window._import_preset()

        main_window._tools_panel.set_adjustments.assert_called_once()
        tools_panel_args, tools_panel_kwargs = (
            main_window._tools_panel.set_adjustments.call_args
        )
        assert tools_panel_args[0] == adjustments
        assert tools_panel_args[0] is not adjustments
        assert tools_panel_kwargs == {"emit_signal": False}

        main_window._image_controller.restore_adjustment_state.assert_called_once()
        (controller_arg,), _ = (
            main_window._image_controller.restore_adjustment_state.call_args
        )
        assert controller_arg == adjustments
        assert controller_arg is not adjustments

        mock_status.assert_called_with("Imported preset: Vivid Look", 2000)

    def test_import_derives_name_from_filename_when_missing(
        self, main_window, sample_image_file, tmp_path, qtbot
    ):
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)

        preset_file = tmp_path / "my_look.json"
        preset_file.write_text(
            json.dumps(
                {
                    "photoedit_preset_version": PRESET_FILE_VERSION,
                    "adjustments": {"exposure": 0.5},
                }
            ),
            encoding="utf-8",
        )

        with patch.object(
            QFileDialog, "getOpenFileName", return_value=(str(preset_file), "")
        ), patch.object(main_window._status_bar, "showMessage") as mock_status:
            main_window._import_preset()

        mock_status.assert_called_with("Imported preset: my_look", 2000)

    def test_import_non_json_file_is_rejected_without_crash(
        self, main_window, sample_image_file, tmp_path, qtbot
    ):
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)

        bad_file = tmp_path / "garbage.json"
        bad_file.write_text("this is not { json", encoding="utf-8")

        main_window._image_controller.restore_adjustment_state = MagicMock()

        with patch.object(
            QFileDialog, "getOpenFileName", return_value=(str(bad_file), "")
        ), patch.object(QMessageBox, "warning") as mock_warning:
            main_window._import_preset()

        mock_warning.assert_called_once()
        main_window._image_controller.restore_adjustment_state.assert_not_called()

    def test_import_missing_adjustments_key_is_rejected(
        self, main_window, sample_image_file, tmp_path, qtbot
    ):
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)

        preset_file = tmp_path / "no_adjustments.json"
        preset_file.write_text(
            json.dumps({"photoedit_preset_version": PRESET_FILE_VERSION}),
            encoding="utf-8",
        )

        main_window._image_controller.restore_adjustment_state = MagicMock()

        with patch.object(
            QFileDialog, "getOpenFileName", return_value=(str(preset_file), "")
        ), patch.object(QMessageBox, "warning") as mock_warning:
            main_window._import_preset()

        mock_warning.assert_called_once()
        main_window._image_controller.restore_adjustment_state.assert_not_called()

    def test_import_wrong_version_is_rejected(
        self, main_window, sample_image_file, tmp_path, qtbot
    ):
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)

        preset_file = tmp_path / "future.json"
        preset_file.write_text(
            json.dumps(
                {
                    "photoedit_preset_version": PRESET_FILE_VERSION + 1,
                    "adjustments": {"exposure": 1.0},
                }
            ),
            encoding="utf-8",
        )

        main_window._image_controller.restore_adjustment_state = MagicMock()

        with patch.object(
            QFileDialog, "getOpenFileName", return_value=(str(preset_file), "")
        ), patch.object(QMessageBox, "warning") as mock_warning:
            main_window._import_preset()

        mock_warning.assert_called_once()
        main_window._image_controller.restore_adjustment_state.assert_not_called()

    def test_import_not_a_json_object_is_rejected(
        self, main_window, sample_image_file, tmp_path, qtbot
    ):
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)

        preset_file = tmp_path / "array.json"
        preset_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

        main_window._image_controller.restore_adjustment_state = MagicMock()

        with patch.object(
            QFileDialog, "getOpenFileName", return_value=(str(preset_file), "")
        ), patch.object(QMessageBox, "warning") as mock_warning:
            main_window._import_preset()

        mock_warning.assert_called_once()
        main_window._image_controller.restore_adjustment_state.assert_not_called()


class TestExportImportPresetRoundTrip:
    """A real export-then-import round trip through the filesystem."""

    def test_export_then_import_restores_same_adjustments(
        self, main_window, sample_image_file, tmp_path, qtbot
    ):
        main_window._image_controller.load_image(sample_image_file)
        qtbot.wait(100)
        main_window._tools_panel._exposure_slider.set_value(0.8)
        main_window._tools_panel._contrast_slider.set_value(30.0)
        qtbot.wait(100)

        exported_state = main_window._image_controller.get_adjustment_state()
        preset_file = tmp_path / "round_trip.json"

        with patch.object(
            QFileDialog, "getSaveFileName", return_value=(str(preset_file), "")
        ):
            main_window._export_preset()

        assert preset_file.exists()

        main_window._image_controller.restore_adjustment_state = MagicMock()

        with patch.object(
            QFileDialog, "getOpenFileName", return_value=(str(preset_file), "")
        ):
            main_window._import_preset()

        main_window._image_controller.restore_adjustment_state.assert_called_once()
        (restored_state,), _ = (
            main_window._image_controller.restore_adjustment_state.call_args
        )
        assert restored_state == exported_state
