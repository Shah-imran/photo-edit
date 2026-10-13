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

import json
import logging
from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import QSettings

from src.services.storage_path_utils import ensure_qt_app_identity


logger = logging.getLogger(__name__)


_KEY_LAST_OPEN_DIR = "paths/last_open_dir"
_KEY_LAST_EXPORT_DIR = "paths/last_export_dir"
_KEY_WINDOW_GEOMETRY = "window/geometry"
_KEY_WINDOW_STATE = "window/state"
_KEY_CURRENT_IMAGE_PATH = "session/current_image_path"
_KEY_CONFIRM_EXPORT_OVERWRITE = "export/confirm_overwrite"
_KEY_LAST_EXPORT_OPTIONS = "export/last_options"
_KEY_PROXY_MAX_SIZE = "performance/proxy_max_size"
_KEY_INTERACTIVE_PROXY_MAX_SIZE = "performance/interactive_proxy_max_size"


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
        if settings is None:
            ensure_qt_app_identity()
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

    def get_window_state(self) -> Optional[bytes]:
        """Return the saved ``QMainWindow.saveState()`` blob, or ``None``."""
        value = self._settings.value(_KEY_WINDOW_STATE)
        if value is None:
            return None
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        try:
            data = bytes(value)
        except TypeError:
            logger.warning("Stored window state has unexpected type: %r", type(value))
            return None
        return data

    def set_window_state(self, state: bytes) -> None:
        """Persist the ``QMainWindow.saveState()`` blob."""
        self._settings.setValue(_KEY_WINDOW_STATE, state)

    def get_current_image_path(self) -> Optional[str]:
        """Return the last-opened image path when it still exists on disk."""
        value = self._settings.value(_KEY_CURRENT_IMAGE_PATH)
        if not isinstance(value, str) or not value:
            return None
        candidate = Path(value)
        if not candidate.is_file():
            logger.info("Stored current image path no longer exists: %s", value)
            return None
        return str(candidate)

    def set_current_image_path(self, path: Optional[str]) -> None:
        """Persist or clear the last-opened image path."""
        if not path:
            self._settings.remove(_KEY_CURRENT_IMAGE_PATH)
            return
        candidate = Path(path).expanduser()
        self._settings.setValue(_KEY_CURRENT_IMAGE_PATH, str(candidate))

    def get_confirm_export_overwrite(self) -> bool:
        """Return whether Export should confirm before overwriting a file.

        Defaults to ``True`` (confirmation is shown) when the preference
        has never been explicitly set. The ``type=bool`` hint keeps
        ``QSettings`` from handing back the stored ``"false"``/``"true"``
        string on platforms that persist booleans as text (a string is
        always truthy in Python, so without this the setting would never
        actually suppress the prompt).
        """
        return bool(
            self._settings.value(
                _KEY_CONFIRM_EXPORT_OVERWRITE, True, type=bool
            )
        )

    def set_confirm_export_overwrite(self, confirm: bool) -> None:
        """Persist whether Export should confirm before overwriting a file."""
        self._settings.setValue(_KEY_CONFIRM_EXPORT_OVERWRITE, bool(confirm))

    def get_last_export_options(self) -> Optional[dict]:
        """Return the last-persisted "Export with Previous" options.

        The options are stored as a JSON string (see
        :meth:`set_last_export_options`) rather than relying on
        ``QSettings``'s own dict round-tripping, which is backend-specific.
        Returns ``None`` when no export has completed yet, or when the
        stored value is missing/empty/corrupt, rather than raising.

        The returned dict has the shape::

            {
                "format": str,            # e.g. "JPEG"
                "quality": int,            # 1-100
                "width": Optional[int],    # None means no resize
                "height": Optional[int],   # None means no resize
                "preserve_aspect": bool,
            }
        """
        value = self._settings.value(_KEY_LAST_EXPORT_OPTIONS)
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning("Stored last export options are not valid JSON; ignoring")
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    def set_last_export_options(self, options: dict) -> None:
        """Persist the options used by the most recent successful export.

        See :meth:`get_last_export_options` for the expected shape.
        """
        self._settings.setValue(_KEY_LAST_EXPORT_OPTIONS, json.dumps(options))

    def get_proxy_max_size(self) -> Optional[int]:
        """Return the preferred quality-preview proxy max dimension (px).

        Returns ``None`` when the preference has never been explicitly
        set. There is deliberately no hardcoded fallback here -- the
        default lives on ``ProxyManager.DEFAULT_PROXY_SIZE`` so there is a
        single source of truth for it; callers that need an effective
        value should fall back to that constant themselves.
        """
        if not self._settings.contains(_KEY_PROXY_MAX_SIZE):
            return None
        return int(self._settings.value(_KEY_PROXY_MAX_SIZE, 0, type=int))

    def set_proxy_max_size(self, size: int) -> None:
        """Persist the preferred quality-preview proxy max dimension (px)."""
        self._settings.setValue(_KEY_PROXY_MAX_SIZE, int(size))

    def get_interactive_proxy_max_size(self) -> Optional[int]:
        """Return the preferred interactive/drag proxy max dimension (px).

        Returns ``None`` when unset. See :meth:`get_proxy_max_size` for
        why there is no hardcoded default here -- it lives on
        ``ProxyManager.DEFAULT_INTERACTIVE_PROXY_SIZE`` instead.
        """
        if not self._settings.contains(_KEY_INTERACTIVE_PROXY_MAX_SIZE):
            return None
        return int(
            self._settings.value(_KEY_INTERACTIVE_PROXY_MAX_SIZE, 0, type=int)
        )

    def set_interactive_proxy_max_size(self, size: int) -> None:
        """Persist the preferred interactive/drag proxy max dimension (px)."""
        self._settings.setValue(_KEY_INTERACTIVE_PROXY_MAX_SIZE, int(size))

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
