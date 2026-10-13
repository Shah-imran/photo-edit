"""Export dialog for saving images."""

from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QSlider,
    QSpinBox,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QFormLayout,
    QMessageBox
)
from PyQt6.QtCore import Qt
from PIL import Image

from src.services.export_service import ExportService
from src.services.settings_service import SettingsService


def confirm_overwrite_if_needed(
    parent, path: str, settings_service: Optional[SettingsService]
) -> bool:
    """Ask before overwriting an existing export file, if required.

    Standalone module-level version of the logic ``ExportDialog`` uses
    internally, so other callers (e.g. ``MainWindow``'s "Export with
    Previous" action) can reuse it without duplicating the logic or
    depending on an ``ExportDialog`` instance.

    Args:
        parent: Widget to parent the confirmation ``QMessageBox`` to.
        path: Destination export path.
        settings_service: Optional ``SettingsService`` used to read/update
            the "confirm before overwrite" preference. When ``None``, no
            confirmation is required.

    Returns:
        ``True`` if the export should proceed, ``False`` if it should be
        aborted.
    """
    if settings_service is None:
        return True
    if not Path(path).exists():
        return True
    if not settings_service.get_confirm_export_overwrite():
        return True

    msg_box = QMessageBox(parent)
    msg_box.setIcon(QMessageBox.Icon.Question)
    msg_box.setWindowTitle("Overwrite File?")
    msg_box.setText(
        f"The file:\n{path}\nalready exists. Do you want to overwrite it?"
    )
    checkbox = QCheckBox("Don't ask me again")
    msg_box.setCheckBox(checkbox)
    msg_box.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    msg_box.setDefaultButton(QMessageBox.StandardButton.No)
    result = msg_box.exec()

    if result != QMessageBox.StandardButton.Yes:
        return False

    if checkbox.isChecked():
        settings_service.set_confirm_export_overwrite(False)

    return True


