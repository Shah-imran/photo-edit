"""Export dialog for saving images."""

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


class ExportDialog(QDialog):
    """Dialog for exporting images with format and quality options."""

    def __init__(
        self,
        image: Image.Image,
        default_path: str = "",
        parent=None
    ):
        """Initialize the export dialog.
        
        Args:
            image: PIL Image to export
            default_path: Default file path
            parent: Parent widget
        """
        super().__init__(parent)
        self._image = image
        self._default_path = default_path
        self._export_service = ExportService()
        
        self.setWindowTitle("Export Image")
        self.setMinimumWidth(450)
        self.setModal(True)
        
        self._setup_ui()

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

    def _browse_file(self):
        """Open file browser for export location."""
        format_data = self._format_combo.currentData()
        ext = format_data['extension'] if format_data else ".jpg"
        
        file_filter = f"Images (*{ext});;All Files (*)"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Image",
            self._path_edit.text(),
            file_filter
        )
        
        if path:
            # Ensure correct extension
            if not path.lower().endswith(ext):
                path += ext
            self._path_edit.setText(path)

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
