"""Centralized logging configuration for PhotoEdit.

Call :func:`configure_logging` exactly once at application startup, after
``QApplication.setApplicationName/setOrganizationName`` so that
``QStandardPaths.AppDataLocation`` resolves correctly.

Tests can call ``configure_logging(log_dir=tmp_path)`` to bypass the
OS-native lookup and re-call freely; the function is idempotent.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional

try:
    from PyQt6.QtCore import QCoreApplication, QStandardPaths
except ImportError:  # pragma: no cover - PyQt6 is a hard runtime dep
    QCoreApplication = None  # type: ignore[assignment]
    QStandardPaths = None  # type: ignore[assignment]


_HANDLER_TAG = "_photoedit"
_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"
_DEFAULT_MAX_BYTES = 5 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 5
_LOG_FILENAME = "photoedit.log"


def configure_logging(
    log_dir: Optional[Path] = None,
    file_level: int = logging.INFO,
    console_level: int = logging.INFO,
    enable_console: bool = True,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    backup_count: int = _DEFAULT_BACKUP_COUNT,
) -> Path:
    """Attach PhotoEdit's standard handlers to the root logger.

    Args:
        log_dir: Directory to write ``photoedit.log`` into. When ``None``,
            an OS-native location is chosen (see :func:`_resolve_log_dir`).
        file_level: Minimum level for the rotating file handler.
        console_level: Minimum level for the stderr handler.
        enable_console: When ``False``, only the file handler is installed.
        max_bytes: Rotation threshold for the file handler.
        backup_count: Number of rotated backups to keep.

    Returns:
        The directory the file handler is writing to. When the directory
        is unwritable, falls back to **stderr-only** logging and returns
        the directory that was attempted (so callers can surface the
        problem to users if they wish).
    """
    if log_dir is None:
        log_dir = _resolve_log_dir()
    log_dir = Path(log_dir)

    root = logging.getLogger()
    _remove_photoedit_handlers(root)

    formatter = logging.Formatter(_DEFAULT_FORMAT, datefmt=_DEFAULT_DATEFMT)

    # Attach the console handler *first* so any error emitted while we
    # try to set up the file handler still reaches stderr.
    if enable_console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(console_level)
        console_handler.setFormatter(formatter)
        setattr(console_handler, _HANDLER_TAG, True)
        root.addHandler(console_handler)

    file_handler_attached = False
    file_setup_error: Optional[OSError] = None
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / _LOG_FILENAME,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(file_level)
        file_handler.setFormatter(formatter)
        setattr(file_handler, _HANDLER_TAG, True)
        root.addHandler(file_handler)
        file_handler_attached = True
    except OSError as exc:
        file_setup_error = exc

    if file_handler_attached or enable_console:
        active_levels = []
        if file_handler_attached:
            active_levels.append(file_level)
        if enable_console:
            active_levels.append(console_level)
        root.setLevel(min(active_levels))

    if file_setup_error is not None:
        # Logged after the root level is set so the message reaches the
        # console handler we just attached. We deliberately do not raise.
        logging.getLogger(__name__).error(
            "Could not open log file in %s (%s); using stderr only",
            log_dir,
            file_setup_error,
        )

    return log_dir


def _remove_photoedit_handlers(logger: logging.Logger) -> None:
    """Remove only handlers we previously installed (idempotency)."""
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_TAG, False):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # pragma: no cover - defensive
                pass


def _resolve_log_dir() -> Path:
    """Pick the platform-correct log directory.

    Prefers ``QStandardPaths.AppDataLocation`` when a Qt application has
    been instantiated (so org/app names are honored). Falls back to
    well-known per-OS environment variables otherwise, so the helper is
    usable from unit tests that have no ``QApplication``.
    """
    if QCoreApplication is not None and QStandardPaths is not None:
        app = QCoreApplication.instance()
        if app is not None:
            location = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppDataLocation
            )
            if location:
                return Path(location) / "logs"

    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "PhotoEdit" / "logs"
        return Path.home() / "AppData" / "Roaming" / "PhotoEdit" / "logs"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "PhotoEdit"

    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home) / "PhotoEdit" / "logs"
    return Path.home() / ".local" / "state" / "PhotoEdit" / "logs"
