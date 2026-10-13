"""Unit tests for ExportDialog's overwrite-confirmation behavior."""

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QMessageBox

from src.services.settings_service import SettingsService
from src.views.export_dialog import ExportDialog, confirm_overwrite_if_needed


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


@pytest.fixture
def sample_image():
    return Image.new('RGB', (10, 10), color='red')


def _make_dialog(qapp, image, path, settings_service=None):
    dialog = ExportDialog(image, default_path=path, settings_service=settings_service)
    dialog._path_edit.setText(path)
    return dialog


class TestExportDialogOverwriteConfirmationSkipped:
    """Cases where no confirmation dialog should appear."""

    def test_skipped_when_path_does_not_exist(self, qapp, sample_image, tmp_path, settings_service):
        path = str(tmp_path / "does-not-exist.jpg")
        dialog = _make_dialog(qapp, sample_image, path, settings_service)

        with patch('src.views.export_dialog.QMessageBox') as mock_box, \
                patch.object(dialog._export_service, 'export_image', return_value=True) as mock_export:
            dialog._do_export()

        mock_export.assert_called_once()
        # No Question-style confirmation box should have been constructed.
        mock_box.assert_not_called()

    def test_skipped_when_setting_is_false_even_if_path_exists(
        self, qapp, sample_image, tmp_path, settings_service
    ):
        path = tmp_path / "existing.jpg"
        path.write_bytes(b"fake")
        settings_service.set_confirm_export_overwrite(False)
        dialog = _make_dialog(qapp, sample_image, str(path), settings_service)

        with patch('src.views.export_dialog.QMessageBox') as mock_box, \
                patch.object(dialog._export_service, 'export_image', return_value=True) as mock_export:
            dialog._do_export()

        mock_export.assert_called_once()
        mock_box.assert_not_called()

    def test_skipped_when_settings_service_is_none(self, qapp, sample_image, tmp_path):
        path = tmp_path / "existing.jpg"
        path.write_bytes(b"fake")
        dialog = _make_dialog(qapp, sample_image, str(path), settings_service=None)

        with patch('src.views.export_dialog.QMessageBox') as mock_box, \
                patch.object(dialog._export_service, 'export_image', return_value=True) as mock_export:
            dialog._do_export()

        mock_export.assert_called_once()
        mock_box.assert_not_called()


class TestExportDialogOverwriteConfirmationShown:
    """Cases where the confirmation dialog should appear and gate the export."""

    def _patched_msgbox(self, mock_qmessagebox_cls, clicked_checkbox, exec_result):
        """Configure the mocked QMessageBox class to behave like a real
        QMessageBox(parent) instance whose exec() returns exec_result and
        whose checkbox reports clicked_checkbox.isChecked()."""
        instance = MagicMock()
        instance.exec.return_value = exec_result
        checkbox_instance = MagicMock()
        checkbox_instance.isChecked.return_value = clicked_checkbox
        mock_qmessagebox_cls.return_value = instance
        mock_qmessagebox_cls.Icon.Question = QMessageBox.Icon.Question
        mock_qmessagebox_cls.StandardButton.Yes = QMessageBox.StandardButton.Yes
        mock_qmessagebox_cls.StandardButton.No = QMessageBox.StandardButton.No
        return instance, checkbox_instance

    def test_shown_when_path_exists_and_setting_true_default(
        self, qapp, sample_image, tmp_path, settings_service
    ):
        path = tmp_path / "existing.jpg"
        path.write_bytes(b"fake")
        dialog = _make_dialog(qapp, sample_image, str(path), settings_service)

        with patch('src.views.export_dialog.QMessageBox') as mock_box_cls, \
                patch('src.views.export_dialog.QCheckBox') as mock_checkbox_cls, \
                patch.object(dialog._export_service, 'export_image', return_value=True) as mock_export:
            instance, checkbox_instance = self._patched_msgbox(
                mock_box_cls, clicked_checkbox=False,
                exec_result=QMessageBox.StandardButton.Yes,
            )
            mock_checkbox_cls.return_value = checkbox_instance
            dialog._do_export()

        instance.exec.assert_called_once()
        mock_export.assert_called_once()

    def test_no_aborts_export_and_leaves_dialog_open(
        self, qapp, sample_image, tmp_path, settings_service
    ):
        path = tmp_path / "existing.jpg"
        path.write_bytes(b"fake")
        dialog = _make_dialog(qapp, sample_image, str(path), settings_service)

        with patch('src.views.export_dialog.QMessageBox') as mock_box_cls, \
                patch('src.views.export_dialog.QCheckBox') as mock_checkbox_cls, \
                patch.object(dialog, 'accept') as mock_accept, \
                patch.object(dialog, 'reject') as mock_reject, \
                patch.object(dialog._export_service, 'export_image', return_value=True) as mock_export:
            instance, checkbox_instance = self._patched_msgbox(
                mock_box_cls, clicked_checkbox=False,
                exec_result=QMessageBox.StandardButton.No,
            )
            mock_checkbox_cls.return_value = checkbox_instance
            dialog._do_export()

        mock_export.assert_not_called()
        mock_accept.assert_not_called()
        mock_reject.assert_not_called()

    def test_yes_with_checkbox_checked_persists_preference(
        self, qapp, sample_image, tmp_path, settings_service
    ):
        path = tmp_path / "existing.jpg"
        path.write_bytes(b"fake")
        dialog = _make_dialog(qapp, sample_image, str(path), settings_service)

        with patch('src.views.export_dialog.QMessageBox') as mock_box_cls, \
                patch('src.views.export_dialog.QCheckBox') as mock_checkbox_cls, \
                patch.object(settings_service, 'set_confirm_export_overwrite') as mock_setter, \
                patch.object(dialog._export_service, 'export_image', return_value=True) as mock_export:
            instance, checkbox_instance = self._patched_msgbox(
                mock_box_cls, clicked_checkbox=True,
                exec_result=QMessageBox.StandardButton.Yes,
            )
            mock_checkbox_cls.return_value = checkbox_instance
            dialog._do_export()

        mock_setter.assert_called_once_with(False)
        mock_export.assert_called_once()

    def test_yes_with_checkbox_unchecked_does_not_persist(
        self, qapp, sample_image, tmp_path, settings_service
    ):
        path = tmp_path / "existing.jpg"
        path.write_bytes(b"fake")
        dialog = _make_dialog(qapp, sample_image, str(path), settings_service)

        with patch('src.views.export_dialog.QMessageBox') as mock_box_cls, \
                patch('src.views.export_dialog.QCheckBox') as mock_checkbox_cls, \
                patch.object(settings_service, 'set_confirm_export_overwrite') as mock_setter, \
                patch.object(dialog._export_service, 'export_image', return_value=True) as mock_export:
            instance, checkbox_instance = self._patched_msgbox(
                mock_box_cls, clicked_checkbox=False,
                exec_result=QMessageBox.StandardButton.Yes,
            )
            mock_checkbox_cls.return_value = checkbox_instance
            dialog._do_export()

        mock_setter.assert_not_called()
        mock_export.assert_called_once()


