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


class TestSettingsServiceSync:
    """Sanity check for the explicit flush helper."""

    def test_sync_does_not_raise(self, service):
        service.sync()
