"""Main entry point for PhotoEdit application."""

import logging
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMessageBox

from src.utils.logging_config import configure_logging
from src.utils.single_instance import SingleInstanceGuard
from src.utils.stall_watchdog import UiStallWatchdog
from src.views.main_window import MainWindow
from src.views.theme import apply_theme


def main():
    """Main function to start the PhotoEdit application."""
    # High DPI scaling is enabled by default in Qt6
    app = QApplication(sys.argv)
    app.setApplicationName("PhotoEdit")
    app.setOrganizationName("PhotoEdit")
    apply_theme(app)

    # Keep logs project-local during active development so performance traces
    # are easy to inspect after a slider interaction.
    project_root = Path(__file__).resolve().parents[1]
    log_dir = configure_logging(
        log_dir=project_root / "logs",
        file_level=logging.DEBUG,
    )
    logger = logging.getLogger(__name__)
    logger.info("PhotoEdit starting; logs at %s", log_dir)

    # Single-instance enforcement. QApplication must already exist (it does,
    # above) before showing a QMessageBox. The guard is kept referenced for
    # the rest of this function (and implicitly for the process lifetime via
    # sys.exit below) so the lock is not released early by garbage collection.
    instance_guard = SingleInstanceGuard()
    if not instance_guard.try_acquire():
        logger.info(
            "Another PhotoEdit instance is already running; exiting."
        )
        QMessageBox.information(
            None,
            "PhotoEdit Already Running",
            "PhotoEdit is already running. Only one instance can run at "
            "a time.",
        )
        sys.exit(0)

    window = MainWindow()
    window.show()

    # Log any event-loop freeze over 50 ms as UI-STALL in photoedit.log.
    watchdog = UiStallWatchdog(app)
    watchdog.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
