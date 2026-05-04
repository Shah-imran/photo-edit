"""Unit tests for src.utils.logging_config."""

from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path

import pytest

from src.utils.logging_config import (
    _HANDLER_TAG,
    _LOG_FILENAME,
    configure_logging,
)


def _photoedit_handlers() -> list[logging.Handler]:
    return [
        h
        for h in logging.getLogger().handlers
        if getattr(h, _HANDLER_TAG, False)
    ]


@pytest.fixture(autouse=True)
def _clean_root_handlers():
    """Strip our handlers before and after each test for isolation."""
    # Snapshot original level so we can restore it.
    root = logging.getLogger()
    original_level = root.level
    for handler in _photoedit_handlers():
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    yield
    for handler in _photoedit_handlers():
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    root.setLevel(original_level)


class TestConfigureLoggingBasics:
    """Smoke / round-trip cases."""

    def test_returns_log_dir_and_creates_directory(self, tmp_path):
        target = tmp_path / "nested" / "logs"
        result = configure_logging(log_dir=target, enable_console=False)
        assert result == target
        assert target.exists()

    def test_info_message_written_to_file(self, tmp_path):
        configure_logging(log_dir=tmp_path, enable_console=False)
        logging.getLogger("test").info("hello world")
        for h in _photoedit_handlers():
            h.flush()

        contents = (tmp_path / _LOG_FILENAME).read_text(encoding="utf-8")
        assert re.search(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[INFO\] test: hello world",
            contents,
        )

    def test_debug_below_default_level_is_dropped(self, tmp_path):
        configure_logging(log_dir=tmp_path, enable_console=False)
        logging.getLogger("test").debug("debug-line")
        for h in _photoedit_handlers():
            h.flush()

        contents = (tmp_path / _LOG_FILENAME).read_text(encoding="utf-8")
        assert "debug-line" not in contents

    def test_module_logger_propagates_to_file(self, tmp_path):
        configure_logging(log_dir=tmp_path, enable_console=False)
        logging.getLogger("src.foo.bar").info("propagation-check")
        for h in _photoedit_handlers():
            h.flush()

        contents = (tmp_path / _LOG_FILENAME).read_text(encoding="utf-8")
        assert "propagation-check" in contents
        assert "src.foo.bar" in contents


class TestConfigureLoggingLevels:
    """Console and file levels are independent."""

    def test_console_warning_filters_info_but_file_keeps_info(
        self, tmp_path, capsys
    ):
        configure_logging(
            log_dir=tmp_path,
            file_level=logging.INFO,
            console_level=logging.WARNING,
        )
        logging.getLogger("test").info("info-only")
        logging.getLogger("test").warning("warn-line")
        for h in _photoedit_handlers():
            h.flush()

        stderr = capsys.readouterr().err
        assert "info-only" not in stderr
        assert "warn-line" in stderr

        contents = (tmp_path / _LOG_FILENAME).read_text(encoding="utf-8")
        assert "info-only" in contents
        assert "warn-line" in contents


class TestConfigureLoggingIdempotency:
    """Repeated calls must not stack handlers."""

    def test_two_calls_produce_two_handlers_total(self, tmp_path):
        configure_logging(log_dir=tmp_path)
        configure_logging(log_dir=tmp_path)
        # one file handler + one console handler each call, but the
        # second call must remove the first set first.
        assert len(_photoedit_handlers()) == 2

    def test_second_call_with_different_dir_redirects_writes(self, tmp_path):
        first = tmp_path / "first"
        second = tmp_path / "second"
        configure_logging(log_dir=first, enable_console=False)
        logging.getLogger("test").info("before-switch")
        for h in _photoedit_handlers():
            h.flush()

        first_size = (first / _LOG_FILENAME).stat().st_size

        configure_logging(log_dir=second, enable_console=False)
        logging.getLogger("test").info("after-switch")
        for h in _photoedit_handlers():
            h.flush()

        # The first directory's file must not have grown after we
        # switched directories (the old handler was removed and closed).
        assert (first / _LOG_FILENAME).stat().st_size == first_size

        new_contents = (second / _LOG_FILENAME).read_text(encoding="utf-8")
        assert "after-switch" in new_contents
        assert "before-switch" not in new_contents


class TestConfigureLoggingRotation:
    """Rotation triggers when max_bytes is exceeded."""

    def test_backup_file_created_when_size_exceeds_threshold(self, tmp_path):
        configure_logging(
            log_dir=tmp_path,
            enable_console=False,
            max_bytes=512,
            backup_count=2,
        )
        logger = logging.getLogger("rotation-test")
        # Each log line is ~80-120 bytes; 50 of them comfortably exceeds 512.
        for i in range(50):
            logger.info("padding-line-%03d-%s", i, "x" * 40)
        for h in _photoedit_handlers():
            h.flush()

        assert (tmp_path / _LOG_FILENAME).exists()
        assert (tmp_path / f"{_LOG_FILENAME}.1").exists()


class TestConfigureLoggingFallback:
    """Unwritable directory must not crash startup."""

    def test_unwritable_dir_falls_back_to_stderr_only(
        self, tmp_path, monkeypatch, capsys
    ):
        target = tmp_path / "blocked"

        original_mkdir = Path.mkdir

        def fake_mkdir(self, *args, **kwargs):
            if self == target:
                raise OSError("simulated read-only filesystem")
            return original_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", fake_mkdir)

        configure_logging(log_dir=target, enable_console=True)

        handlers = _photoedit_handlers()
        # No file handler must be attached when mkdir failed.
        assert all(
            not isinstance(h, logging.handlers.RotatingFileHandler)  # type: ignore[arg-type]
            for h in handlers
        )
        # The stderr handler must still be there.
        assert any(isinstance(h, logging.StreamHandler) for h in handlers)
        # And the target directory must not have been created.
        assert not target.exists()

        stderr = capsys.readouterr().err
        assert "simulated read-only filesystem" in stderr


class TestConfigureLoggingConsoleToggle:
    """The enable_console flag controls stderr attachment."""

    def test_disabled_console_means_only_file_handler(self, tmp_path):
        configure_logging(log_dir=tmp_path, enable_console=False)
        handlers = _photoedit_handlers()
        assert len(handlers) == 1
        assert isinstance(
            handlers[0], logging.handlers.RotatingFileHandler  # type: ignore[arg-type]
        )
