"""Main window for PhotoEdit application."""

import copy
import json
import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QDockWidget,
    QLabel,
    QStatusBar,
    QFileDialog,
    QProgressBar,
    QPushButton,
    QMessageBox,
    QInputDialog,
    QToolBar,
)
from PyQt6.QtCore import QByteArray, Qt, QTimer
from PyQt6.QtGui import QKeySequence, QAction


logger = logging.getLogger(__name__)

# Preset file envelope: see docs/planning/implementation-notes/
# 2026-10-13-import-export-presets.md section 3 for the full format
# rationale. ``PRESET_FILE_VERSION`` is bumped only if the envelope shape
# itself ever changes incompatibly; it is not tied to the app version.
PRESET_FILE_VERSION = 1
PRESET_FILE_FILTER = "PhotoEdit Preset (*.json)"

from src.models.builtin_profiles import BUILTIN_PROFILES
from src.views.image_view import ImageView
from src.views.tools_panel import ToolsPanel
from src.services.export_service import ExportService
from src.views.export_dialog import ExportDialog, confirm_overwrite_if_needed
from src.views.preferences_dialog import PreferencesDialog
from src.views.library_view import LibraryView
from src.views.theme import apply_theme
from src.views.widgets.crop_toolbar import CropToolbar
from src.views.widgets.healing_toolbar import HealingToolbar
from src.views.widgets.mask_toolbar import MaskToolbar
from src.views.widgets.filmstrip_view import FilmstripView
from src.views.widgets.image_toolbar import ImageToolBar
from src.views.widgets.workspace_header import WorkspaceHeader
from src.controllers.library_controller import LibraryController
from src.controllers.image_controller import ImageController
from src.services.library_catalog_service import LibraryCatalogService
from src.services.library_image_preview_cache_service import (
    LibraryImagePreviewCacheService,
)
from src.services.library_thumbnail_cache_service import LibraryThumbnailCacheService
from src.services.settings_service import SettingsService
from src.utils.curve_math import compute_luminance_histogram
from src.utils.image_extensions import open_image_file_dialog_filter


