"""Export renders and writes in the background.

The Export dialog used to wait for a synchronous full-resolution render
before it could open; now it opens immediately with the render running,
and only waits (with the window still painting) if Export is clicked
before the render is done.
"""

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image
from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import QApplication

from src.controllers.image_controller import ImageController
from src.processing.export_render import BackgroundTask
from src.services.settings_service import SettingsService
from src.views.export_dialog import ExportDialog
from src.views.image_view import ImageView


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def settings_service(tmp_path):
    return SettingsService(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))


def _gated_render(image):
    """A render that finishes only when ``gate`` is set."""
    gate = threading.Event()

    def run():
        gate.wait(5)
        return image

    return BackgroundTask(run).start(), gate


def test_dialog_opens_before_the_render_finishes(qapp, qtbot, settings_service):
    image = np.full((40, 60, 3), 0.5, dtype=np.float32)
    render, gate = _gated_render(image)

    dialog = ExportDialog(
        settings_service=settings_service, render=render, image_size=(60, 40)
    )
    qtbot.addWidget(dialog)

    assert not render.is_done()
    assert "Rendering" in dialog._render_status.text()
    assert dialog._width_spin.value() == 60 and dialog._height_spin.value() == 40

    gate.set()
    qtbot.waitUntil(render.is_done, timeout=3000)
    assert "ready" in dialog._render_status.text()


def test_export_clicked_early_waits_for_the_render_then_writes(
    qapp, qtbot, settings_service, tmp_path
):
    image = np.full((40, 60, 3), 0.5, dtype=np.float32)
    render, gate = _gated_render(image)
    out = tmp_path / "out.jpg"
    dialog = ExportDialog(
        default_path=str(out), settings_service=settings_service, render=render,
        image_size=(60, 40),
    )
    qtbot.addWidget(dialog)
    dialog._path_edit.setText(str(out))

    QTimer.singleShot(150, gate.set)  # render finishes while we wait
    with patch("src.views.export_dialog.QMessageBox"):
        dialog._do_export()

    assert out.exists()
    assert Image.open(out).size == (60, 40)


def test_failed_render_reports_and_writes_nothing(qapp, qtbot, settings_service, tmp_path):
    def boom():
        raise RuntimeError("out of memory")

    render = BackgroundTask(boom).start()
    out = tmp_path / "out.jpg"
    dialog = ExportDialog(
        default_path=str(out), settings_service=settings_service, render=render,
        image_size=(60, 40),
    )
    qtbot.addWidget(dialog)
    dialog._path_edit.setText(str(out))

    with patch("src.views.export_dialog.QMessageBox") as box:
        dialog._do_export()

    box.critical.assert_called_once()
    assert "out of memory" in box.critical.call_args.args[2]
    assert not out.exists()


def test_background_render_matches_the_synchronous_export(qapp, qtbot):
    controller = ImageController(ImageView(), use_threading=False)
    rng = np.random.default_rng(4)
    controller._apply_loaded_image("x.tif", rng.random((120, 180, 3), dtype=np.float32))
    controller.restore_adjustment_state(
        {"exposure": 0.7, "contrast": 20.0, "shadows": 30.0, "clarity": 25.0,
         "vignette": -20.0, "crop": {"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.8}}
    )

    task = controller.start_export_render()
    qtbot.waitUntil(task.is_done, timeout=5000)

    np.testing.assert_allclose(task.result, controller.get_export_image(), atol=1e-5)
    controller.cleanup()


def test_snapshot_ignores_edits_made_after_export_started(qapp, qtbot):
    controller = ImageController(ImageView(), use_threading=False)
    controller._apply_loaded_image("x.tif", np.full((20, 30, 3), 0.25, dtype=np.float32))
    controller.restore_adjustment_state({"exposure": 1.0})
    expected = controller.get_export_image()

    gate = threading.Event()
    task = controller.start_export_render(post=lambda img: (gate.wait(5), img)[1])
    controller.restore_adjustment_state({"exposure": -2.0})  # user keeps editing
    gate.set()
    qtbot.waitUntil(task.is_done, timeout=5000)

    np.testing.assert_allclose(task.result, expected, atol=1e-6)
    controller.cleanup()


def test_export_dialog_opens_without_rendering_on_the_ui_thread(qapp, qtbot, tmp_path):
    from src.services.library_catalog_service import LibraryCatalogService
    from src.services.library_image_preview_cache_service import (
        LibraryImagePreviewCacheService,
    )
    from src.services.library_thumbnail_cache_service import LibraryThumbnailCacheService
    from src.views.main_window import MainWindow

    window = MainWindow(
        settings_service=SettingsService(QSettings(str(tmp_path / "w.ini"), QSettings.Format.IniFormat)),
        catalog_service=LibraryCatalogService(catalog_path=tmp_path / "c.json"),
        thumbnail_cache_service=LibraryThumbnailCacheService(cache_dir=tmp_path / "t"),
        image_preview_cache_service=LibraryImagePreviewCacheService(cache_dir=tmp_path / "p"),
    )
    qtbot.addWidget(window)
    controller = window._image_controller
    controller._apply_loaded_image("x.tif", np.full((40, 60, 3), 0.5, dtype=np.float32))
    controller.get_export_image = MagicMock(
        side_effect=AssertionError("export must not render on the UI thread")
    )

    with patch("src.views.main_window.ExportDialog") as dialog_cls:
        dialog_cls.return_value.exec.return_value = False
        window._export_image()

    kwargs = dialog_cls.call_args.kwargs
    assert kwargs["image_size"] == (60, 40)
    assert isinstance(kwargs["render"], BackgroundTask)
    qtbot.waitUntil(kwargs["render"].is_done, timeout=5000)
    window.close()


def test_task_listeners_run_on_the_ui_thread(qapp, qtbot):
    """Plain-function listeners must not run on the worker thread (they
    touch widgets: status bar, message boxes)."""
    seen = []
    task = BackgroundTask(lambda: 42)
    task.finished.connect(lambda value: seen.append((value, threading.current_thread())))
    task.start()
    qtbot.waitUntil(lambda: bool(seen), timeout=3000)
    assert seen == [(42, threading.main_thread())]
