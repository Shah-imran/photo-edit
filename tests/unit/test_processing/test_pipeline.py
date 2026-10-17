"""One develop pipeline: every render entry point gives the same pixels.

There used to be five hand-maintained copies of the stage sequence; the
synchronous preview copy passed the mask's fields as keyword arguments and
raised whenever a mask existed. These pin all entry points to
DevelopPipeline.render.
"""

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from src.commands.adjustment_commands import CombinedAdjustmentCommand
from src.controllers.image_controller import ImageController
from src.models.image_model import ImageModel
from src.processing.pipeline import DevelopPipeline
from src.processing.processing_worker import ProcessingWorker
from src.views.image_view import ImageView


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


RECIPE = {
    "exposure": 0.6, "contrast": 15.0, "shadows": 30.0, "clarity": 20.0,
    "vignette": -25.0, "tone_curve": [[0.0, 0.0], [0.5, 0.6], [1.0, 1.0]],
    "crop": {"x0": 0.1, "y0": 0.05, "x1": 0.9, "y1": 0.85},
    "mask": {"type": "radial", "cx": 0.5, "cy": 0.5, "rx": 0.3, "ry": 0.3,
             "feather": 0.5, "invert": False, "exposure": 1.0, "contrast": 0.0,
             "saturation": 0.0, "clarity": 0.0},
    "heal_spots": [{"mode": "heal", "dst_x": 0.3, "dst_y": 0.4, "src_x": 0.6, "src_y": 0.4,
                    "radius": 0.05, "feather": 0.3, "opacity": 1.0}],
}


@pytest.fixture
def photo():
    rng = np.random.default_rng(9)
    return rng.random((90, 140, 3), dtype=np.float32)


@pytest.fixture
def controller(qapp, photo):
    controller = ImageController(ImageView(), use_threading=False)
    controller._apply_loaded_image("x.tif", photo)
    controller.restore_adjustment_state(RECIPE)
    yield controller
    controller.cleanup()


def test_unknown_parameter_is_rejected():
    with pytest.raises(TypeError):
        DevelopPipeline().render(np.zeros((2, 2, 3), np.float32), exposure={"exposure": 1})


def test_render_never_modifies_its_input(photo):
    before = photo.copy()
    DevelopPipeline().render(photo, exposure_params={"exposure": 1.0})
    np.testing.assert_array_equal(photo, before)


def test_crop_is_applied_last():
    grey = np.full((90, 140, 3), 0.5, dtype=np.float32)
    result = DevelopPipeline().render(
        grey, crop_params={"x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 0.5},
        vignette_params={"vignette": 50.0},
    )
    # Vignette was computed on the full frame, then cropped: the cropped
    # corner at (0, 0) is a full-frame corner, darkest of all.
    assert result.shape[:2] == (45, 70)
    assert result[0, 0].mean() < result[-1, -1].mean()


def test_every_entry_point_renders_the_same_pixels(controller, photo):
    reference = controller.get_export_image()
    kwargs = controller._render_kwargs()

    worker = ProcessingWorker()._apply_adjustments(photo, **kwargs)
    restored = controller.image_model.current_image

    model = ImageModel()
    model.set_original_image(photo)
    command = CombinedAdjustmentCommand(model, **kwargs)
    command.execute()

    controller.apply_adjustments(add_to_history=False)  # sync live preview
    live = controller.image_model.current_image

    for name, image in [("worker", worker), ("restore", restored),
                        ("undo command", model.current_image), ("live preview", live)]:
        np.testing.assert_allclose(image, reference, atol=1e-6, err_msg=name)


def test_sync_live_preview_with_a_mask_does_not_raise(controller):
    """The old synchronous copy called the mask stage with the mask's
    fields as keyword arguments (TypeError)."""
    controller.apply_adjustments(add_to_history=False)
    assert controller.image_model.current_image is not None


@pytest.mark.parametrize(
    "params",
    [
        {"clarity_params": {"clarity": 70.0}},
        {"texture_params": {"texture": 70.0}},
        {"dehaze_params": {"dehaze": 60.0}},
        {"sharpening_params": {"sharpening": 80.0}},
        {"color_nr_params": {"color_nr": 80.0}},
    ],
)
def test_preview_matches_downscaled_export(params):
    """What the user approves on the preview is what gets exported: the
    same edit rendered at full size and downscaled matches the preview.
    (Effects used fixed pixel radii, so Clarity on a 1400 px preview and on
    a 6000 px export looked different.)"""
    import cv2

    rng = np.random.default_rng(3)
    small = cv2.resize(rng.random((64, 96, 3), dtype=np.float32), (1050, 700),
                       interpolation=cv2.INTER_CUBIC)
    full = cv2.resize(small, (3150, 2100), interpolation=cv2.INTER_CUBIC)
    pipeline = DevelopPipeline()

    preview = pipeline.render(small, pixel_scale=1 / 3, **params)
    export = pipeline.render(full, **params)
    export_small = cv2.resize(export, (1050, 700), interpolation=cv2.INTER_AREA)

    effect = np.abs(preview - small).mean()
    mismatch = np.abs(preview - export_small).mean()
    assert mismatch <= max(0.15 * effect, 2e-3), (mismatch, effect)
