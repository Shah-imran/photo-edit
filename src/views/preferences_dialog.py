"""Preferences dialog for PhotoEdit.

Implements the honestly-scoped slice of the roadmap's "Preferences UI"
bullet (see docs/planning/implementation-notes/2026-10-13-preferences-ui.md
for the full writeup of what is and is not covered):

* General: a second, more discoverable entry point for the existing
  "confirm before overwriting exported files" preference (the Export
  dialog's own "don't ask again" checkbox sets the same underlying
  value).
* Performance: two new preferences -- quality-preview and interactive
  (drag) preview proxy max dimensions -- mapped onto
  ``ProxyManager``'s already-configurable constructor parameters.

Deliberately NOT covered here (see the implementation note for why):
Local Storage path relocation, Interface theme switching, Import
defaults (copy vs. reference in place), and any user-facing threading
setting.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from src.processing.proxy_manager import ProxyManager
from src.services.settings_service import SettingsService


class PreferencesDialog(QDialog):
    """Dialog exposing the currently-safe subset of PhotoEdit preferences."""

    _SPIN_MIN = 200
    _SPIN_MAX = 6000

    def __init__(
        self,
        settings_service: Optional[SettingsService] = None,
        parent=None,
    ):
        """Initialize the preferences dialog.

        Args:
            settings_service: Optional ``SettingsService`` used to read
                and persist preferences. When ``None`` the dialog still
                opens and lets the user look at/change the default
                values, but Accept has nothing to persist to -- it is
                treated the same as Cancel for state (nothing is saved),
                though it still closes the dialog with an accepted result
                so a caller's ``if dialog.exec():`` branch is not broken
                by the absence of a settings service.
            parent: Parent widget.
        """
        super().__init__(parent)
        self._settings_service = settings_service

        self.setWindowTitle("Preferences")
        self.setMinimumWidth(420)
        self.setModal(True)

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # --- General -------------------------------------------------
        general_group = QGroupBox("General")
        general_layout = QVBoxLayout(general_group)

        confirm_default = True
        if self._settings_service is not None:
            confirm_default = self._settings_service.get_confirm_export_overwrite()
        self._confirm_overwrite_checkbox = QCheckBox(
            "Confirm before overwriting exported files"
        )
        self._confirm_overwrite_checkbox.setChecked(confirm_default)
        general_layout.addWidget(self._confirm_overwrite_checkbox)

        # Import defaults (e.g. "copy into library vs. reference in
        # place") are not exposed here: LibraryController.import_images()
        # has no configurable import-behavior toggle point today -- see
        # the implementation note's "Import defaults" section for what
        # was checked and why nothing is surfaced.

        layout.addWidget(general_group)

        # --- Performance -----------------------------------------------
        performance_group = QGroupBox("Performance")
        performance_layout = QFormLayout(performance_group)

        proxy_default = ProxyManager.DEFAULT_PROXY_SIZE
        interactive_default = ProxyManager.DEFAULT_INTERACTIVE_PROXY_SIZE
        if self._settings_service is not None:
            stored_proxy = self._settings_service.get_proxy_max_size()
            if stored_proxy is not None:
                proxy_default = stored_proxy
            stored_interactive = (
                self._settings_service.get_interactive_proxy_max_size()
            )
            if stored_interactive is not None:
                interactive_default = stored_interactive

        self._proxy_size_spin = QSpinBox()
        self._proxy_size_spin.setRange(self._SPIN_MIN, self._SPIN_MAX)
        self._proxy_size_spin.setSuffix(" px")
        self._proxy_size_spin.setValue(proxy_default)
        performance_layout.addRow(
            "Preview quality (max dimension):", self._proxy_size_spin
        )

        self._interactive_proxy_size_spin = QSpinBox()
        self._interactive_proxy_size_spin.setRange(self._SPIN_MIN, self._SPIN_MAX)
        self._interactive_proxy_size_spin.setSuffix(" px")
        self._interactive_proxy_size_spin.setValue(interactive_default)
        performance_layout.addRow(
            "Interactive preview size (max dimension):",
            self._interactive_proxy_size_spin,
        )

        restart_note = QLabel(
            "Preview size changes take effect after restarting PhotoEdit."
        )
        restart_note.setStyleSheet("color: #808080;")
        restart_note.setWordWrap(True)
        performance_layout.addRow("", restart_note)

        layout.addWidget(performance_group)

        # --- Buttons -----------------------------------------------------
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)

        ok_button = QPushButton("OK")
        ok_button.setDefault(True)
        ok_button.clicked.connect(self._on_accept)
        button_layout.addWidget(ok_button)

        layout.addLayout(button_layout)

    def _on_accept(self) -> None:
        """Persist the chosen values (if possible) and accept the dialog."""
        if self._settings_service is not None:
            self._settings_service.set_confirm_export_overwrite(
                self._confirm_overwrite_checkbox.isChecked()
            )
            self._settings_service.set_proxy_max_size(
                self._proxy_size_spin.value()
            )
            self._settings_service.set_interactive_proxy_max_size(
                self._interactive_proxy_size_spin.value()
            )
        self.accept()