class MainWindow(QMainWindow):
    """Main application window with Lightroom-like layout.
    
    The window features a three-panel layout:
    - Left: Library panel (for image browsing)
    - Center: Image view (for editing)
    - Right: Tools panel (for adjustments)
    """

    def __init__(
        self,
        settings_service: Optional[SettingsService] = None,
        catalog_service: Optional[LibraryCatalogService] = None,
        thumbnail_cache_service: Optional[LibraryThumbnailCacheService] = None,
        image_preview_cache_service: Optional[LibraryImagePreviewCacheService] = None,
    ):
        """Initialize the main window.

        Args:
            settings_service: Optional SettingsService instance. When ``None``,
                a default one is created using the application's QSettings.
        """
        super().__init__()
        apply_theme()
        self.setObjectName("photoEditMainWindow")
        self.setWindowTitle("PhotoEdit")
        self.setMinimumSize(1200, 800)
        
        # One settings service shared by the window and its consumers.
        self._settings_service = settings_service or SettingsService()

        # Crash-recovery notice bookkeeping (see docs/planning/
        # implementation-notes/2026-10-13-crash-recovery-notice.md).
        # Read the PREVIOUS session's clean-shutdown flag before doing
        # anything else, then immediately mark the CURRENT session as
        # "in progress" (not yet cleanly closed). Order matters: if the
        # read happened after the write, it would always see the
        # just-written False and never detect a real crash. ``sync()``
        # is called right away so this False reaches disk promptly --
        # QSettings does not guarantee an immediate flush to the backing
        # store on every setValue() (it may buffer, depending on
        # platform/backend), and this flag's entire purpose is to
        # survive a crash that happens moments later, so relying on
        # whatever implicit flush QSettings gets around to on its own
        # would defeat the feature.
        self._last_shutdown_was_clean = self._settings_service.get_clean_shutdown()
        self._settings_service.set_clean_shutdown(False)
        self._settings_service.sync()

        self._catalog_service = (
            catalog_service if catalog_service is not None else LibraryCatalogService()
        )
        self._thumbnail_cache_service = (
            thumbnail_cache_service
            if thumbnail_cache_service is not None
            else LibraryThumbnailCacheService()
        )
        self._image_preview_cache_service = (
            image_preview_cache_service
            if image_preview_cache_service is not None
            else LibraryImagePreviewCacheService()
        )
        
        # Initialize components
        self._image_view = ImageView()
        self._tools_panel = ToolsPanel()
        self._library_view = LibraryView(show_thumbnail_grid=False)
        self._image_toolbar = ImageToolBar()
        self._crop_toolbar = CropToolbar()
        self._crop_toolbar.hide()
        self._pre_crop_mode_adjustment_state: Optional[dict] = None
        self._mask_toolbar = MaskToolbar()
        self._mask_toolbar.hide()
        self._mask_overlay_signal_connected = False
        self._healing_toolbar = HealingToolbar()
        self._healing_toolbar.hide()
        self._healing_overlay_signal_connected = False
        # Background "Export with Previous" jobs, kept referenced until done.
        self._export_tasks: list = []
        self._filmstrip_view = FilmstripView()
        self._workspace_header = WorkspaceHeader()
        self._library_controller = LibraryController(
            catalog_service=self._catalog_service,
            thumbnail_cache_service=self._thumbnail_cache_service,
        )
        self._image_controller = ImageController(
            self._image_view, settings_service=self._settings_service
        )
        self._pending_library_add_path: Optional[str] = None
        self._pending_image_library_id: Optional[str] = None
        self._pending_adjustment_payload: Optional[dict] = None
        self._pending_zoom_factor: Optional[float] = None
        self._current_image_library_id: Optional[str] = None
        # Single-slot, in-memory, session-only clipboard for Copy/Paste Edit
        # Settings -- matches Lightroom's own single-slot behavior for this
        # feature (not its separate multi-preset system). Never persisted to
        # disk; cleared when the app closes. See
        # docs/planning/implementation-notes/2026-10-13-copy-paste-edit-settings.md.
        self._copied_adjustment_state: Optional[dict] = None
        self._adjustment_persist_timer = QTimer(self)
        self._adjustment_persist_timer.setSingleShot(True)
        self._adjustment_persist_timer.setInterval(400)
        self._adjustment_persist_timer.timeout.connect(
            self._persist_current_adjustments
        )
        
        # Set up UI
        self._setup_ui()
        self._setup_menu_bar()
        self._setup_workspace_header()
        self._setup_status_bar()
        self._setup_shortcuts()
        self._connect_signals()
        self._restore_window_geometry()
        self._restore_window_state()
        self._library_controller.initialize()
        self._restore_last_session_image()

        # Defer the recovery notice until after the window is actually
        # shown. __init__ runs before show(); a QMessageBox popping up
        # mid-construction, before anything is visible, would be
        # confusing. QTimer.singleShot(0, ...) queues the call on the Qt
        # event loop instead of firing it synchronously here, so it runs
        # once the loop starts processing events -- which, per
        # src/main.py's window.show() then app.exec() sequence (and per
        # qtbot.waitExposed in tests, which also pumps the event loop),
        # is always after the window is visible.
        QTimer.singleShot(0, self._maybe_show_crash_recovery_notice)

    def _maybe_show_crash_recovery_notice(self) -> None:
        """Show a one-time notice if the previous session did not exit cleanly.

        Does nothing on the ordinary clean-shutdown-then-relaunch case.
        This is a session-level honesty notice, not a restore flow: there
        is nothing to "recover" beyond what the existing debounced
        adjustment-persist timer / library catalog save already wrote to
        disk continuously during the previous session.
        """
        if self._last_shutdown_was_clean:
            return
        QMessageBox.information(
            self,
            "PhotoEdit",
            "PhotoEdit may not have closed cleanly last time. Your edits "
            "are saved automatically as you work, so no changes should "
            "have been lost.",
        )

    def _setup_ui(self):
        """Set up the main UI components."""
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Editing workspace: canvas, local controls, then the active-library strip.
        layout.addWidget(self._image_view, 1)
        layout.addWidget(self._image_toolbar)
        layout.addWidget(self._filmstrip_view)
        # Crop/Heal/Mask options open in the right panel's tool drawer,
        # under the tool strip (Lightroom layout, docs/UI_UX.md), so the
        # photo keeps its full height while a tool is active.
        drawer = self._tools_panel.tool_drawer
        drawer.add_page("crop", self._crop_toolbar)
        drawer.add_page("heal", self._healing_toolbar)
        drawer.add_page("mask", self._mask_toolbar)
        
        # Left panel - Library
        self.library_dock = QDockWidget("Library", self)
        self.library_dock.setObjectName("library_dock")
        self.library_dock.setWidget(self._library_view)
        self.library_dock.setMinimumWidth(230)
        # Keep enough headroom for a user's persisted custom dock width.
        self.library_dock.setMaximumWidth(360)
        self.library_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.library_dock)
        
        # Right panel - Tools
        self.tools_dock = QDockWidget("Adjustments", self)
        self.tools_dock.setObjectName("tools_dock")
        self.tools_dock.setWidget(self._tools_panel)
        self.tools_dock.setMinimumWidth(310)
        self.tools_dock.setMaximumWidth(420)
        self.tools_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.tools_dock)
        self.resizeDocks(
            [self.library_dock, self.tools_dock],
            [270, 340],
            Qt.Orientation.Horizontal,
        )
        
        # Disable tools panel until image is loaded
        self._tools_panel.set_enabled(False)

    def _create_action(self, text: str, callback, shortcut: str = None) -> QAction:
        """Create a QAction with text, callback, and optional shortcut.
        
        Args:
            text: Action text
            callback: Function to call when action is triggered
            shortcut: Optional keyboard shortcut
            
        Returns:
            QAction instance
        """
        action = QAction(text, self)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            # Keep shortcuts active when the classic menu bar is hidden in
            # favor of the v2 workspace header.
            self.addAction(action)
        return action

    def _setup_menu_bar(self):
        """Set up the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self._create_action("&Open Image...", self._open_image, "Ctrl+O"))
        file_menu.addAction(self._create_action("&Import Images...", self._import_images, "Ctrl+Shift+O"))
        file_menu.addSeparator()
        file_menu.addAction(self._create_action("&Export...", self._export_image, "Ctrl+E"))
        file_menu.addAction(
            self._create_action(
                "Export with &Previous", self._export_with_previous, "Ctrl+Shift+E"
            )
        )
        file_menu.addSeparator()
        file_menu.addAction(
            self._create_action("Export &Preset...", self._export_preset)
        )
        file_menu.addAction(
            self._create_action("Import Pre&set...", self._import_preset)
        )
        file_menu.addSeparator()
        file_menu.addAction(self._create_action("E&xit", self.close, "Ctrl+Q"))
        
        # Edit menu
        edit_menu = menubar.addMenu("&Edit")
        self._undo_action = self._create_action("&Undo", self._undo, "Ctrl+Z")
        self._redo_action = self._create_action("&Redo", self._redo, "Ctrl+Shift+Z")
        edit_menu.addAction(self._undo_action)
        edit_menu.addAction(self._redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self._create_action("&Reset Adjustments", self._reset_adjustments, "Ctrl+R"))
        edit_menu.addAction(
            self._create_action(
                "&Copy Edit Settings", self._copy_edit_settings, "Ctrl+Alt+C"
            )
        )
        edit_menu.addAction(
            self._create_action(
                "&Paste Edit Settings", self._paste_edit_settings, "Ctrl+Alt+V"
            )
        )
        edit_menu.addSeparator()
        edit_menu.addAction(
            self._create_action(
                "Select &All", self._filmstrip_view.select_all, "Ctrl+A"
            )
        )
        edit_menu.addAction(
            self._create_action(
                "Select &None", self._filmstrip_view.select_none, "Ctrl+Shift+A"
            )
        )
        edit_menu.addSeparator()
        edit_menu.addAction(
            self._create_action(
                "&Preferences...", self._show_preferences, "Ctrl+,"
            )
        )

        # View menu
        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self._create_action("&Fit to Window", self._fit_to_window, "0"))
        view_menu.addAction(self._create_action("&100%", self._view_100_percent, "1"))
        view_menu.addAction(self._create_action("Zoom &In", self._zoom_in, "Ctrl+="))
        view_menu.addAction(self._create_action("Zoom &Out", self._zoom_out, "Ctrl+-"))
        view_menu.addSeparator()
        view_menu.addAction(
            self._create_action("&Next Photo", self._next_photo, "Right")
        )
        view_menu.addAction(
            self._create_action("&Previous Photo", self._previous_photo, "Left")
        )
        view_menu.addSeparator()
        view_menu.addAction(self._create_action("Toggle &Library Panel", self._toggle_library_panel, "F5"))
        view_menu.addAction(self._create_action("Toggle &Tools Panel", self._toggle_tools_panel, "F6"))

        # Tools menu: Lightroom's tool shortcuts. Pressing a tool's key while
        # it is active closes it (Done); Esc cancels.
        tools_menu = menubar.addMenu("&Tools")
        tools_menu.addAction(
            self._create_action("&Crop", lambda: self._toggle_tool("crop"), "R")
        )
        tools_menu.addAction(
            self._create_action("&Remove Spots", lambda: self._toggle_tool("heal"), "Q")
        )
        tools_menu.addAction(
            self._create_action("&Masking", lambda: self._toggle_tool("mask"), "Shift+W")
        )
        tools_menu.addAction(
            self._create_action("Cancel &Tool", self._cancel_active_tool, "Esc")
        )

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(self._create_action("&About PhotoEdit", self._show_about))

    def _setup_workspace_header(self) -> None:
        """Install the v2 workspace header across the full main window."""
        self.menuBar().hide()
        self._header_toolbar = QToolBar("Workspace", self)
        self._header_toolbar.setObjectName("workspace_toolbar")
        self._header_toolbar.setMovable(False)
        self._header_toolbar.setFloatable(False)
        self._header_toolbar.setContentsMargins(0, 0, 0, 0)
        self._header_toolbar.setStyleSheet(
            "QToolBar#workspace_toolbar { border: none; padding: 0; spacing: 0; "
            "background: #171a1e; }"
        )
        self._header_toolbar.addWidget(self._workspace_header)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._header_toolbar)

    def _setup_status_bar(self):
        """Set up the status bar."""
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        self._file_label = QLabel("No image selected")
        self._file_label.setObjectName("statusFileLabel")
        self._file_label.setStyleSheet("color: #a0a0a0; padding: 0 8px;")
        self._dimensions_label = QLabel("—")
        self._dimensions_label.setObjectName("statusDimensionsLabel")
        self._dimensions_label.setStyleSheet("color: #707070; padding: 0 8px;")
        self._status_bar.addWidget(self._file_label)
        self._status_bar.addWidget(self._dimensions_label)
        self._format_label = QLabel("—")
        self._format_label.setStyleSheet("color: #707780; padding: 0 8px;")
        self._color_space_label = QLabel("sRGB IEC61966-2.1")
        self._color_space_label.setStyleSheet("color: #707780; padding: 0 8px;")
        self._megapixels_label = QLabel("—")
        self._megapixels_label.setStyleSheet("color: #707780; padding: 0 8px;")
        self._status_bar.addWidget(self._format_label)
        self._status_bar.addWidget(self._color_space_label)
        self._status_bar.addWidget(self._megapixels_label)
        
        # Thumbnail import progress (non-modal; hidden when idle)
        self._thumb_import_label = QLabel("Thumbnails")
        self._thumb_import_label.setStyleSheet("color: #a0a0a0; padding: 0 4px;")
        self._thumb_import_progress = QProgressBar()
        self._thumb_import_progress.setFixedWidth(120)
        self._thumb_import_progress.setMinimum(0)
        self._thumb_import_progress.setMaximum(1)
        self._thumb_import_progress.setTextVisible(False)
        self._thumb_import_count_label = QLabel("0 / 0")
        self._thumb_import_count_label.setStyleSheet(
            "color: #a0a0a0; font-size: 11px; padding: 0 2px;"
        )
        self._thumb_import_container = QWidget()
        _im_lay = QHBoxLayout(self._thumb_import_container)
        _im_lay.setContentsMargins(0, 0, 8, 0)
        _im_lay.setSpacing(6)
        _im_lay.addStretch(1)
        _im_lay.addWidget(self._thumb_import_label)
        _im_lay.addWidget(self._thumb_import_progress)
        _im_lay.addWidget(self._thumb_import_count_label)
        self._thumb_import_cancel = QPushButton("Cancel")
        self._thumb_import_cancel.setFlat(True)
        self._thumb_import_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._thumb_import_cancel.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: none;
                color: #0086f0;
                font-size: 11px;
                padding: 0 2px;
                text-decoration: underline;
            }
            QPushButton:hover {
                color: #4db2ff;
            }
            QPushButton:disabled {
                color: #606060;
                text-decoration: none;
            }
            """
        )
        self._thumb_import_cancel.setToolTip("Stop generating remaining thumbnails")
        self._thumb_import_cancel.clicked.connect(self._on_thumbnail_import_cancel)
        _im_lay.addWidget(self._thumb_import_cancel)
        self._thumb_import_container.setVisible(False)
        self._status_bar.addPermanentWidget(self._thumb_import_container, 1)

        # Zoom label
        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet("padding: 0 10px;")
        self._status_bar.addPermanentWidget(self._zoom_label)

    def _setup_shortcuts(self):
        """Set up keyboard shortcuts."""
        # Additional shortcuts can be added here
        pass

    def _connect_signals(self):
        """Connect signals to slots."""
        self._image_view.image_loaded.connect(self._on_image_loaded)
        self._image_view.zoom_changed.connect(self._on_zoom_changed)
        self._image_toolbar.fit_requested.connect(self._fit_to_window)
        self._image_toolbar.actual_size_requested.connect(self._view_100_percent)
        self._image_toolbar.zoom_in_requested.connect(self._zoom_in)
        self._image_toolbar.zoom_out_requested.connect(self._zoom_out)
        self._workspace_header.undo_requested.connect(self._undo)
        self._workspace_header.redo_requested.connect(self._redo)
        self._workspace_header.export_requested.connect(self._export_image)
        self._workspace_header.workspace_changed.connect(self._on_workspace_changed)
        self._tools_panel.adjustments_changed.connect(self._on_adjustments_changed)
        # Connected to the channel-aware signal (always carries an
        # explicit channel, including "master"), not the legacy
        # ``curve_changed`` -- see docs/planning/implementation-notes/
        # 2026-10-13-per-channel-curves.md section 4.
        self._tools_panel.curve_channel_changed.connect(self._on_curve_changed)
        self._tools_panel.hsl_changed.connect(self._on_hsl_changed)
        self._tools_panel.color_grading_changed.connect(self._on_color_grading_changed)
        self._tools_panel.slider_released.connect(self._on_slider_released)
        self._tools_panel.profile_apply_requested.connect(self._apply_profile)
        self._tools_panel.crop_tool_requested.connect(lambda: self._toggle_tool("crop"))
        self._crop_toolbar.apply_requested.connect(self._apply_crop)
        self._crop_toolbar.cancel_requested.connect(self._cancel_crop)
        self._crop_toolbar.aspect_ratio_changed.connect(self._on_crop_aspect_ratio_changed)
        self._tools_panel.mask_tool_requested.connect(lambda: self._toggle_tool("mask"))
        self._mask_toolbar.apply_requested.connect(self._apply_mask)
        self._mask_toolbar.cancel_requested.connect(self._cancel_mask)
        self._mask_toolbar.remove_requested.connect(self._remove_mask)
        self._mask_toolbar.mask_type_changed.connect(self._on_mask_type_changed)
        self._mask_toolbar.invert_changed.connect(self._on_mask_invert_changed)
        self._mask_toolbar.adjustments_changed.connect(self._on_mask_adjustments_changed)
        self._tools_panel.heal_tool_requested.connect(lambda: self._toggle_tool("heal"))
        self._healing_toolbar.apply_requested.connect(self._apply_healing)
        self._healing_toolbar.cancel_requested.connect(self._cancel_healing)
        self._healing_toolbar.remove_last_requested.connect(self._on_heal_remove_last)
        self._healing_toolbar.clear_all_requested.connect(self._on_heal_clear_all)
        self._healing_toolbar.mode_changed.connect(self._on_heal_mode_changed)
        self._healing_toolbar.feather_changed.connect(self._on_heal_feather_changed)
        self._healing_toolbar.opacity_changed.connect(self._on_heal_opacity_changed)
        self._library_view.image_selected.connect(self._on_library_image_selected)
        self._filmstrip_view.image_selected.connect(self._on_library_image_selected)
        self._library_view.import_requested.connect(self._import_images)
        self._library_view.library_selected.connect(self._on_library_selected)
        self._library_view.collection_selected.connect(self._filmstrip_view.set_filter)
        self._filmstrip_view.favorite_toggled.connect(
            self._library_controller.set_entry_favorite
        )
        self._filmstrip_view.rating_changed.connect(
            self._library_controller.set_entry_rating
        )
        self._filmstrip_view.flag_changed.connect(
            self._library_controller.set_entry_flag
        )
        self._filmstrip_view.keywords_changed.connect(
            self._library_controller.set_entry_keywords
        )
        self._filmstrip_view.captured_at_changed.connect(
            self._library_controller.set_entry_captured_at
        )
        self._filmstrip_view.collection_membership_toggled.connect(
            self._library_controller.set_entry_collection_membership
        )
        self._filmstrip_view.new_collection_for_entry_requested.connect(
            self._library_controller.create_collection_with_entry
        )
        # Multi-select batch counterparts (see docs/planning/
        # implementation-notes/2026-10-13-multi-select-batch-actions.md) --
        # only ever emitted from the context menu's multi-selection branch,
        # routed to dedicated controller methods that refresh views once
        # per batch action instead of once per selected image.
        self._filmstrip_view.favorite_batch_toggled.connect(
            self._library_controller.set_entries_favorite
        )
        self._filmstrip_view.rating_batch_changed.connect(
            self._library_controller.set_entries_rating
        )
        self._filmstrip_view.flag_batch_changed.connect(
            self._library_controller.set_entries_flag
        )
        self._filmstrip_view.keywords_batch_added.connect(
            self._library_controller.add_entries_keywords
        )
        self._filmstrip_view.captured_at_batch_changed.connect(
            self._library_controller.set_entries_captured_at
        )
        self._filmstrip_view.collection_batch_added.connect(
            self._library_controller.add_entries_to_collection
        )
        # Remove Photo / Delete from Disk (PDF Edit/Photo menu, "Duplicate/
        # Delete/Remove photo" -- Duplicate is a deliberately deferred
        # architectural gap, see docs/planning/implementation-notes/
        # 2026-10-13-remove-delete-photo.md). The confirmation dialog
        # itself already lives in FilmstripView (mirrors how "Edit Date &
        # Time..." prompts there too) -- these signals only ever fire
        # AFTER the user has confirmed, carrying the chosen
        # delete_from_disk value.
        self._filmstrip_view.remove_requested.connect(
            self._on_remove_entry_requested
        )
        self._filmstrip_view.remove_batch_requested.connect(
            self._on_remove_entries_requested
        )
        self._library_view.create_library_requested.connect(
            self._on_create_library_requested
        )
        self._library_view.remove_library_requested.connect(
            self._on_remove_library_requested
        )
        self._library_view.create_collection_requested.connect(
            self._library_controller.create_collection
        )
        self._library_controller.libraries_changed.connect(
            self._library_view.set_libraries
        )
        self._library_controller.collections_changed.connect(
            self._library_view.set_collections
        )
        self._library_controller.collections_changed.connect(
            self._filmstrip_view.set_collections
        )
        self._library_controller.entries_rebuilt.connect(
            self._on_library_entries_rebuilt
        )
        self._library_controller.entry_thumbnail_updated.connect(
            self._on_entry_thumbnail_updated
        )
        self._library_controller.thumbnail_batch_started.connect(
            self._on_thumbnail_batch_started
        )
        self._library_controller.thumbnail_batch_progress.connect(
            self._on_thumbnail_batch_progress
        )
        self._library_controller.thumbnail_batch_finished.connect(
            self._on_thumbnail_batch_finished
        )
        self._image_controller.image_load_started.connect(self._on_image_load_started)
        self._image_controller.image_preview_ready.connect(self._on_image_preview_ready)
        self._image_controller.image_load_finished.connect(self._on_image_load_finished)
        self._image_controller.adjustment_state_restored.connect(
            self._on_adjustment_state_restored
        )

    def _on_library_entries_rebuilt(self, library_id: str, entries: list[dict]) -> None:
        self._library_view.set_entries(entries)
        self._filmstrip_view.set_context(
            self._library_controller.get_library_name(library_id)
        )
        self._filmstrip_view.set_entries(entries)
        self._filmstrip_view.set_current_path(
            self._image_controller.image_model.file_path
        )

    def _on_entry_thumbnail_updated(self, path: str, payload: dict) -> None:
        """Keep the library grid and filmstrip thumbnail surfaces in sync."""
        self._library_view.update_entry_thumbnail(path, payload)
        self._filmstrip_view.update_entry_thumbnail(path, payload)

    def _on_image_loaded(self):
        """Handle image loaded event."""
        file_path = self._image_controller.image_model.file_path
        if file_path:
            self.setWindowTitle("PhotoEdit")
            self._status_bar.showMessage(f"Loaded: {file_path}", 3000)
            self._file_label.setText(Path(file_path).name)
            width, height = self._image_controller.image_model.get_image_size()
            self._dimensions_label.setText(f"{width} × {height}")
            suffix = Path(file_path).suffix.lstrip(".").upper() or "IMAGE"
            self._format_label.setText(suffix)
            self._megapixels_label.setText(f"{(width * height) / 1_000_000:.1f} MP")
            self._filmstrip_view.set_current_path(file_path)
            # Enable tools panel
            self._tools_panel.set_enabled(True)

    def _on_zoom_changed(self, zoom_factor: float):
        """Handle zoom changed event."""
        percent = max(1, int(round(zoom_factor * 100)))
        self._zoom_label.setText(f"{percent}%")
        self._image_toolbar.set_zoom_factor(zoom_factor)

    def _on_adjustments_changed(self, adjustments: dict):
        """Handle adjustments changed from tools panel."""
        self._image_controller.on_adjustments_changed(adjustments)
        self._adjustment_persist_timer.start()

    def _on_curve_changed(self, channel: str, points: list):
        """Handle one of the 4 tone curves changing from the tools panel."""
        self._image_controller.on_curve_changed(points, channel=channel)
        self._adjustment_persist_timer.start()

    def _on_hsl_changed(self, values: dict):
        """Handle HSL Color Mixer changes from the tools panel."""
        self._image_controller.on_hsl_changed(values)
        self._adjustment_persist_timer.start()

    def _on_color_grading_changed(self, values: dict):
        """Handle Color Grading changes from the tools panel."""
        self._image_controller.on_color_grading_changed(values)
        self._adjustment_persist_timer.start()

    def _on_slider_released(self):
        """Handle slider released - trigger final processing."""
        self._image_controller.on_slider_released()
        self._adjustment_persist_timer.start()
        self._refresh_curve_histogram()

    def _refresh_curve_histogram(self) -> None:
        """Refresh the tone curve's histogram backdrop from the current image.

        Uses whatever ``ImageController.get_current_image()`` currently
        holds, which may be an interactive-tier preview frame rather than
        the final full-resolution render immediately after a release -- an
        intentional simplification (see
        docs/planning/implementation-notes/2026-09-29-tone-curve.md section
        5) to avoid a full-image histogram pass on every settle event.
        """
        if not self._image_controller.has_image():
            return
        image = self._image_controller.get_current_image()
        if image is None:
            return
        # A 256-bin histogram is stable from ~0.25 MP; subsample so a
        # full-resolution frame can't stall the UI thread (it cost ~100 ms
        # on every photo open).
        step = max(1, int(round((image.shape[0] * image.shape[1] / 250_000) ** 0.5)))
        if step > 1:
            image = image[::step, ::step]
        histogram = compute_luminance_histogram(image)
        self._tools_panel.update_curve_histogram(histogram)
        self._tools_panel.update_histogram(image)

    def _on_library_image_selected(self, file_path: str):
        """Handle image selection from library."""
        self._persist_current_adjustments()
        self._prepare_pending_image_state(
            self._library_controller.current_library_id,
            file_path,
        )
        self._image_controller.load_image_async(
            file_path,
            self,
            show_intermediate_preview=not self._show_cached_preview_if_available(),
        )

    def _on_library_selected(self, library_id: str) -> None:
        """Persist current edits before switching library context."""
        self._persist_current_adjustments()
        self._library_controller.select_library(library_id)

    def _on_thumbnail_batch_started(self, total: int) -> None:
        """Show status-bar progress while library thumbnails load."""
        self._thumb_import_progress.setMaximum(max(1, total))
        self._thumb_import_progress.setValue(0)
        self._thumb_import_count_label.setText(f"0 / {total}")
        self._thumb_import_cancel.setEnabled(True)
        self._thumb_import_container.setVisible(True)

    def _on_thumbnail_import_cancel(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Cancel Thumbnail Import?",
            "Stop generating thumbnails for the remaining images?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._library_controller.cancel_thumbnail_batch()
        self._thumb_import_cancel.setEnabled(False)

    def _on_thumbnail_batch_progress(self, current: int, total: int) -> None:
        self._thumb_import_progress.setMaximum(max(1, total))
        self._thumb_import_progress.setValue(current)
        self._thumb_import_count_label.setText(f"{current} / {total}")

    def _on_thumbnail_batch_finished(self) -> None:
        self._thumb_import_container.setVisible(False)
        self._thumb_import_progress.setValue(0)
        self._thumb_import_count_label.setText("0 / 0")
        self._status_bar.showMessage("Ready", 2000)

    def _on_image_load_started(self, file_path: str) -> None:
        """Show loading feedback while the image decodes."""
        self._image_view.set_loading(True)
        self._status_bar.showMessage(f"Loading: {file_path}")
        self._tools_panel.set_enabled(False)

    def _on_image_preview_ready(self, file_path: str) -> None:
        """Show that a fast preview is visible while full decode continues."""
        self._status_bar.showMessage(f"Preview loaded; decoding full image: {file_path}")

    def _on_image_load_finished(self, file_path: str, success: bool) -> None:
        """Handle completion of asynchronous image loading."""
        if not success:
            self._status_bar.showMessage(f"Failed to load: {file_path}", 4000)
            if self._pending_library_add_path == file_path:
                self._pending_library_add_path = None
            self._pending_image_library_id = None
            self._pending_adjustment_payload = None
            self._pending_zoom_factor = None
            self._image_view.set_loading(False)
            return

        if self._pending_library_add_path == file_path:
            self._library_controller.add_image(file_path)
            self._pending_library_add_path = None
        self._current_image_library_id = (
            self._pending_image_library_id or self._library_controller.current_library_id
        )
        adjustments = self._adjustment_values_from_payload(
            self._pending_adjustment_payload
        )
        self._pending_image_library_id = None
        self._pending_adjustment_payload = None
        self._tools_panel.set_adjustments(adjustments, emit_signal=False)
        self._image_controller.restore_adjustment_state(adjustments)
        # Image switches always start fitted. Per-image zoom persistence made
        # navigation appear random (a previously saved 100% view reopened at
        # full size), while preview/full swaps also queued competing fit calls.
        # Guard the single final callback by path so a stale load can never
        # resize the next image.
        QTimer.singleShot(0, lambda path=file_path: self._fit_image_if_current(path))
        self._pending_zoom_factor = None
        self._image_view.set_loading(False)
        self._settings_service.set_current_image_path(file_path)
        self._settings_service.sync()
        self._refresh_curve_histogram()

    def _fit_image_if_current(self, file_path: str) -> None:
        if self._image_controller.image_model.file_path != file_path:
            return
        self._image_view.fit_to_window()

    def _on_create_library_requested(self, default_name: str) -> None:
        self._persist_current_adjustments()
        name, accepted = QInputDialog.getText(
            self,
            "Create Library",
            "Library name:",
            text=default_name,
        )
        if not accepted:
            return
        self._library_controller.create_library(name)

    def _on_remove_library_requested(self, library_id: str) -> None:
        self._persist_current_adjustments()
        name = self._library_controller.get_library_name(library_id)
        confirm = QMessageBox.question(
            self,
            "Remove Library?",
            f"Remove library '{name}'? Original image files will not be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._library_controller.remove_library(library_id)

    def _on_remove_entry_requested(self, file_path: str, delete_from_disk: bool) -> None:
        """Handle a single-image "Remove Photo.../Delete from Disk"
        request -- already confirmed by ``FilmstripView``'s own 3-way
        dialog by the time this fires."""
        self._clear_current_image_if_removed([file_path])
        self._library_controller.remove_entry(file_path, delete_from_disk)

    def _on_remove_entries_requested(
        self, file_paths: list, delete_from_disk: bool
    ) -> None:
        """Batch counterpart of ``_on_remove_entry_requested``."""
        self._clear_current_image_if_removed(file_paths)
        self._library_controller.remove_entries(file_paths, delete_from_disk)

    def _clear_current_image_if_removed(self, removed_paths: list) -> None:
        """If the image currently open in the editor is one of
        ``removed_paths``, reset the editor to its own "no image loaded"
        state BEFORE the library controller removes/deletes it.

        Reuses ``ImageController.clear_image()`` -- the exact state the
        app is already in right after startup with an empty library,
        before any image has ever been loaded -- rather than inventing a
        new empty-state UI. Does not persist the about-to-be-removed
        image's adjustments first (unlike most other library mutations in
        this file): that state is being discarded along with the entry
        itself, so writing it back to the catalog first would be pure
        waste.
        """
        current_path = self._image_controller.image_model.file_path
        if not current_path or current_path not in removed_paths:
            return
        self._image_controller.clear_image()
        self._tools_panel.set_enabled(False)
        self._settings_service.set_current_image_path("")
        self._settings_service.sync()
        self._status_bar.showMessage("Photo removed", 2000)

    # Menu action handlers
    def _open_image(self):
        """Handle open image action."""
        start_dir = self._settings_service.get_last_open_dir()
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Image",
            start_dir,
            open_image_file_dialog_filter()
        )
        if not file_path:
            return

        self._settings_service.set_last_open_dir(file_path)
        self._persist_current_adjustments()
        self._pending_library_add_path = file_path
        self._prepare_pending_image_state(
            self._library_controller.current_library_id,
            file_path,
        )
        self._image_controller.load_image_async(
            file_path,
            self,
            show_intermediate_preview=not self._show_cached_preview_if_available(),
        )

    def _import_images(self):
        """Handle import images action."""
        start_dir = self._settings_service.get_last_open_dir()
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Images",
            start_dir,
            open_image_file_dialog_filter()
        )
        
        if file_paths:
            self._settings_service.set_last_open_dir(file_paths[0])
            self._library_controller.import_images(file_paths)
            self._status_bar.showMessage(
                f"Importing {len(file_paths)} images…", 5000
            )

    def _export_image(self):
        """Handle export image action."""
        if not self._image_controller.has_image():
            self._status_bar.showMessage("No image to export", 2000)
            return
        
        # Start the full-resolution render in the background now; the
        # dialog opens immediately and Export waits for it only if the user
        # is faster than the render. (It used to render synchronously here,
        # freezing the window before the dialog appeared.)
        render = self._image_controller.start_export_render()
        output_size = self._image_controller.get_output_size()
        if render is None or output_size is None:
            self._status_bar.showMessage("No image to export", 2000)
            return

        # Get default path from current file
        default_path = self._image_controller.image_model.file_path or ""
        if default_path:
            from pathlib import Path
            p = Path(default_path)
            default_path = str(p.parent / f"{p.stem}_edited{p.suffix}")
        
        # If we have no source path, seed default location with the
        # last-used export directory so the dialog is not empty.
        if not default_path:
            from pathlib import Path

            default_path = str(Path(self._settings_service.get_last_export_dir()))

        # Show export dialog
        dialog = ExportDialog(
            default_path=default_path,
            settings_service=self._settings_service,
            parent=self,
            render=render,
            image_size=output_size,
        )
        if dialog.exec():
            export_path = dialog.get_export_path()
            if export_path:
                self._settings_service.set_last_export_dir(export_path)
            self._status_bar.showMessage(f"Exported to: {export_path}", 3000)

    def _export_with_previous(self):
        """Repeat the last-used export settings without opening the dialog.

        Mirrors Lightroom's File > Export with Previous: re-runs the most
        recently used export options (format/quality/resize/preserve
        aspect) immediately. When no previous export has ever completed,
        there is nothing to repeat, so this falls back to the normal
        ``_export_image`` flow (which opens the dialog) -- that is the
        intended UX, not a bug.
        """
        if not self._image_controller.has_image():
            self._status_bar.showMessage("No image to export", 2000)
            return

        # Get default path from current file (same logic as _export_image).
        default_path = self._image_controller.image_model.file_path or ""
        if default_path:
            p = Path(default_path)
            default_path = str(p.parent / f"{p.stem}_edited{p.suffix}")

        if not default_path:
            default_path = str(Path(self._settings_service.get_last_export_dir()))

        options = self._settings_service.get_last_export_options()
        if options is None:
            # No previous export to repeat; fall back to the normal
            # Export dialog flow.
            self._status_bar.showMessage(
                "No previous export settings; opening Export dialog...", 2000
            )
            self._export_image()
            return

        if not confirm_overwrite_if_needed(self, default_path, self._settings_service):
            self._status_bar.showMessage("Export cancelled", 2000)
            return

        width = options.get("width")
        height = options.get("height")
        resize = (width, height) if width is not None and height is not None else None

        export_service = ExportService()

        def write(image):
            return export_service.export_image(
                image,
                default_path,
                format=options.get("format"),
                quality=options.get("quality"),
                resize=resize,
                preserve_aspect=options.get("preserve_aspect", True),
            )

        # Render and write entirely in the background; the user can keep
        # editing (the edit was snapshotted when the export started).
        task = self._image_controller.start_export_render(post=write)
        if task is None:
            self._status_bar.showMessage("No image to export", 2000)
            return
        self._export_tasks.append(task)
        self._status_bar.showMessage(f"Exporting {Path(default_path).name}…")

        def finished(success):
            self._export_tasks.remove(task)
            if success:
                self._settings_service.set_last_export_dir(default_path)
                self._status_bar.showMessage(f"Exported to: {default_path}", 3000)
            else:
                QMessageBox.critical(self, "Export Failed", "Failed to export image.")

        def failed(message):
            self._export_tasks.remove(task)
            QMessageBox.critical(self, "Export Failed", f"Failed to export image: {message}")

        task.finished.connect(finished)
        task.failed.connect(failed)

    def _undo(self):
        """Handle undo action."""
        if self._image_controller.can_undo():
            self._image_controller.undo()
            self._status_bar.showMessage("Undo", 1000)
        else:
            self._status_bar.showMessage("Nothing to undo", 1000)

    def _redo(self):
        """Handle redo action."""
        if self._image_controller.can_redo():
            self._image_controller.redo()
            self._status_bar.showMessage("Redo", 1000)
        else:
            self._status_bar.showMessage("Nothing to redo", 1000)

    def _on_adjustment_state_restored(self, state: dict) -> None:
        """Resync the ToolsPanel UI and persist to the catalog after an
        undo/redo (or any other) call to ImageController.apply_history_state.

        Mirrors ``_reset_adjustments``/``_paste_edit_settings``/
        ``_apply_profile``'s exact "replace the current image's entire
        adjustment state" UI-sync pattern.

        Also refreshes the status-bar dimensions label from the now-current
        image's actual shape. This fixes the gap flagged in slice 1 (see
        docs/planning/implementation-notes/2026-10-13-crop-processor.md
        section 2/6): the label was previously set once, at image load, and
        never refreshed on a later shape-changing edit -- which, before
        this slice, only Crop could cause, and Crop was unreachable from
        the UI. ``apply_history_state`` (the only emitter of
        ``adjustment_state_restored``) already assigns the new image to
        ``current_image`` before emitting, so reading it here is current.
        """
        self._tools_panel.set_adjustments(state, emit_signal=False)
        self._adjustment_persist_timer.start()
        # current_image may be a preview proxy; report the real output size.
        output_size = self._image_controller.get_output_size()
        if output_size is not None:
            width, height = output_size
            self._dimensions_label.setText(f"{width} × {height}")
            self._megapixels_label.setText(f"{(width * height) / 1_000_000:.1f} MP")

    def _enter_crop_mode(self) -> None:
        """Show the interactive crop overlay over the full, uncropped image.

        Uses ``get_export_image(apply_crop=False)`` so a previously
        committed crop does not hide the rest of the frame while the user
        is re-adjusting it. This is a v1 simplification worth noting: it
        fetches a full-resolution image on every crop-mode entry, which
        could be slow for a very large source image -- see
        docs/planning/implementation-notes/2026-10-13-crop-tool-ui.md.
        """
        if not self._image_controller.has_image():
            self._status_bar.showMessage("No image to crop", 2000)
            return
        # Crop/Mask/Heal can never be simultaneously active -- see
        # _exit_any_interactive_tool_mode's own docstring and
        # docs/planning/implementation-notes/2026-10-13-healing-tool-ui.md
        # section 5 (extending the Crop/Mask pairwise check this slice's
        # predecessor established into a three-way shared helper).
        self._exit_any_interactive_tool_mode()
        state = self._image_controller.get_adjustment_state()
        self._pre_crop_mode_adjustment_state = state
        crop = state.get("crop") or {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
        size = self._image_controller.preview_uncropped()
        if size is None:
            return
        self._image_view.enter_crop_mode(crop)
        overlay = self._image_view.get_crop_overlay()
        width, height = size
        self._crop_toolbar.set_original_ratio(width / height if height else None)
        self._crop_toolbar.reset_to_free()
        if overlay is not None:
            overlay.set_locked_aspect(None)
        self._sync_tool_ui()

    def _apply_crop(self) -> None:
        """Commit the overlay's current rectangle via on_crop_changed."""
        before = self._image_controller.get_adjustment_state()
        overlay = self._image_view.get_crop_overlay()
        if overlay is not None:
            rect = overlay.get_rect()
            self._image_controller.on_crop_changed(rect)
        self._image_view.exit_crop_mode()
        self._sync_tool_ui()
        self._pre_crop_mode_adjustment_state = None
        # Only announce a real change (switching tools also commits).
        if self._image_controller.get_adjustment_state() != before:
            self._status_bar.showMessage("Crop applied", 2000)

    def _cancel_crop(self) -> None:
        """Exit crop mode without changing the committed crop state."""
        self._image_view.exit_crop_mode()
        self._sync_tool_ui()
        self._pre_crop_mode_adjustment_state = None
        self._image_controller.refresh_view()

    def _on_crop_aspect_ratio_changed(self, ratio) -> None:
        overlay = self._image_view.get_crop_overlay()
        if overlay is not None:
            overlay.set_locked_aspect(ratio)

    # -- Mask mode ----------------------------------------------------------

    def _enter_mask_mode(self) -> None:
        """Show the interactive mask overlay+toolbar over the current image.

        Unlike crop mode, the canvas keeps showing whatever it is already
        showing (the normal, fully-adjusted image, including any prior
        committed mask) -- no uncropped-style image swap is needed; see
        docs/planning/implementation-notes/2026-10-13-mask-tool-ui.md
        section 3.5.
        """
        if not self._image_controller.has_image():
            self._status_bar.showMessage("No image to mask", 2000)
            return
        # Crop/Mask/Heal can never be simultaneously active -- see
        # _exit_any_interactive_tool_mode.
        self._exit_any_interactive_tool_mode()

        state = self._image_controller.get_adjustment_state()
        mask = state.get("mask") or {}
        mask_type = mask.get("type", "linear")
        invert = bool(mask.get("invert", False))
        exposure = mask.get("exposure", 0.0)
        contrast = mask.get("contrast", 0.0)
        saturation = mask.get("saturation", 0.0)
        clarity = mask.get("clarity", 0.0)

        self._image_view.enter_mask_mode(mask_type, mask)
        overlay = self._image_view.get_mask_overlay()
        if overlay is not None and not self._mask_overlay_signal_connected:
            overlay.geometry_changed.connect(self._on_mask_editing_changed)
            self._mask_overlay_signal_connected = True

        self._mask_toolbar.set_values(
            mask_type, invert, exposure, contrast, saturation, clarity
        )
        self._sync_tool_ui()

    def _apply_mask(self) -> None:
        """Commit the overlay's geometry + toolbar's adjustments via
        ``on_mask_changed`` -- the ONE real, committed, undoable edit."""
        before = self._image_controller.get_adjustment_state()
        overlay = self._image_view.get_mask_overlay()
        if overlay is not None:
            mask = overlay.get_geometry()
            mask.update(self._mask_toolbar.get_adjustments())
            self._image_controller.on_mask_changed(mask)
        self._image_view.exit_mask_mode()
        self._sync_tool_ui()
        # Only announce a real change (switching tools also commits).
        if self._image_controller.get_adjustment_state() != before:
            self._status_bar.showMessage("Mask applied", 2000)

    def _cancel_mask(self) -> None:
        """Exit mask mode without committing.

        Nothing was ever mutated on the committed engine state while
        editing (see ``_on_mask_editing_changed``/
        ``ImageController.preview_mask``), so cancelling only needs to
        hide the overlay/toolbar and ask the controller to re-display
        whatever image is still actually current -- there is no stray
        preview-mode state to roll back.
        """
        self._image_view.exit_mask_mode()
        self._sync_tool_ui()
        self._image_controller.refresh_view()

    def _remove_mask(self) -> None:
        """Commit clearing the mask (``on_mask_changed(None)``) and exit."""
        self._image_controller.on_mask_changed(None)
        self._image_view.exit_mask_mode()
        self._sync_tool_ui()
        self._status_bar.showMessage("Mask removed", 2000)

    def _on_mask_type_changed(self, mask_type: str) -> None:
        overlay = self._image_view.get_mask_overlay()
        if overlay is not None:
            overlay.set_mask_type(mask_type)
        self._on_mask_editing_changed()

    def _on_mask_invert_changed(self, invert: bool) -> None:
        overlay = self._image_view.get_mask_overlay()
        if overlay is not None:
            overlay.set_invert(invert)
        self._on_mask_editing_changed()

    def _on_mask_adjustments_changed(self, _adjustments: dict) -> None:
        self._on_mask_editing_changed()

    def _on_mask_editing_changed(self, *_args) -> None:
        """Live-preview the CURRENT in-progress mask candidate.

        Assembles geometry (from the overlay) + adjustments (from the
        toolbar) and hands the result to
        ``ImageController.preview_mask`` -- a display-only call that never
        touches history or the committed mask state. See
        docs/planning/implementation-notes/2026-10-13-mask-tool-ui.md
        section 3.5 for why this, and not ``on_mask_changed``, is used
        here.
        """
        overlay = self._image_view.get_mask_overlay()
        if overlay is None:
            return
        candidate = overlay.get_geometry()
        candidate.update(self._mask_toolbar.get_adjustments())
        self._image_controller.preview_mask(candidate)

    # -- Crop/Mask/Heal three-way mutual exclusion --------------------------

    def _exit_any_interactive_tool_mode(self) -> None:
        """Close whichever of Crop/Mask/Heal is active, keeping its edit.

        Crop, Mask, and Heal can never be simultaneously active. Each
        ``_enter_X_mode`` calls this first. Like Lightroom, picking another
        tool commits the current one (same as its Done button); only
        Cancel or Esc discards.
        """
        if self._image_view.is_in_crop_mode():
            self._apply_crop()
        if self._image_view.is_in_mask_mode():
            self._apply_mask()
        if self._image_view.is_in_healing_mode():
            self._apply_healing()

    def _active_tool(self):
        """"crop", "heal", "mask" or None, from the image view's mode."""
        if self._image_view.is_in_crop_mode():
            return "crop"
        if self._image_view.is_in_healing_mode():
            return "heal"
        if self._image_view.is_in_mask_mode():
            return "mask"
        return None

    def _sync_tool_ui(self) -> None:
        """Show the active tool's drawer page and highlight its strip button."""
        self._tools_panel.set_active_tool(self._active_tool())

    def _toggle_tool(self, tool: str) -> None:
        """Strip button / shortcut: open ``tool``, or close it (Done) if it
        is already active -- Lightroom's click-again behaviour."""
        if self._active_tool() == tool:
            {"crop": self._apply_crop, "heal": self._apply_healing,
             "mask": self._apply_mask}[tool]()
            return
        {"crop": self._enter_crop_mode, "heal": self._enter_healing_mode,
         "mask": self._enter_mask_mode}[tool]()
        self._sync_tool_ui()

    def _cancel_active_tool(self) -> None:
        """Esc: discard the active tool's uncommitted edit."""
        tool = self._active_tool()
        if tool is not None:
            {"crop": self._cancel_crop, "heal": self._cancel_healing,
             "mask": self._cancel_mask}[tool]()

    # -- Healing mode ---------------------------------------------------------

    def _enter_healing_mode(self) -> None:
        """Show the interactive healing overlay+toolbar over the current
        image.

        Mirrors ``_enter_mask_mode`` exactly: like Mask (and unlike Crop),
        the canvas keeps showing whatever it is already showing -- no
        image swap is needed, since the live-preview mechanism
        (``ImageController.preview_heal_spots``) shows exactly the
        in-progress candidate's effect. See docs/planning/
        implementation-notes/2026-10-13-healing-tool-ui.md.
        """
        if not self._image_controller.has_image():
            self._status_bar.showMessage("No image to heal", 2000)
            return
        # Crop/Mask/Heal can never be simultaneously active.
        self._exit_any_interactive_tool_mode()

        state = self._image_controller.get_adjustment_state()
        heal_spots = state.get("heal_spots") or []

        self._image_view.enter_healing_mode(heal_spots)
        overlay = self._image_view.get_healing_overlay()
        if overlay is not None and not self._healing_overlay_signal_connected:
            overlay.spots_changed.connect(self._on_heal_editing_changed)
            self._healing_overlay_signal_connected = True

        self._healing_toolbar.set_values("heal", 0.3, 1.0)
        if overlay is not None:
            overlay.set_pending_mode("heal")
            overlay.set_pending_feather(0.3)
            overlay.set_pending_opacity(1.0)
        self._sync_tool_ui()

    def _apply_healing(self) -> None:
        """Commit the overlay's full spot list via ``on_heal_spots_changed``
        -- the ONE real, committed, undoable edit."""
        before = self._image_controller.get_adjustment_state()
        overlay = self._image_view.get_healing_overlay()
        if overlay is not None:
            self._image_controller.on_heal_spots_changed(overlay.get_spots())
        self._image_view.exit_healing_mode()
        self._sync_tool_ui()
        # Only announce a real change (switching tools also commits).
        if self._image_controller.get_adjustment_state() != before:
            self._status_bar.showMessage("Healing applied", 2000)

    def _cancel_healing(self) -> None:
        """Exit healing mode without committing.

        Nothing was ever mutated on the committed engine state while
        editing (see ``_on_heal_editing_changed``/
        ``ImageController.preview_heal_spots``), so cancelling only needs
        to hide the overlay/toolbar and ask the controller to re-display
        whatever image is still actually current -- mirrors
        ``_cancel_mask``'s own trivial simplicity exactly.
        """
        self._image_view.exit_healing_mode()
        self._sync_tool_ui()
        self._image_controller.refresh_view()

    def _on_heal_remove_last(self) -> None:
        overlay = self._image_view.get_healing_overlay()
        if overlay is not None:
            overlay.remove_last()

    def _on_heal_clear_all(self) -> None:
        overlay = self._image_view.get_healing_overlay()
        if overlay is not None:
            overlay.clear_all()

    def _on_heal_mode_changed(self, mode: str) -> None:
        overlay = self._image_view.get_healing_overlay()
        if overlay is not None:
            overlay.set_pending_mode(mode)
        # Per spec, every toolbar pending-value-change signal also drives
        # the live-preview path, even though a mode/feather/opacity change
        # by itself only affects the NEXT spot placed (not any already-
        # placed spot) -- see docs/planning/implementation-notes/
        # 2026-10-13-healing-tool-ui.md. Harmless (and correctly a no-op
        # on the displayed image) when nothing is placed yet.
        self._on_heal_editing_changed()

    def _on_heal_feather_changed(self, feather: float) -> None:
        overlay = self._image_view.get_healing_overlay()
        if overlay is not None:
            overlay.set_pending_feather(feather)
        self._on_heal_editing_changed()

    def _on_heal_opacity_changed(self, opacity: float) -> None:
        overlay = self._image_view.get_healing_overlay()
        if overlay is not None:
            overlay.set_pending_opacity(opacity)
        self._on_heal_editing_changed()

    def _on_heal_editing_changed(self, *_args) -> None:
        """Live-preview the CURRENT in-progress heal-spot list.

        Wired to the overlay's ``spots_changed`` signal (emitted on a new
        spot placement, Remove Last, or Clear All). Hands the overlay's
        full in-progress list to
        ``ImageController.preview_heal_spots`` -- a display-only call
        that never touches history or the committed heal-spot state. See
        docs/planning/implementation-notes/2026-10-13-healing-tool-ui.md.
        """
        overlay = self._image_view.get_healing_overlay()
        if overlay is None:
            return
        self._image_controller.preview_heal_spots(overlay.get_spots())

    def _reset_adjustments(self):
        """Handle reset adjustments action."""
        if self._image_controller.has_image():
            self._tools_panel.set_adjustments({}, emit_signal=False)
            self._image_controller.restore_adjustment_state({})
            self._adjustment_persist_timer.start()
            self._status_bar.showMessage("Reset to original", 2000)

    def _copy_edit_settings(self):
        """Handle copy edit settings action.

        Captures the current image's full adjustment-state dict (the same
        JSON-plain shape ``LibraryCatalogService`` already persists per
        image) into the single in-memory clipboard slot.
        """
        if self._image_controller.has_image():
            self._copied_adjustment_state = self._image_controller.get_adjustment_state()
            self._status_bar.showMessage("Copied edit settings", 2000)
        else:
            self._status_bar.showMessage("No image to copy edit settings from", 2000)

    def _paste_edit_settings(self):
        """Handle paste edit settings action.

        Mirrors ``_reset_adjustments``'s exact "replace the current image's
        entire adjustment state" pattern, but with the copied state instead
        of ``{}``. A deep copy is passed downstream (rather than the stored
        clipboard dict itself) so that neither ``ToolsPanel.set_adjustments``
        nor ``ImageController.restore_adjustment_state`` can leave the
        clipboard corrupted for a later paste onto a different image --
        see the implementation note for what was found by inspection about
        whether either call actually mutates its input.
        """
        if not self._image_controller.has_image():
            self._status_bar.showMessage("No image to paste edit settings to", 2000)
            return
        if self._copied_adjustment_state is None:
            self._status_bar.showMessage(
                "Nothing to paste; copy edit settings first", 2000
            )
            return

        state_for_tools_panel = copy.deepcopy(self._copied_adjustment_state)
        state_for_controller = copy.deepcopy(self._copied_adjustment_state)
        self._tools_panel.set_adjustments(state_for_tools_panel, emit_signal=False)
        self._image_controller.restore_adjustment_state(state_for_controller)
        self._adjustment_persist_timer.start()
        self._status_bar.showMessage("Pasted edit settings", 2000)

    def _apply_profile(self, profile_name: str):
        """Apply a built-in profile's preset adjustment values.

        This is a preset-apply action, not a persistent separate pipeline
        stage -- see docs/planning/implementation-notes/
        2026-10-13-profile-selector.md section 1 for the honest scope
        boundary against real Lightroom Profiles. It mirrors
        ``_paste_edit_settings``'s exact "replace the current image's
        entire adjustment state" pattern, with ``BUILTIN_PROFILES``
        treated as a second clipboard-like source deserving the same
        defensive-copy treatment (two independent ``copy.deepcopy`` calls,
        never the stored profile dict itself).
        """
        if not self._image_controller.has_image():
            self._status_bar.showMessage("No image to apply a profile to", 2000)
            return
        profile_state = BUILTIN_PROFILES.get(profile_name)
        if profile_state is None:
            self._status_bar.showMessage(f"Unknown profile: {profile_name}", 2000)
            return

        state_for_tools_panel = copy.deepcopy(profile_state)
        state_for_controller = copy.deepcopy(profile_state)
        self._tools_panel.set_adjustments(state_for_tools_panel, emit_signal=False)
        self._image_controller.restore_adjustment_state(state_for_controller)
        self._adjustment_persist_timer.start()
        self._status_bar.showMessage(f"Applied profile: {profile_name}", 2000)

    def _export_preset(self) -> None:
        """Export the current image's adjustment state as a preset file.

        Single-file export of one user-authored preset (analogous to
        saving a Lightroom .xmp preset) -- NOT a browsable, persistent
        preset library. See docs/planning/implementation-notes/
        2026-10-13-import-export-presets.md section 1 for the full scope
        boundary. Reuses ``ImageController.get_adjustment_state()`` --
        the same whole-state dict used by Copy Edit Settings and already
        persisted per image -- wrapped in a small versioned JSON envelope.
        """
        if not self._image_controller.has_image():
            self._status_bar.showMessage("No image to export a preset from", 2000)
            return

        default_name = "preset.json"
        source_path = self._image_controller.image_model.file_path or ""
        if source_path:
            default_name = f"{Path(source_path).stem}_preset.json"
        start_dir = self._settings_service.get_last_preset_dir()
        default_path = str(Path(start_dir) / default_name)

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Preset", default_path, PRESET_FILE_FILTER
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"

        if not confirm_overwrite_if_needed(self, path, self._settings_service):
            self._status_bar.showMessage("Export preset cancelled", 2000)
            return

        preset_name = Path(path).stem
        envelope = {
            "photoedit_preset_version": PRESET_FILE_VERSION,
            "name": preset_name,
            "adjustments": self._image_controller.get_adjustment_state(),
        }

        try:
            Path(path).write_text(json.dumps(envelope, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to write preset file %s: %s", path, exc)
            QMessageBox.critical(
                self, "Export Preset Failed", f"Failed to write preset file:\n{exc}"
            )
            return

        self._settings_service.set_last_preset_dir(path)
        self._status_bar.showMessage(f"Exported preset: {preset_name}", 2000)

    def _import_preset(self) -> None:
        """Import a preset file and apply it to the current image.

        Mirrors ``_apply_profile``/``_paste_edit_settings``'s exact
        "replace the current image's entire adjustment state" pattern,
        with a user-chosen preset file as the source instead of a
        built-in profile or the in-memory clipboard. The file's content
        is arbitrary, user-supplied data -- every parsing/validation step
        below is defensive and reports a clear message rather than
        letting a malformed file crash the app or partially apply.
        """
        if not self._image_controller.has_image():
            self._status_bar.showMessage("No image to apply a preset to", 2000)
            return

        start_dir = self._settings_service.get_last_preset_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Preset", start_dir, PRESET_FILE_FILTER
        )
        if not path:
            return

        try:
            raw_text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read preset file %s: %s", path, exc)
            QMessageBox.critical(
                self, "Import Preset Failed", f"Failed to read preset file:\n{exc}"
            )
            return

        try:
            envelope = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError) as exc:
            QMessageBox.warning(
                self,
                "Import Preset Failed",
                f"This file is not a valid preset (not valid JSON):\n{exc}",
            )
            return

        if not isinstance(envelope, dict):
            QMessageBox.warning(
                self,
                "Import Preset Failed",
                "This file is not a valid preset (expected a JSON object).",
            )
            return

        version = envelope.get("photoedit_preset_version")
        if version != PRESET_FILE_VERSION:
            if isinstance(version, int) and version > PRESET_FILE_VERSION:
                message = (
                    "This preset was made with a newer version of PhotoEdit "
                    "and cannot be imported here."
                )
            else:
                message = "This file is not a recognized PhotoEdit preset."
            QMessageBox.warning(self, "Import Preset Failed", message)
            return

        adjustments = envelope.get("adjustments")
        if not isinstance(adjustments, dict):
            QMessageBox.warning(
                self,
                "Import Preset Failed",
                "This preset file is missing its adjustment data.",
            )
            return

        preset_name = envelope.get("name")
        if not isinstance(preset_name, str) or not preset_name:
            preset_name = Path(path).stem

        state_for_tools_panel = copy.deepcopy(adjustments)
        state_for_controller = copy.deepcopy(adjustments)
        self._tools_panel.set_adjustments(state_for_tools_panel, emit_signal=False)
        self._image_controller.restore_adjustment_state(state_for_controller)
        self._adjustment_persist_timer.start()
        self._settings_service.set_last_preset_dir(path)
        self._status_bar.showMessage(f"Imported preset: {preset_name}", 2000)

    def _show_preferences(self) -> None:
        """Open the Preferences dialog."""
        dialog = PreferencesDialog(
            settings_service=self._settings_service, parent=self
        )
        if dialog.exec():
            self._status_bar.showMessage(
                "Preferences saved (preview size changes apply after restart)",
                3000,
            )

    def _fit_to_window(self):
        """Handle fit to window action."""
        self._image_controller.fit_to_window()

    def _view_100_percent(self):
        """Handle 100% view action."""
        self._image_controller.view_100_percent()

    def _zoom_in(self):
        """Handle zoom in action."""
        self._image_controller.zoom_in()

    def _zoom_out(self):
        """Handle zoom out action."""
        self._image_controller.zoom_out()

    def _next_photo(self) -> None:
        """Advance to the next photo in the filmstrip's currently displayed
        (filtered/sorted/searched) order. Routes through
        ``FilmstripView.select_next()``, which moves the list's current
        row and relies on the existing ``currentItemChanged`` ->
        ``image_selected`` -> ``_on_library_image_selected`` path to load
        the image -- the exact same path a filmstrip click already uses.
        No wraparound: at the last photo, just show a status message
        (matching Lightroom's own non-wrapping behavior).
        """
        if not self._filmstrip_view.select_next():
            self._status_bar.showMessage("Already at the last photo", 2000)

    def _previous_photo(self) -> None:
        """Mirror of ``_next_photo`` -- moves to the previous photo."""
        if not self._filmstrip_view.select_previous():
            self._status_bar.showMessage("Already at the first photo", 2000)

    def _toggle_library_panel(self):
        """Toggle library panel visibility."""
        self.library_dock.setVisible(not self.library_dock.isVisible())

    def _toggle_tools_panel(self):
        """Toggle tools panel visibility."""
        self.tools_dock.setVisible(not self.tools_dock.isVisible())

    def _on_workspace_changed(self, workspace: str) -> None:
        """Switch between browsing-focused and editing-focused shell layouts."""
        self.library_dock.setVisible(True)
        self.tools_dock.setVisible(workspace == "develop")

    def _show_about(self) -> None:
        """Show a compact product description without external navigation."""
        QMessageBox.about(
            self,
            "About PhotoEdit",
            "<b>PhotoEdit</b><br>"
            "A focused, non-destructive photo editing workspace built with PyQt6.",
        )

    def _restore_window_geometry(self) -> None:
        """Restore window size and position from settings (if any)."""
        try:
            blob = self._settings_service.get_window_geometry()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to read window geometry from settings")
            return
        if not blob:
            return
        try:
            self.restoreGeometry(QByteArray(blob))
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to restore window geometry; using defaults")

    def _restore_window_state(self) -> None:
        """Restore dock sizes/visibility from settings (if any)."""
        try:
            blob = self._settings_service.get_window_state()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to read window state from settings")
            return
        if not blob:
            return
        try:
            self.restoreState(QByteArray(blob))
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to restore window state; using defaults")

    def _save_window_geometry(self) -> None:
        """Persist current window size and position to settings."""
        try:
            blob = bytes(self.saveGeometry())
            self._settings_service.set_window_geometry(blob)
            self._settings_service.sync()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to save window geometry")

    def _save_window_state(self) -> None:
        """Persist dock sizes, positions, and visibility."""
        try:
            blob = bytes(self.saveState())
            self._settings_service.set_window_state(blob)
            self._settings_service.sync()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to save window state")

    def _restore_last_session_image(self) -> None:
        """Reopen the last image from the previous session when possible."""
        last_path = self._settings_service.get_current_image_path()
        if not last_path:
            return
        self._prepare_pending_image_state(
            self._library_controller.current_library_id,
            last_path,
        )
        self._image_controller.load_image_async(
            last_path,
            self,
            show_intermediate_preview=not self._show_cached_preview_if_available(),
        )

    def _adjustment_values_from_payload(
        self, payload: Optional[dict]
    ) -> dict:
        if not isinstance(payload, dict):
            return {}
        values = payload.get("values", {})
        if not isinstance(values, dict):
            return {}
        # NOTE: this whitelist previously omitted highlights/shadows/whites/
        # blacks (never updated when that slice landed), so those sliders
        # silently reset to 0 on every library reload even though they were
        # correctly persisted to disk. Fixed here alongside adding
        # tone_curve -- see
        # docs/planning/implementation-notes/2026-09-29-tone-curve.md
        # section 2.
        return {
            "exposure": float(values.get("exposure", 0.0)),
            "contrast": float(values.get("contrast", 0.0)),
            "brightness": float(values.get("brightness", 0.0)),
            "highlights": float(values.get("highlights", 0.0)),
            "shadows": float(values.get("shadows", 0.0)),
            "whites": float(values.get("whites", 0.0)),
            "blacks": float(values.get("blacks", 0.0)),
            "temperature": float(values.get("temperature", 0.0)),
            "tint": float(values.get("tint", 0.0)),
            "saturation": float(values.get("saturation", 0.0)),
            "vibrance": float(values.get("vibrance", 0.0)),
            "tone_curve": values.get("tone_curve"),
            "tone_curve_red": values.get("tone_curve_red"),
            "tone_curve_green": values.get("tone_curve_green"),
            "tone_curve_blue": values.get("tone_curve_blue"),
            "hsl": values.get("hsl"),
            "color_grading": values.get("color_grading"),
        }

    def _zoom_factor_from_payload(self, payload: Optional[dict]) -> Optional[float]:
        if not isinstance(payload, dict):
            return None
        value = payload.get("zoom_factor")
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _preview_cache_key_from_payload(self, payload: Optional[dict]) -> Optional[str]:
        if not isinstance(payload, dict):
            return None
        value = payload.get("preview_cache_key")
        if not isinstance(value, str) or not value:
            return None
        return value

    def _prepare_pending_image_state(self, library_id: Optional[str], file_path: str) -> None:
        self._pending_image_library_id = library_id
        self._pending_adjustment_payload = self._library_controller.get_entry_adjustment_state(
            library_id or "",
            file_path,
        )
        self._pending_zoom_factor = self._zoom_factor_from_payload(
            self._pending_adjustment_payload
        )

    def _show_cached_preview_if_available(self) -> bool:
        cache_key = self._preview_cache_key_from_payload(self._pending_adjustment_payload)
        cached = self._image_preview_cache_service.load_qimage(cache_key)
        if cached is None:
            return False
        self._image_view.set_cached_preview_image(cached, None)
        QTimer.singleShot(0, self._image_view.fit_to_window)
        return True

    def _persist_current_adjustments(self) -> None:
        """Persist the current image's adjustment state to the owning library."""
        self._adjustment_persist_timer.stop()
        if not self._image_controller.has_image():
            return
        file_path = self._image_controller.image_model.file_path
        library_id = self._current_image_library_id
        if not file_path or not library_id:
            return

        values = self._image_controller.get_adjustment_state()
        entry = self._library_controller.get_entry(library_id, file_path)
        preview_cache_key = None
        current_image = self._image_controller.get_current_image()
        if entry is not None and current_image is not None:
            preview_cache_key = self._image_preview_cache_service.build_cache_key(
                entry.path,
                entry.last_seen_mtime_ns,
                entry.last_seen_size,
                values,
            )
            if preview_cache_key is not None:
                self._image_preview_cache_service.write_preview(
                    preview_cache_key,
                    current_image,
                )

        payload = {
            "version": 1,
            "values": values,
            "zoom_factor": self._image_controller.get_zoom_factor(),
            "preview_cache_key": preview_cache_key,
        }
        self._library_controller.set_entry_adjustment_state(
            library_id,
            file_path,
            payload,
        )
        self._settings_service.set_current_image_path(file_path)

    def closeEvent(self, event):
        """Handle window close event."""
        self._persist_current_adjustments()
        self._save_window_geometry()
        self._save_window_state()
        self._image_preview_cache_service.remove_orphaned_cache(
            self._library_controller.referenced_adjustment_preview_cache_keys()
        )
        self._settings_service.set_clean_shutdown(True)
        self._settings_service.sync()
        self._library_controller.cleanup()
        self._library_view.cleanup()
        # Clean up the image controller (stops background threads)
        self._image_controller.cleanup()
        super().closeEvent(event)