class ExportDialog(QDialog):
    """Dialog for exporting images with format and quality options."""

    def __init__(
        self,
        image: Image.Image,
        default_path: str = "",
        parent=None,
        settings_service: Optional[SettingsService] = None,
    ):
        """Initialize the export dialog.
        
        Args:
            image: PIL Image to export
            default_path: Default file path. When empty and a
                ``settings_service`` is provided, the last-used export
                directory is used as the dialog's starting location.
            parent: Parent widget
            settings_service: Optional SettingsService for persisting the
                last-used export directory.
        """
        super().__init__(parent)
        self._image = image
        self._default_path = default_path
        self._export_service = ExportService()
        self._settings_service = settings_service
        
        self.setWindowTitle("Export Image")
        self.setMinimumWidth(450)
        self.setModal(True)
        
        self._setup_ui()
        self._apply_last_export_options()

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        # File location group
        file_group = QGroupBox("File Location")
        file_layout = QHBoxLayout(file_group)
        
        self._path_edit = QLineEdit(self._default_path)
        self._path_edit.setPlaceholderText("Select output file...")
        file_layout.addWidget(self._path_edit)
        
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._browse_file)
        file_layout.addWidget(browse_button)
        
        layout.addWidget(file_group)
        
        # Format options group
        format_group = QGroupBox("Format Options")
        format_layout = QFormLayout(format_group)
        
        # Format selector
        self._format_combo = QComboBox()
        for fmt in self._export_service.get_export_formats():
            self._format_combo.addItem(fmt['name'], fmt)
        self._format_combo.currentIndexChanged.connect(self._on_format_changed)
        format_layout.addRow("Format:", self._format_combo)
        
        # Quality slider (for JPEG)
        self._quality_label = QLabel("Quality:")
        self._quality_slider = QSlider(Qt.Orientation.Horizontal)
        self._quality_slider.setRange(1, 100)
        self._quality_slider.setValue(95)
        self._quality_slider.valueChanged.connect(self._on_quality_changed)
        
        self._quality_value = QLabel("95")
        quality_layout = QHBoxLayout()
        quality_layout.addWidget(self._quality_slider)
        quality_layout.addWidget(self._quality_value)
        format_layout.addRow(self._quality_label, quality_layout)
        
        layout.addWidget(format_group)
        
        # Resize options group
        resize_group = QGroupBox("Resize Options")
        resize_layout = QFormLayout(resize_group)
        
        # Resize preset
        self._resize_combo = QComboBox()
        for preset in self._export_service.get_resize_presets():
            self._resize_combo.addItem(preset['name'], preset['size'])
        resize_layout.addRow("Size:", self._resize_combo)
        
        # Custom size
        custom_layout = QHBoxLayout()
        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 20000)
        self._width_spin.setValue(self._image.width)
        custom_layout.addWidget(self._width_spin)
        
        custom_layout.addWidget(QLabel("x"))
        
        self._height_spin = QSpinBox()
        self._height_spin.setRange(1, 20000)
        self._height_spin.setValue(self._image.height)
        custom_layout.addWidget(self._height_spin)
        
        custom_layout.addWidget(QLabel("px"))
        resize_layout.addRow("Custom:", custom_layout)
        
        # Preserve aspect ratio
        self._preserve_aspect = QCheckBox("Preserve aspect ratio")
        self._preserve_aspect.setChecked(True)
        resize_layout.addRow("", self._preserve_aspect)
        
        layout.addWidget(resize_group)
        
        # Image info
        info_label = QLabel(
            f"Original size: {self._image.width} x {self._image.height} px"
        )
        info_label.setStyleSheet("color: #808080;")
        layout.addWidget(info_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        self._export_button = QPushButton("Export")
        self._export_button.setDefault(True)
        self._export_button.clicked.connect(self._do_export)
        button_layout.addWidget(self._export_button)
        
        layout.addLayout(button_layout)
        
        # Connect preset changes
        self._resize_combo.currentIndexChanged.connect(self._on_resize_preset_changed)

    def _apply_last_export_options(self):
        """Pre-populate widgets from the last-used export options, if any.

        Called after ``_setup_ui()`` so the signal connections it makes
        (format combo -> ``_on_format_changed``, etc.) are already wired;
        ``QComboBox.setCurrentIndex`` emits ``currentIndexChanged`` itself
        when the index actually changes, so ``_on_format_changed`` fires
        automatically here and no explicit call is needed.
        """
        if self._settings_service is None:
            return
        options = self._settings_service.get_last_export_options()
        if not options:
            return

        format_name = options.get("format")
        if format_name:
            for i in range(self._format_combo.count()):
                data = self._format_combo.itemData(i)
                if data and data.get("name") == format_name:
                    self._format_combo.setCurrentIndex(i)
                    break

        quality = options.get("quality")
        if isinstance(quality, int):
            self._quality_slider.setValue(quality)

        width = options.get("width")
        height = options.get("height")
        if width is not None and height is not None:
            self._width_spin.setValue(width)
            self._height_spin.setValue(height)

        preserve_aspect = options.get("preserve_aspect")
        if preserve_aspect is not None:
            self._preserve_aspect.setChecked(bool(preserve_aspect))

    def _browse_file(self):
        """Open file browser for export location."""
        format_data = self._format_combo.currentData()
        ext = format_data['extension'] if format_data else ".jpg"
        
        # Decide the dialog's starting location: prefer the current text
        # in the path edit; if empty, fall back to last-used export dir.
        start = self._path_edit.text()
        if not start and self._settings_service is not None:
            start = self._settings_service.get_last_export_dir()
        
        file_filter = f"Images (*{ext});;All Files (*)"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Image",
            start,
            file_filter
        )
        
        if path:
            # Ensure correct extension
            if not path.lower().endswith(ext):
                path += ext
            self._path_edit.setText(path)
            if self._settings_service is not None:
                self._settings_service.set_last_export_dir(path)

    def _on_format_changed(self, index: int):
        """Handle format selection change."""
        format_data = self._format_combo.currentData()
        
        # Show/hide quality slider for JPEG
        is_jpeg = format_data and format_data['name'] == 'JPEG'
        self._quality_label.setVisible(is_jpeg)
        self._quality_slider.setVisible(is_jpeg)
        self._quality_value.setVisible(is_jpeg)

    def _on_quality_changed(self, value: int):
        """Handle quality slider change."""
        self._quality_value.setText(str(value))

    def _on_resize_preset_changed(self, index: int):
        """Handle resize preset change."""
        size = self._resize_combo.currentData()
        if size:
            self._width_spin.setValue(size[0])
            self._height_spin.setValue(size[1])
        else:
            # Original size
            self._width_spin.setValue(self._image.width)
            self._height_spin.setValue(self._image.height)

    def _do_export(self):
        """Execute the export."""
        path = self._path_edit.text()
        if not path:
            QMessageBox.warning(self, "Export Error", "Please specify an output file.")
            return
        
        # Get export options
        format_data = self._format_combo.currentData()
        format_name = format_data['name'] if format_data else 'JPEG'
        quality = self._quality_slider.value()
        
        # Get resize options
        width = self._width_spin.value()
        height = self._height_spin.value()
        resize = None
        if width != self._image.width or height != self._image.height:
            resize = (width, height)
        
        preserve_aspect = self._preserve_aspect.isChecked()

        if not confirm_overwrite_if_needed(self, path, self._settings_service):
            return

        # Export
        success = self._export_service.export_image(
            self._image,
            path,
            format=format_name,
            quality=quality,
            resize=resize,
            preserve_aspect=preserve_aspect
        )

        if success:
            if self._settings_service is not None:
                self._settings_service.set_last_export_options({
                    "format": format_name,
                    "quality": quality,
                    "width": resize[0] if resize else None,
                    "height": resize[1] if resize else None,
                    "preserve_aspect": preserve_aspect,
                })
            QMessageBox.information(self, "Export Complete", f"Image exported to:\n{path}")
            self.accept()
        else:
            QMessageBox.critical(self, "Export Failed", "Failed to export image.")

    def get_export_path(self) -> str:
        """Get the exported file path.
        
        Returns:
            Path where image was exported
        """
        return self._path_edit.text()
