"""ImageController on the production render path, judged by what's on screen.

Most older controller tests construct ``use_threading=False``, a
synchronous fallback the app never runs, and assert internal fields.
These run the real threaded path (async requests, display frames,
settings-only history, detail renders) through ``InlineProcessingWorker``
and check outcomes: the pixels shown, the undo stack, the output size.
"""

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from src.controllers.image_controller import ImageController
from src.views.image_view import ImageView
from tests.support.inline_worker import InlineProcessingWorker


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def photo():
    """3000x2000 smooth gradient (bigger than the 1400 px quality proxy)."""
    h, w = 2000, 3000
    y = np.linspace(0.05, 0.6, h, dtype=np.float32)[:, None, None]
    x = np.linspace(0.05, 0.6, w, dtype=np.float32)[None, :, None]
    return np.broadcast_to((x + y) * 0.5 * np.array([1.0, 0.8, 0.6], np.float32), (h, w, 3)).copy()


@pytest.fixture
def setup(qapp, qtbot, photo):
    view = ImageView()
    view.resize(800, 600)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    controller = ImageController(
        view, use_threading=True, worker_factory=InlineProcessingWorker
    )
    controller._apply_loaded_image("photo.tif", photo)
    controller.fit_to_window()
    yield view, controller
    controller.cleanup()


def _settle(qtbot, controller):
    """Let every queued render land."""
    target = controller._latest_request_id
    qtbot.waitUntil(lambda: controller._latest_presented_preview_id >= target, timeout=5000)
    qtbot.wait(30)


def _shown_mean(view) -> float:
    image = view.get_display_image()
    ptr = image.constBits()
    ptr.setsize(image.sizeInBytes())
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(image.height(), image.bytesPerLine())
    return float(arr[:, : image.width() * image.depth() // 8].mean())


def _edit(controller, **values):
    controller.on_adjustments_changed(values)
    controller.on_slider_released()


def test_release_shows_the_edit_and_records_one_undo_step(qtbot, setup):
    view, controller = setup
    before = _shown_mean(view)

    _edit(controller, exposure=1.0)
    _settle(qtbot, controller)

    assert _shown_mean(view) > before + 20
    assert len(controller.history_service._undo_stack) == 1


def test_undo_and_redo_switch_the_shown_pixels(qtbot, setup):
    view, controller = setup
    controller.refresh_view()
    _settle(qtbot, controller)
    original = _shown_mean(view)
    _edit(controller, exposure=1.0)
    _settle(qtbot, controller)
    edited = _shown_mean(view)

    controller.undo()
    _settle(qtbot, controller)
    assert _shown_mean(view) == pytest.approx(original, abs=0.5)

    controller.redo()
    _settle(qtbot, controller)
    assert _shown_mean(view) == pytest.approx(edited, abs=0.5)


def test_each_release_is_one_step_and_undo_walks_back_in_order(qtbot, setup):
    view, controller = setup
    for value in (0.5, 1.0, 1.5):
        _edit(controller, exposure=value)
    _settle(qtbot, controller)

    seen = []
    while controller.can_undo():
        controller.undo()
        seen.append(controller.get_adjustment_state()["exposure"])
    assert seen == [1.0, 0.5, 0.0]


def test_restoring_saved_settings_renders_them(qtbot, setup):
    view, controller = setup
    controller.refresh_view()
    _settle(qtbot, controller)
    original = _shown_mean(view)

    controller.restore_adjustment_state({"exposure": -1.0})
    _settle(qtbot, controller)

    assert _shown_mean(view) < original - 10
    assert not controller.can_undo()  # restoring is not an undoable edit


def test_mask_preview_changes_the_screen_but_not_the_edit(qtbot, setup):
    view, controller = setup
    controller.refresh_view()
    _settle(qtbot, controller)
    committed = _shown_mean(view)

    controller.preview_mask({"type": "radial", "cx": 0.5, "cy": 0.5, "rx": 0.4, "ry": 0.4, "exposure": 2.0})
    _settle(qtbot, controller)
    assert _shown_mean(view) > committed + 5
    assert controller.get_adjustment_state()["mask"] in (None, {})

    controller.refresh_view()  # what Cancel does
    _settle(qtbot, controller)
    assert _shown_mean(view) == pytest.approx(committed, abs=0.5)


def test_crop_changes_output_size_and_crop_mode_shows_the_full_frame(qtbot, setup):
    view, controller = setup
    controller.on_crop_changed({"x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5})
    _settle(qtbot, controller)
    assert controller.get_output_size() == (1500, 1000)
    cropped_shown = view.get_display_image()

    assert controller.preview_uncropped() == (3000, 2000)
    _settle(qtbot, controller)
    full_shown = view.get_display_image()

    assert full_shown.width() > cropped_shown.width()
    assert full_shown.width() / full_shown.height() == pytest.approx(1.5, abs=0.01)


def test_zooming_past_the_preview_brings_in_full_resolution(qtbot, setup):
    view, controller = setup
    _edit(controller, exposure=0.5)
    _settle(qtbot, controller)
    assert view.get_display_image().width() < 3000

    view.set_zoom_factor(1.0)
    qtbot.waitUntil(lambda: view.get_display_image().width() == 3000, timeout=5000)

    assert view.get_zoom_factor() == 1.0
    assert view._image_canvas.width() == 3000  # true 1:1 on screen
