"""Main entry point for PhotoEdit application."""

import logging
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from src.utils.logging_config import configure_logging
from src.views.main_window import MainWindow


def main():
    """Main function to start the PhotoEdit application."""
    # High DPI scaling is enabled by default in Qt6
    app = QApplication(sys.argv)
    app.setApplicationName("PhotoEdit")
    app.setOrganizationName("PhotoEdit")

    # Keep logs project-local during active development so performance traces
    # are easy to inspect after a slider interaction.
    project_root = Path(__file__).resolve().parents[1]
    log_dir = configure_logging(
        log_dir=project_root / "logs",
        file_level=logging.DEBUG,
    )
    logging.getLogger(__name__).info(
        "PhotoEdit starting; logs at %s", log_dir
    )

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
