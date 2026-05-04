"""Application settings service.

Wraps :class:`PyQt6.QtCore.QSettings` with a small, typed API for the keys
PhotoEdit currently persists. Views and controllers must go through this
service rather than calling ``QSettings`` directly so the GUI can be
reskinned or replaced without touching persistence logic
(see ``docs/planning/INCREMENTAL_WORKFLOW.md`` section 5.1).

On Windows ``QSettings`` defaults to the registry under
``HKCU\\Software\\PhotoEdit\\PhotoEdit`` (the org/app names are configured
in :mod:`src.main`). On macOS/Linux it uses native plist/INI files.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import QSettings


logger = logging.getLogger(__name__)


_KEY_LAST_OPEN_DIR = "paths/last_open_dir"
_KEY_LAST_EXPORT_DIR = "paths/last_export_dir"
_KEY_WINDOW_GEOMETRY = "window/geometry"


class SettingsService:
    """Typed wrapper over ``QSettings`` for application-level state.

    Scope of values managed today:

    * Last directory used by Open/Import dialogs.
    * Last directory used by the Export Browse dialog.
    * Main window geometry (size and position).

    Per-image edit state and project files are out of scope for this
    service (handled by ``ProjectModel`` / future ``K0`` JSON schema).
    """

    def __init__(self, settings: Optional[QSettings] = None) -> None:
        """Initialize the service.

        Args:
            settings: Optional :class:`QSettings` instance. When ``None``
                the default constructor is used, which reads
                ``QApplication.organizationName()`` and
                ``QApplication.applicationName()`` configured in
                :mod:`src.main`. Tests should pass an isolated
                ``QSettings`` (``IniFormat`` + ``UserScope`` + custom
                org/app) so they do not pollute the user's registry.
        """
        self._settings = settings if settings is not None else QSettings()

    def get_last_open_dir(self) -> str:
        """Return the last directory used for Open/Import dialogs.

        Falls back to the user's home directory on first launch or when
        the stored path no longer exists on disk.
        """
        return self._get_existing_dir(_KEY_LAST_OPEN_DIR)

    def set_last_open_dir(self, path: str) -> None:
        """Persist the last open/import directory.

        ``path`` may be either a directory or a file path. When it is a
        file path, the parent directory is stored.
        """
        self._set_dir(_KEY_LAST_OPEN_DIR, path)

    def get_last_export_dir(self) -> str:
        """Return the last directory used for the Export dialog.

        Same fallback semantics as :meth:`get_last_open_dir`.
        """
        return self._get_existing_dir(_KEY_LAST_EXPORT_DIR)

    def set_last_export_dir(self, path: str) -> None:
        """Persist the last export directory (file path or directory)."""
        self._set_dir(_KEY_LAST_EXPORT_DIR, path)

    def get_window_geometry(self) -> Optional[bytes]:
        """Return the saved ``QMainWindow.saveGeometry()`` blob, or ``None``."""
        value = self._settings.value(_KEY_WINDOW_GEOMETRY)
        if value is None:
            return None
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        try:
            data = bytes(value)
        except TypeError:
            logger.warning("Stored window geometry has unexpected type: %r", type(value))
            return None
        return data

    def set_window_geometry(self, geometry: bytes) -> None:
        """Persist the ``QMainWindow.saveGeometry()`` blob."""
        self._settings.setValue(_KEY_WINDOW_GEOMETRY, geometry)

    def sync(self) -> None:
        """Flush pending changes to the underlying store."""
        self._settings.sync()

    def _get_existing_dir(self, key: str) -> str:
        """Read a directory value from settings, falling back to home.

        Logs at INFO when a stale path is replaced with the home fallback
        so users can trace why a dialog reset.
        """
        home = str(Path.home())
        stored = self._settings.value(key, home)
        if not isinstance(stored, str) or not stored:
            return home
        if not Path(stored).is_dir():
            logger.info(
                "Stored directory for %s no longer exists; falling back to home", key
            )
            return home
        return stored

    def _set_dir(self, key: str, path: str) -> None:
        """Normalize a file or directory path to a directory and store it."""
        if not path:
            return
        candidate = Path(path)
        directory = candidate if candidate.is_dir() else candidate.parent
        directory_str = str(directory)
        self._settings.setValue(key, directory_str)
        logger.info("Stored %s = %s", key, directory_str)

    def _get(self, key: str, default: Any = None) -> Any:
        """Generic getter (kept for future expansion / tests)."""
        return self._settings.value(key, default)

    def _set(self, key: str, value: Any) -> None:
        """Generic setter (kept for future expansion / tests)."""
        self._settings.setValue(key, value)
