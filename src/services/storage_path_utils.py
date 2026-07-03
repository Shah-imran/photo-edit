"""Helpers for resolving writable app storage paths."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

try:
    from PyQt6.QtCore import QCoreApplication, QStandardPaths
except ImportError:  # pragma: no cover - runtime dependency
    QCoreApplication = None  # type: ignore[assignment]
    QStandardPaths = None  # type: ignore[assignment]


APP_NAME = "PhotoEdit"
_GENERIC_QT_APP_NAMES = {"", "python", "python.exe", "pytest", "pytest.exe"}


def ensure_qt_app_identity() -> None:
    """Set a stable Qt app/org identity when the host left generic defaults."""
    if QCoreApplication is None:
        return
    app = QCoreApplication.instance()
    if app is None:
        return

    application_name = app.applicationName().strip().lower()
    if application_name in _GENERIC_QT_APP_NAMES:
        app.setApplicationName(APP_NAME)

    organization_name = app.organizationName().strip().lower()
    if organization_name in _GENERIC_QT_APP_NAMES:
        app.setOrganizationName(APP_NAME)


def resolve_app_data_root() -> Path:
    """Return the preferred persistent-data root for the current platform."""
    ensure_qt_app_identity()
    if QCoreApplication is not None and QStandardPaths is not None:
        app = QCoreApplication.instance()
        if app is not None:
            location = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            )
            if location:
                return Path(location)

    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def resolve_app_cache_root() -> Path:
    """Return the preferred cache root for the current platform."""
    ensure_qt_app_identity()
    if QCoreApplication is not None and QStandardPaths is not None:
        app = QCoreApplication.instance()
        if app is not None:
            location = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.CacheLocation
            )
            if location:
                return Path(location)

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_NAME / "cache"
        return Path.home() / "AppData" / "Local" / APP_NAME / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP_NAME
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / ".cache" / APP_NAME


def ensure_writable_directory(path: Path, fallback_relative: Path) -> Path:
    """Create ``path`` or fall back to a temp-backed PhotoEdit directory."""
    candidate = Path(path)
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    except OSError:
        fallback = Path(tempfile.gettempdir()) / APP_NAME / fallback_relative
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
