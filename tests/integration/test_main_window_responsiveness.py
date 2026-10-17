"""The real window stays responsive through a full editing session.

Drives MainWindow the way a user does -- open a 24 MP photo, drag a
slider through its real widget signals, release, undo, redo, switch to
another photo and back, use the mask and crop tools -- while a heartbeat
watchdog measures how long the event loop is ever blocked. Replaces the
older tests/performance/test_integrated_performance.py, whose checks
(e.g. "zoom_in() did not raise") could not detect a frozen UI.

Budget: no event-loop stall over 100 ms (the app target is 50 ms; the
margin absorbs test-machine noise). See
docs/planning/PERFORMANCE_OVERHAUL.md.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from src.services.library_catalog_service import LibraryCatalogService
from src.services.library_image_preview_cache_service import (
    LibraryImagePreviewCacheService,
)
from src.services.library_thumbnail_cache_service import LibraryThumbnailCacheService
from src.services.settings_service import SettingsService
from src.utils import pixel_kernels
from src.utils.stall_watchdog import UiStallWatchdog
from src.views.main_window import MainWindow

pytestmark = pytest.mark.integration

STALL_BUDGET_MS = 100.0


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _write_photo(path, seed):
    """24 MP JPEG with gradients and some texture (not a flat colour)."""
    h, w = 4000, 6000
    y = np.linspace(0, 255, h, dtype=np.float32)[:, None]
    x = np.linspace(0, 255, w, dtype=np.float32)[None, :]
    base = np.stack(
        np.broadcast_arrays(x * 0.8 + y * 0.2, (x + y) * 0.5, 255 - x + 0 * y), axis=-1
    ).astype(np.float32)
    rng = np.random.default_rng(seed)
    base += rng.normal(0, 6, size=(h, w, 1)).astype(np.float32)
    Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).save(path, quality=90)
    return str(path)


@pytest.fixture(scope="module")
def photos(tmp_path_factory):
    folder = tmp_path_factory.mktemp("photos")
    return _write_photo(folder / "a.jpg", 1), _write_photo(folder / "b.jpg", 2)


@pytest.fixture
def window(qapp, qtbot, tmp_path):
    pixel_kernels.warm_up()
    window = MainWindow(
        settings_service=SettingsService(
            QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
        ),
        catalog_service=LibraryCatalogService(catalog_path=tmp_path / "catalog.json"),
        thumbnail_cache_service=LibraryThumbnailCacheService(cache_dir=tmp_path / "c"),
        image_preview_cache_service=LibraryImagePreviewCacheService(
            cache_dir=tmp_path / "pc"
        ),
    )
    qtbot.addWidget(window)
    window.resize(1400, 900)
    window.show()
    qtbot.waitExposed(window)
    yield window
    window.close()


class _StallRecorder(UiStallWatchdog):
    def __init__(self, parent):
        super().__init__(parent, interval_ms=10, threshold_ms=STALL_BUDGET_MS)
        self.step = "start"
        self.stalls: list[tuple[str, int]] = []

    def record(self, blocked_ms):
        if blocked_ms > STALL_BUDGET_MS:
            self.stalls.append((self.step, round(blocked_ms)))
        super().record(blocked_ms)


def _open(qtbot, window, path):
    controller = window._image_controller
    controller.load_image_async(path, window)
    qtbot.waitUntil(
        lambda: controller.has_image() and controller.image_model.file_path == path,
        timeout=30000,
    )
    qtbot.wait(300)


def _wait_frame(qtbot, controller):
    target = controller._latest_request_id
    qtbot.waitUntil(
        lambda: controller._latest_presented_preview_id >= target, timeout=15000
    )


def test_editing_session_never_freezes_the_window(qtbot, window, photos):
    controller = window._image_controller
    tools = window._tools_panel
    recorder = _StallRecorder(window)
    recorder.start()

    recorder.step = "open"
    _open(qtbot, window, photos[0])

    recorder.step = "drag"
    for value in np.linspace(0.1, 1.5, 15):
        tools._exposure_slider.set_value(float(value))
        qtbot.wait(16)
    recorder.step = "release"
    tools.slider_released.emit()
    _wait_frame(qtbot, controller)
    assert controller.can_undo()

    recorder.step = "undo"
    controller.undo()
    _wait_frame(qtbot, controller)
    assert controller.get_adjustment_state()["exposure"] == 0.0
    recorder.step = "redo"
    controller.redo()
    _wait_frame(qtbot, controller)
    assert controller.get_adjustment_state()["exposure"] == pytest.approx(1.5)

    recorder.step = "switch photo"
    _open(qtbot, window, photos[1])
    recorder.step = "switch back"
    _open(qtbot, window, photos[0])

    recorder.step = "mask"
    window._enter_mask_mode()
    for i in range(8):
        controller.preview_mask(
            {"type": "radial", "cx": 0.3 + 0.05 * i, "cy": 0.5, "exposure": 1.0}
        )
        qtbot.wait(20)
    _wait_frame(qtbot, controller)
    window._cancel_mask()

    recorder.step = "crop"
    window._enter_crop_mode()
    qtbot.wait(300)
    window._cancel_crop()
    qtbot.wait(300)

    recorder.stop()
    assert recorder.stalls == [], f"UI froze: {recorder.stalls}"
