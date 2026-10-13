"""Single-instance enforcement using Qt's QLockFile.

Provides a small wrapper around ``QLockFile`` so ``src/main.py`` can refuse
to start a second instance of PhotoEdit while one is already running,
without hand-rolling PID-checking logic. ``QLockFile`` is already
PID-aware: it writes the current PID, hostname, and app name into the lock
file, and ``tryLock``/``error()`` detect a stale lock left behind by a
process that crashed without releasing it (Qt removes/recovers the stale
lock automatically on the next ``tryLock`` call in that case).
"""

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QLockFile, QStandardPaths

logger = logging.getLogger(__name__)

#: Fixed lock file name under the chosen writable location.
LOCK_FILE_NAME = "PhotoEdit.lock"


def default_lock_file_path() -> str:
    """Return the deterministic, real lock file path used by ``main()``.

    Uses ``QStandardPaths.StandardLocation.TempLocation`` rather than
    ``AppDataLocation``/``CacheLocation``: a lockfile is purely transient
    process-coordination state, never anything worth backing up or
    preserving between runs, which matches the conventional meaning of a
    "temp" location (and keeps it out of any directory a backup tool might
    sweep up alongside real user data/settings).
    """
    temp_dir = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.TempLocation
    )
    return str(Path(temp_dir) / LOCK_FILE_NAME)


class SingleInstanceGuard:
    """Wraps a ``QLockFile`` to coordinate single-instance enforcement.

    Pass ``lock_file_path`` explicitly (e.g. in tests, pointed at an
    isolated ``tmp_path``) to avoid contending with the real, fixed path
    that ``main()`` uses by default -- a stray lock left behind by a
    crashed test run should never be able to affect other test runs.
    """

    def __init__(self, lock_file_path: Optional[str] = None):
        self._path = lock_file_path or default_lock_file_path()
        self._lock_file = QLockFile(self._path)
        self._acquired = False

    @property
    def lock_file_path(self) -> str:
        """The path this guard's lock file lives at."""
        return self._path

    def try_acquire(self, timeout_ms: int = 100) -> bool:
        """Attempt to become the sole/primary instance.

        Returns ``True`` if the caller should proceed with startup --
        either because this process now holds the lock (``is_held()`` is
        then also ``True``), or because acquisition failed for a reason
        that is NOT genuine contention with another live instance (a
        permission or other I/O error on the lock directory). Returns
        ``False`` only for the expected, benign second-instance case
        (``QLockFile.LockError.LockFailedError``): another live process
        already holds the lock.

        A permission/unknown error is logged loudly (it is a real
        environment problem, unlike ordinary second-instance contention)
        but deliberately does not block startup -- refusing to start the
        app entirely over a lock-directory permission issue would be the
        wrong tradeoff; see ``src/main.py`` and the implementation note.
        """
        acquired = self._lock_file.tryLock(timeout_ms)
        self._acquired = acquired

        if acquired:
            return True

        error = self._lock_file.error()
        lock_error = QLockFile.LockError
        if error == lock_error.LockFailedError:
            logger.info(
                "Another PhotoEdit instance already holds the lock at %s",
                self._path,
            )
            return False
        elif error == lock_error.PermissionError:
            logger.error(
                "Permission denied acquiring single-instance lock at "
                "%s; proceeding without single-instance enforcement",
                self._path,
            )
            return True
        else:
            logger.error(
                "Unexpected error (%s) acquiring single-instance lock "
                "at %s; proceeding without single-instance enforcement",
                error,
                self._path,
            )
            return True

    def error(self) -> "QLockFile.LockError":
        """Return the ``QLockFile`` error enum from the last attempt."""
        return self._lock_file.error()

    def is_held(self) -> bool:
        """Whether this guard currently holds the lock."""
        return self._acquired and self._lock_file.isLocked()

    def release(self) -> None:
        """Release the lock, if held.

        Note: ``QLockFile`` also unlocks automatically when the underlying
        C++ object is destroyed (observed directly: letting a
        ``SingleInstanceGuard`` go out of scope without calling
        ``release()`` frees the lock for a subsequent ``try_acquire`` at
        the same path in the same process, in manual testing during
        development). Callers should still call ``release()`` explicitly
        (or use this class as a context manager) rather than relying on
        garbage-collection timing, which CPython does not guarantee is
        immediate.
        """
        if self._acquired:
            self._lock_file.unlock()
            self._acquired = False

    def __enter__(self) -> "SingleInstanceGuard":
        self.try_acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
