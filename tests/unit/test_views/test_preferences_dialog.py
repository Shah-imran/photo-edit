"""Unit tests for PreferencesDialog."""

import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QDialog

from src.processing.proxy_manager import ProxyManager
from src.services.settings_service import SettingsService
from src.views.preferences_dialog import PreferencesDialog


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication for Qt tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def isolated_settings(tmp_path):
    """Create a QSettings instance backed by a per-test INI file."""
    ini_path = tmp_path / "photoedit-test.ini"
    settings = QSettings(str(ini_path), QSettings.Format.IniFormat)
    yield settings
    settings.sync()


@pytest.fixture
def settings_service(isolated_settings):
    """Provide a SettingsService bound to the isolated QSettings."""
    return SettingsService(isolated_settings)


class TestPreferencesDialogInitialization:
    """Widgets should reflect stored preferences, or sane defaults."""

    def test_shows_proxy_manager_defaults_when_nothing_stored(
        self, qapp, settings_service
    ):
        dialog = PreferencesDialog(settings_service=settings_service)
        assert dialog._proxy_size_spin.value() == ProxyManager.DEFAULT_PROXY_SIZE
        assert (
            dialog._interactive_proxy_size_spin.value()
            == ProxyManager.DEFAULT_INTERACTIVE_PROXY_SIZE
        )

    def test_default_confirm_overwrite_checkbox_is_checked(
        self, qapp, settings_service
    ):
        dialog = PreferencesDialog(settings_service=settings_service)
        assert dialog._confirm_overwrite_checkbox.isChecked() is True

    def test_initializes_from_existing_stored_preferences(
        self, qapp, settings_service
    ):
        settings_service.set_confirm_export_overwrite(False)
        settings_service.set_proxy_max_size(2200)
        settings_service.set_interactive_proxy_max_size(900)

        dialog = PreferencesDialog(settings_service=settings_service)

        assert dialog._confirm_overwrite_checkbox.isChecked() is False
        assert dialog._proxy_size_spin.value() == 2200
        assert dialog._interactive_proxy_size_spin.value() == 900

    def test_does_not_crash_with_no_settings_service(self, qapp):
        dialog = PreferencesDialog(settings_service=None)
        assert dialog._proxy_size_spin.value() == ProxyManager.DEFAULT_PROXY_SIZE
        assert dialog._confirm_overwrite_checkbox.isChecked() is True


class TestPreferencesDialogAccept:
    """Accept persists all three values."""

    def test_accept_persists_all_values(self, qapp, settings_service):
        dialog = PreferencesDialog(settings_service=settings_service)
        dialog._confirm_overwrite_checkbox.setChecked(False)
        dialog._proxy_size_spin.setValue(1800)
        dialog._interactive_proxy_size_spin.setValue(700)

        dialog._on_accept()

        assert settings_service.get_confirm_export_overwrite() is False
        assert settings_service.get_proxy_max_size() == 1800
        assert settings_service.get_interactive_proxy_max_size() == 700

    def test_accept_with_no_settings_service_does_not_crash(self, qapp):
        dialog = PreferencesDialog(settings_service=None)
        dialog._proxy_size_spin.setValue(1800)
        # Should not raise even though there is nothing to persist to.
        dialog._on_accept()
        assert dialog.result() == QDialog.DialogCode.Accepted


class TestPreferencesDialogCancel:
    """Cancel must not persist any change."""

    def test_cancel_does_not_persist_changes(self, qapp, settings_service):
        dialog = PreferencesDialog(settings_service=settings_service)
        dialog._confirm_overwrite_checkbox.setChecked(False)
        dialog._proxy_size_spin.setValue(1800)
        dialog._interactive_proxy_size_spin.setValue(700)

        dialog.reject()

        assert settings_service.get_confirm_export_overwrite() is True
        assert settings_service.get_proxy_max_size() is None
        assert settings_service.get_interactive_proxy_max_size() is None
