"""Main entry point for PhotoEdit application."""

import sys
from PyQt6.QtWidgets import QApplication
from src.views.main_window import MainWindow


def main():
    """Main function to start the PhotoEdit application."""
    # High DPI scaling is enabled by default in Qt6
    # Create application
    app = QApplication(sys.argv)
    app.setApplicationName("PhotoEdit")
    app.setOrganizationName("PhotoEdit")
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