class TestExportDialogConfirmOverwriteIsNeededStandalone:
    """The extracted module-level function behaves the same as before."""

    def test_returns_true_when_settings_service_is_none(self, tmp_path):
        path = tmp_path / "existing.jpg"
        path.write_bytes(b"fake")
        assert confirm_overwrite_if_needed(None, str(path), None) is True

    def test_returns_true_when_path_does_not_exist(self, settings_service, tmp_path):
        path = tmp_path / "missing.jpg"
        assert confirm_overwrite_if_needed(None, str(path), settings_service) is True

    def test_returns_true_when_preference_is_false(self, settings_service, tmp_path):
        path = tmp_path / "existing.jpg"
        path.write_bytes(b"fake")
        settings_service.set_confirm_export_overwrite(False)
        assert confirm_overwrite_if_needed(None, str(path), settings_service) is True


class TestExportDialogPersistsLastExportOptions:
    """A successful export persists the exact options dict shape."""

    def test_persists_options_without_resize(
        self, qapp, sample_image, tmp_path, settings_service
    ):
        path = str(tmp_path / "out.jpg")
        dialog = _make_dialog(qapp, sample_image, path, settings_service)

        with patch.object(dialog._export_service, 'export_image', return_value=True), \
                patch('src.views.export_dialog.QMessageBox'):
            dialog._do_export()

        options = settings_service.get_last_export_options()
        assert options == {
            "format": "JPEG",
            "quality": 95,
            "width": None,
            "height": None,
            "preserve_aspect": True,
        }

    def test_persists_options_with_resize(
        self, qapp, sample_image, tmp_path, settings_service
    ):
        path = str(tmp_path / "out.jpg")
        dialog = _make_dialog(qapp, sample_image, path, settings_service)
        dialog._width_spin.setValue(5)
        dialog._height_spin.setValue(5)
        dialog._preserve_aspect.setChecked(False)
        dialog._quality_slider.setValue(50)

        with patch.object(dialog._export_service, 'export_image', return_value=True), \
                patch('src.views.export_dialog.QMessageBox'):
            dialog._do_export()

        options = settings_service.get_last_export_options()
        assert options == {
            "format": "JPEG",
            "quality": 50,
            "width": 5,
            "height": 5,
            "preserve_aspect": False,
        }

    def test_does_not_persist_on_failed_export(
        self, qapp, sample_image, tmp_path, settings_service
    ):
        path = str(tmp_path / "out.jpg")
        dialog = _make_dialog(qapp, sample_image, path, settings_service)

        with patch.object(dialog._export_service, 'export_image', return_value=False), \
                patch('src.views.export_dialog.QMessageBox'):
            dialog._do_export()

        assert settings_service.get_last_export_options() is None


class TestExportDialogPrePopulatesFromLastExportOptions:
    """Dialog construction reads previously-stored options into widgets."""

    def test_prepopulates_widgets_when_options_exist(
        self, qapp, sample_image, tmp_path, settings_service
    ):
        settings_service.set_last_export_options({
            "format": "PNG",
            "quality": 42,
            "width": 123,
            "height": 456,
            "preserve_aspect": False,
        })
        dialog = ExportDialog(
            sample_image, default_path="", settings_service=settings_service
        )

        assert dialog._format_combo.currentData()['name'] == "PNG"
        assert dialog._quality_slider.value() == 42
        assert dialog._width_spin.value() == 123
        assert dialog._height_spin.value() == 456
        assert dialog._preserve_aspect.isChecked() is False

    def test_leaves_defaults_when_no_options_exist(
        self, qapp, sample_image, settings_service
    ):
        dialog = ExportDialog(
            sample_image, default_path="", settings_service=settings_service
        )

        assert dialog._format_combo.currentData()['name'] == "JPEG"
        assert dialog._quality_slider.value() == 95
        assert dialog._width_spin.value() == sample_image.width
        assert dialog._height_spin.value() == sample_image.height
        assert dialog._preserve_aspect.isChecked() is True

    def test_leaves_defaults_when_settings_service_is_none(self, qapp, sample_image):
        dialog = ExportDialog(sample_image, default_path="", settings_service=None)

        assert dialog._format_combo.currentData()['name'] == "JPEG"
        assert dialog._quality_slider.value() == 95
