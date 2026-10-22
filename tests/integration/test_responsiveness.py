"""End-to-end responsiveness checks with the real background workers.

These drive ImageController the way the UI does (drag, release, undo,
redo, photo switch) on a 24 MP image and assert two things:

* every call returns to the event loop quickly (nothing heavy runs on the
  UI thread), and
* the worker's frame actually arrives and is presented.

Budgets come from docs/planning/PERFORMANCE_OVERHAUL.md section 3.
"""

from __future__ import annotations

from time import perf_counter

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from src.controllers.image_controller import ImageController
from src.utils import pixel_kernels
from src.views.image_view import ImageView


pytestmark = pytest.mark.integration

UI_CALL_BUDGET_MS = 50.0


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def big_image():
    rng = np.random.default_rng(7)
    h, w = 4000, 6000
    y = np.linspace(0.05, 0.95, h, dtype=np.float32)[:, None, None]
    x = np.linspace(0.05, 0.95, w, dtype=np.float32)[None, :, None]
    image = np.broadcast_to((x + y) * 0.5, (h, w, 3)).copy()
    image += rng.normal(0, 0.01, size=(h, w, 1)).astype(np.float32)
    return np.clip(image, 0, 1).astype(np.float32)


@pytest.fixture
def controller(qapp, qtbot):
    # Compile (or load) the pixel kernels first: a first-ever JIT compile
    # is a one-off install cost, not what these tests measure.
    pixel_kernels.warm_up()
    view = ImageView()
    view.resize(1200, 800)
    view.show()
    qtbot.waitExposed(view)
    controller = ImageController(view, use_threading=True)
    yield controller
    controller.cleanup()
    view.close()


def _timed_ms(fn, *args, **kwargs) -> float:
    start = perf_counter()
    fn(*args, **kwargs)
    return (perf_counter() - start) * 1000.0


def _wait_for_frame(qtbot, controller, after_request_id: int) -> None:
    qtbot.waitUntil(
        lambda: controller._latest_presented_preview_id >= after_request_id,
        timeout=15000,
    )


def test_release_undo_redo_stay_off_the_ui_thread(qtbot, controller, big_image):
    controller._apply_loaded_image("big.tif", big_image)
    controller.fit_to_window()

    drag_ms = max(
        _timed_ms(controller.on_adjustments_changed, {"exposure": value})
        for value in (0.2, 0.4, 0.6, 0.8, 1.0)
    )
    release_ms = _timed_ms(controller.on_slider_released)
    release_request = controller._latest_request_id
    _wait_for_frame(qtbot, controller, release_request)
    assert controller.can_undo()

    undo_ms = _timed_ms(controller.undo)
    _wait_for_frame(qtbot, controller, controller._latest_request_id)
    assert controller.get_adjustment_state()["exposure"] == 0.0

    redo_ms = _timed_ms(controller.redo)
    _wait_for_frame(qtbot, controller, controller._latest_request_id)
    assert controller.get_adjustment_state()["exposure"] == 1.0

    # The presented frame is a preview, not a 24 MP buffer.
    assert max(controller.get_current_image().shape[:2]) < 4000

    for name, elapsed in (
        ("drag", drag_ms),
        ("release", release_ms),
        ("undo", undo_ms),
        ("redo", redo_ms),
    ):
        assert elapsed < UI_CALL_BUDGET_MS, f"{name} blocked the UI for {elapsed:.0f} ms"


def test_restore_adjustment_state_stays_off_the_ui_thread(qtbot, controller, big_image):
    controller._apply_loaded_image("big.tif", big_image)
    restore_ms = _timed_ms(
        controller.restore_adjustment_state,
        {"exposure": 0.5, "contrast": 20.0, "clarity": 30.0},
    )
    _wait_for_frame(qtbot, controller, controller._latest_request_id)
    assert restore_ms < UI_CALL_BUDGET_MS, f"restore blocked the UI for {restore_ms:.0f} ms"


def test_mask_preview_stays_off_the_ui_thread(qtbot, controller, big_image):
    controller._apply_loaded_image("big.tif", big_image)
    mask = {"type": "radial", "exposure": 1.0}
    preview_ms = max(_timed_ms(controller.preview_mask, mask) for _ in range(5))
    _wait_for_frame(qtbot, controller, controller._latest_request_id)
    assert preview_ms < UI_CALL_BUDGET_MS, f"mask preview blocked the UI for {preview_ms:.0f} ms"
    assert controller.get_adjustment_state()["masks"] == []
