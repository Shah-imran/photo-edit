"""Tests for src.utils.single_instance.SingleInstanceGuard."""

import os
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QLockFile

from src.utils.single_instance import SingleInstanceGuard, default_lock_file_path


def test_first_guard_acquires_lock(tmp_path: Path):
    lock_path = str(tmp_path / "test.lock")
    guard = SingleInstanceGuard(lock_path)

    assert guard.try_acquire() is True
    assert guard.is_held() is True

    guard.release()


def test_second_guard_fails_while_first_holds_same_path(tmp_path: Path):
    """Verifies QLockFile detects contention from a second QLockFile
    instance pointed at the same path, within the same process.

    This was checked directly rather than assumed: QLockFile tracks
    locking per *file path*, not merely per OS process, so two QLockFile
    objects in the same Python process pointed at the same path do behave
    like two independent contenders -- the second tryLock() call fails
    while the first instance still holds the lock. This matches the real
    two-process scenario closely enough to exercise via a single pytest
    process, which is the strategy used here.
    """
    lock_path = str(tmp_path / "test.lock")

    first = SingleInstanceGuard(lock_path)
    second = SingleInstanceGuard(lock_path)

    assert first.try_acquire() is True
    assert second.try_acquire(timeout_ms=50) is False
    assert second.is_held() is False
    assert second.error() == QLockFile.LockError.LockFailedError

    first.release()


def test_third_attempt_succeeds_after_release(tmp_path: Path):
    lock_path = str(tmp_path / "test.lock")

    first = SingleInstanceGuard(lock_path)
    assert first.try_acquire() is True

    second = SingleInstanceGuard(lock_path)
    assert second.try_acquire(timeout_ms=50) is False

    first.release()

    third = SingleInstanceGuard(lock_path)
    assert third.try_acquire() is True
    third.release()


def test_error_introspection_after_success_and_failure(tmp_path: Path):
    lock_path = str(tmp_path / "test.lock")

    first = SingleInstanceGuard(lock_path)
    assert first.try_acquire() is True
    assert first.error() == QLockFile.LockError.NoError

    second = SingleInstanceGuard(lock_path)
    assert second.try_acquire(timeout_ms=50) is False
    assert second.error() == QLockFile.LockError.LockFailedError

    first.release()


def test_context_manager_releases_on_exit(tmp_path: Path):
    lock_path = str(tmp_path / "test.lock")

    with SingleInstanceGuard(lock_path) as guard:
        assert guard.is_held() is True

    # Lock released on context exit; a fresh guard can now acquire it.
    follow_up = SingleInstanceGuard(lock_path)
    assert follow_up.try_acquire() is True
    follow_up.release()


def test_release_without_acquire_is_a_no_op(tmp_path: Path):
    lock_path = str(tmp_path / "test.lock")
    guard = SingleInstanceGuard(lock_path)

    # Should not raise even though try_acquire() was never called.
    guard.release()


def test_lock_file_path_property_reflects_constructor_arg(tmp_path: Path):
    lock_path = str(tmp_path / "custom.lock")
    guard = SingleInstanceGuard(lock_path)

    assert guard.lock_file_path == lock_path


def test_default_lock_file_path_uses_fixed_filename():
    path = default_lock_file_path()

    assert path.endswith("PhotoEdit.lock")


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0,
    reason=(
        "chmod-based permission denial is not meaningful on Windows, and "
        "root bypasses directory permissions entirely"
    ),
)
def test_permission_error_proceeds_rather_than_blocking_startup(tmp_path: Path):
    """A lock-directory permission error must not refuse app startup.

    This is the key safety property of ``try_acquire``: only genuine
    contention with another live instance (``LockFailedError``) should
    tell the caller not to proceed. A permission or other I/O error on
    the lock directory is a real environment problem (logged loudly) but
    must still let the app start -- refusing to launch PhotoEdit entirely
    because its lock *directory* is unwritable would be a much worse
    outcome than simply skipping single-instance enforcement.
    """
    unwritable_dir = tmp_path / "locked_dir"
    unwritable_dir.mkdir()
    unwritable_dir.chmod(0o000)
    try:
        lock_path = str(unwritable_dir / "test.lock")
        guard = SingleInstanceGuard(lock_path)

        assert guard.try_acquire() is True
        assert guard.error() == QLockFile.LockError.PermissionError
        # The guard did not actually obtain the OS-level lock; it merely
        # told the caller to proceed anyway.
        assert guard.is_held() is False
    finally:
        unwritable_dir.chmod(0o755)
