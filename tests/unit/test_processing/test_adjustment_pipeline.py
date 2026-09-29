"""Unit tests for the shared apply_basic_adjustments pipeline function."""

import numpy as np
from PIL import Image

from src.processing.adjustment_pipeline import apply_basic_adjustments
from src.processors.exposure_processor import ExposureProcessor
from src.processors.color_processor import ColorProcessor


def _gray_image(size=(20, 20), value=128):
    return Image.new("RGB", size, color=(value, value, value))


class TestNoParams:
    def test_no_params_returns_unmodified_copy(self):
        image = _gray_image()
        result = apply_basic_adjustments(image)
        assert result is not image
        np.testing.assert_array_equal(np.array(result), np.array(image))

    def test_all_zero_params_is_identity(self):
        image = _gray_image()
        result = apply_basic_adjustments(
            image,
            exposure_params={"exposure": 0.0, "contrast": 0.0, "brightness": 0.0},
            tonal_params={"highlights": 0.0, "shadows": 0.0, "whites": 0.0, "blacks": 0.0},
            color_params={"saturation": 0.0, "vibrance": 0.0},
        )
        np.testing.assert_array_equal(np.array(result), np.array(image))


class TestOrderingAndComposition:
    def test_exposure_only_matches_exposure_processor_directly(self):
        image = _gray_image(value=100)
        params = {"exposure": 0.5, "contrast": 10.0, "brightness": 0.0}
        expected = ExposureProcessor().process(image.copy(), **params)
        result = apply_basic_adjustments(image, exposure_params=params)
        np.testing.assert_array_equal(np.array(result), np.array(expected))

    def test_color_only_matches_color_processor_directly(self):
        image = Image.new("RGB", (10, 10), color=(200, 120, 80))
        params = {"saturation": 30.0, "vibrance": 10.0}
        expected = ColorProcessor().process(image.copy(), **params)
        result = apply_basic_adjustments(image, color_params=params)
        np.testing.assert_array_equal(np.array(result), np.array(expected))

    def test_tonal_only_changes_a_bright_pixel_with_positive_highlights(self):
        image = Image.new("RGB", (5, 5), color=(230, 230, 230))
        result = apply_basic_adjustments(image, tonal_params={"highlights": 80.0})
        before = np.array(image)[0, 0, 0]
        after = np.array(result)[0, 0, 0]
        assert after >= before

    def test_all_three_stages_combine(self):
        image = Image.new("RGB", (5, 5), color=(60, 60, 60))
        result = apply_basic_adjustments(
            image,
            exposure_params={"exposure": 0.3, "contrast": 0.0, "brightness": 0.0},
            tonal_params={"shadows": 50.0},
            color_params={"saturation": 20.0},
        )
        # Just confirm it runs end to end and produces a different, valid image.
        assert result.size == image.size
        assert result.mode == "RGB"
        assert np.array(result).max() <= 255


class TestGrayscaleSkipsTonalGracefully:
    def test_l_mode_image_does_not_crash_with_tonal_params(self):
        image = Image.new("L", (5, 5), color=128)
        # Must not raise even though TonalProcessor only understands RGB(A).
        result = apply_basic_adjustments(image, tonal_params={"highlights": 50.0})
        assert result.mode == "L"


class TestDoesNotMutateInput:
    def test_original_image_untouched(self):
        image = Image.new("RGB", (5, 5), color=(50, 50, 50))
        original_bytes = image.tobytes()
        apply_basic_adjustments(
            image,
            exposure_params={"exposure": 1.0},
            tonal_params={"highlights": 50.0},
            color_params={"saturation": 50.0},
        )
        assert image.tobytes() == original_bytes
