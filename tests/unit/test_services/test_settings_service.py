"""Unit tests for SettingsService."""

from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings

from src.services.settings_service import SettingsService


@pytest.fixture
def isolated_settings(tmp_path):
    """Create a QSettings instance backed by a per-test INI file."""
    ini_path = tmp_path / "photoedit-test.ini"
    settings = QSettings(str(ini_path), QSettings.Format.IniFormat)
    yield settings
    settings.sync()


@pytest.fixture
def service(isolated_settings):
    """Provide a SettingsService bound to the isolated QSettings."""
    return SettingsService(isolated_settings)


class TestSettingsServiceDefaults:
    """First-launch behavior."""

    def test_default_last_open_dir_is_home(self, service):
        assert service.get_last_open_dir() == str(Path.home())

    def test_default_last_export_dir_is_home(self, service):
        assert service.get_last_export_dir() == str(Path.home())

    def test_default_window_geometry_is_none(self, service):
        assert service.get_window_geometry() is None

    def test_default_window_state_is_none(self, service):
        assert service.get_window_state() is None

    def test_default_current_image_path_is_none(self, service):
        assert service.get_current_image_path() is None


class TestSettingsServiceLastOpenDir:
    """Round-trips and edge cases for last_open_dir."""

    def test_set_and_get_directory(self, service, tmp_path):
        service.set_last_open_dir(str(tmp_path))
        assert service.get_last_open_dir() == str(tmp_path)

    def test_set_with_file_path_stores_parent(self, service, tmp_path):
        file_path = tmp_path / "image.jpg"
        file_path.touch()
        service.set_last_open_dir(str(file_path))
        assert service.get_last_open_dir() == str(tmp_path)

    def test_get_falls_back_to_home_when_stored_dir_missing(
        self, service, tmp_path, caplog
    ):
        # Create a real directory, store it, then delete it to simulate
        # a removable drive being unmounted between launches.
        ghost = tmp_path / "transient"
        ghost.mkdir()
        service.set_last_open_dir(str(ghost))
        ghost.rmdir()
        with caplog.at_level("INFO", logger="src.services.settings_service"):
            assert service.get_last_open_dir() == str(Path.home())
        assert any("falling back to home" in m for m in caplog.messages)

    def test_set_empty_path_is_noop(self, service):
        service.set_last_open_dir("")
        assert service.get_last_open_dir() == str(Path.home())


class TestSettingsServiceLastExportDir:
    """Mirror of the open-dir behavior, applied to export."""

    def test_set_and_get_directory(self, service, tmp_path):
        service.set_last_export_dir(str(tmp_path))
        assert service.get_last_export_dir() == str(tmp_path)

    def test_set_with_file_path_stores_parent(self, service, tmp_path):
        file_path = tmp_path / "out.png"
        file_path.touch()
        service.set_last_export_dir(str(file_path))
        assert service.get_last_export_dir() == str(tmp_path)

    def test_get_falls_back_to_home_when_stored_dir_missing(self, service, tmp_path):
        ghost = tmp_path / "transient-export"
        ghost.mkdir()
        service.set_last_export_dir(str(ghost))
        ghost.rmdir()
        assert service.get_last_export_dir() == str(Path.home())

    def test_open_and_export_keys_are_independent(self, service, tmp_path):
        opens = tmp_path / "opens"
        exports = tmp_path / "exports"
        opens.mkdir()
        exports.mkdir()
        service.set_last_open_dir(str(opens))
        service.set_last_export_dir(str(exports))
        assert service.get_last_open_dir() == str(opens)
        assert service.get_last_export_dir() == str(exports)


class TestSettingsServiceWindowGeometry:
    """Geometry blob round-trip."""

    def test_set_and_get_geometry(self, service):
        blob = b"\x01\x02\x03\x04geometry"
        service.set_window_geometry(blob)
        result = service.get_window_geometry()
        assert isinstance(result, bytes)
        assert result == blob

    def test_get_geometry_returns_none_when_absent(self, service):
        assert service.get_window_geometry() is None


class TestSettingsServiceWindowState:
    """Dock-state blob round-trip."""

    def test_set_and_get_window_state(self, service):
        blob = b"\x05\x06dock-state"
        service.set_window_state(blob)
        assert service.get_window_state() == blob


class TestSettingsServiceCurrentImagePath:
    """Current-image session path handling."""

    def test_set_and_get_current_image_path(self, service, tmp_path):
        image_path = tmp_path / "current.jpg"
        image_path.touch()
        service.set_current_image_path(str(image_path))
        assert service.get_current_image_path() == str(image_path)

    def test_missing_current_image_path_returns_none(self, service, tmp_path):
        image_path = tmp_path / "gone.jpg"
        image_path.touch()
        service.set_current_image_path(str(image_path))
        image_path.unlink()
        assert service.get_current_image_path() is None

    def test_set_current_image_path_none_clears_value(self, service, tmp_path):
        image_path = tmp_path / "clear.jpg"
        image_path.touch()
        service.set_current_image_path(str(image_path))
        service.set_current_image_path(None)
        assert service.get_current_image_path() is None


class TestSettingsServiceConfirmExportOverwrite:
    """Round-trip and default behavior for the overwrite-confirmation flag."""

    def test_default_is_true(self, service):
        assert service.get_confirm_export_overwrite() is True

    def test_set_false_round_trips_as_actual_bool(self, service):
        service.set_confirm_export_overwrite(False)
        result = service.get_confirm_export_overwrite()
        assert result is False

    def test_set_true_round_trips_as_actual_bool(self, service):
        service.set_confirm_export_overwrite(False)
        service.set_confirm_export_overwrite(True)
        result = service.get_confirm_export_overwrite()
        assert result is True


class TestSettingsServiceLastExportOptions:
    """Round-trip and corruption-recovery behavior for export options."""

    def test_default_is_none(self, service):
        assert service.get_last_export_options() is None

    def test_round_trips_full_options_dict(self, service):
        options = {
            "format": "JPEG",
            "quality": 85,
            "width": 1920,
            "height": 1080,
            "preserve_aspect": True,
        }
        service.set_last_export_options(options)
        assert service.get_last_export_options() == options

    def test_round_trips_none_width_and_height(self, service):
        options = {
            "format": "PNG",
            "quality": 95,
            "width": None,
            "height": None,
            "preserve_aspect": False,
        }
        service.set_last_export_options(options)
        assert service.get_last_export_options() == options

    def test_corrupt_stored_value_returns_none(self, service, isolated_settings):
        isolated_settings.setValue("export/last_options", "not-valid-json{{{")
        assert service.get_last_export_options() is None

    def test_empty_stored_value_returns_none(self, service, isolated_settings):
        isolated_settings.setValue("export/last_options", "")
        assert service.get_last_export_options() is None


class TestSettingsServiceSync:
    """Sanity check for the explicit flush helper."""

    def test_sync_does_not_raise(self, service):
        service.sync()
