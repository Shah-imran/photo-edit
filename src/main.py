"""Main entry point for PhotoEdit application."""

import logging
import sys

from PyQt6.QtWidgets import QApplication

from src.utils.logging_config import configure_logging
from src.views.main_window import MainWindow


def main():
    """Main function to start the PhotoEdit application."""
    # High DPI scaling is enabled by default in Qt6
    app = QApplication(sys.argv)
    app.setApplicationName("PhotoEdit")
    app.setOrganizationName("PhotoEdit")

    # Configure logging *after* org/app names are set (so QStandardPaths
    # resolves correctly) and *before* MainWindow is constructed (so
    # first-launch INFO lines from views/services are captured).
    log_dir = configure_logging()
    logging.getLogger(__name__).info(
        "PhotoEdit starting; logs at %s", log_dir
    )

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
