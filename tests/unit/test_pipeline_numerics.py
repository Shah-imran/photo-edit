"""Numerical-correctness tests for the float32 linear pipeline.

These tests pin the contract that processors operate in linear-light
space and that boundary conversions round-trip cleanly. They run
without any GUI or Qt application (hence not under ``test_views`` or
``test_processors`` -- these are cross-cutting invariants).
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from src.processors.color_processor import ColorProcessor
from src.processors.exposure_processor import ExposureProcessor
from src.services.image_service import ImageService
from src.utils.color_pipeline import (
    linear_to_srgb,
    pil_to_linear,
    srgb_to_linear,
)


class TestLinearLoadFidelity:
    """sRGB JPEG/PNG -> LinearImage must match the IEC EOTF."""

    def test_mid_grey_jpeg_loads_at_iec_value(self, tmp_path):
        path = tmp_path / "grey.jpg"
        Image.new("RGB", (8, 8), color=(128, 128, 128)).save(path, "JPEG", quality=95)

        service = ImageService()
        arr = service.load_image(str(path))

        expected = ((128 / 255.0 + 0.055) / 1.055) ** 2.4
        # JPEG quantization can shift the value by ~1 LSB, so allow that.
        np.testing.assert_allclose(arr, expected, atol=5e-3)

    def test_png_save_load_round_trip_within_one_lsb(self, tmp_path):
        rng = np.random.default_rng(seed=7)
        srgb_u8 = rng.integers(0, 256, size=(16, 16, 3), dtype=np.uint8)
        original_linear = srgb_to_linear(srgb_u8.astype(np.float32) / 255.0)

        path = tmp_path / "rt.png"
        service = ImageService()
        service.save_image(original_linear, str(path), format="PNG")
        loaded = service.load_image(str(path))

        diff_u8 = np.abs(
            (linear_to_srgb(loaded) * 255.0).round().astype(np.int16)
            - srgb_u8.astype(np.int16)
        )
        assert diff_u8.max() <= 1


class TestExposureStopsAreLinear:
    """The whole point of the migration: exposure +/- N stops is exact."""

    @pytest.fixture
    def flat_quarter(self) -> np.ndarray:
        return np.full((8, 8, 3), 0.25, dtype=np.float32)

    def test_plus_one_stop_doubles_linear(self, flat_quarter):
        out = ExposureProcessor().process(flat_quarter, exposure=1.0)
        np.testing.assert_allclose(out, 0.5, atol=1e-6)

    def test_minus_one_stop_halves_linear(self):
        flat = np.full((8, 8, 3), 0.5, dtype=np.float32)
        out = ExposureProcessor().process(flat, exposure=-1.0)
        np.testing.assert_allclose(out, 0.25, atol=1e-6)

    def test_plus_two_stops_quadruples_below_clip(self):
        flat = np.full((4, 4, 3), 0.1, dtype=np.float32)
        out = ExposureProcessor().process(flat, exposure=2.0)
        np.testing.assert_allclose(out, 0.4, atol=1e-6)


class TestSaturationMinus100:
    """Saturation -100 must collapse to channel-equal grayscale (HSV V)."""

    def test_collapse_to_v(self):
        arr = np.zeros((4, 4, 3), dtype=np.float32)
        arr[..., 0] = 0.7
        arr[..., 1] = 0.2
        arr[..., 2] = 0.1

        out = ColorProcessor().process(arr, saturation=-100.0)

        v = arr.max(axis=-1, keepdims=True)
        np.testing.assert_allclose(out, np.broadcast_to(v, out.shape), atol=1e-5)

    def test_pure_grey_unchanged_by_saturation(self):
        grey = np.full((4, 4, 3), 0.4, dtype=np.float32)

        increased = ColorProcessor().process(grey, saturation=100.0)
        decreased = ColorProcessor().process(grey, saturation=-100.0)

        np.testing.assert_allclose(increased, grey, atol=1e-5)
        np.testing.assert_allclose(decreased, grey, atol=1e-5)


class TestNoNansAtExtremes:
    """Negative or super-bright intermediates must not produce NaNs."""

    def test_extreme_exposure_extreme_contrast(self):
        flat = np.full((8, 8, 3), 0.05, dtype=np.float32)
        ex = ExposureProcessor()
        out = ex.process(flat, exposure=5.0, contrast=100.0)
        assert not np.any(np.isnan(out))

    def test_negative_intermediates_round_trip(self):
        # Create a value that goes negative after the contrast curve.
        srgb_low = np.full((4, 4, 3), 0.1, dtype=np.float32)
        # Plug a synthesized linear array into the encode/decode pair.
        linear = srgb_to_linear(srgb_low - 0.5)  # intentionally negative
        re_encoded = linear_to_srgb(linear)
        # The OETF clips negatives to 0; the EOTF preserves sign symmetry.
        assert not np.any(np.isnan(linear))
        assert not np.any(np.isnan(re_encoded))


class TestProcessorIdempotenceAtZero:
    """Zero adjustments must return an exactly equal image (no rounding drift)."""

    def test_exposure_zero_is_identity(self):
        rng = np.random.default_rng(seed=11)
        arr = rng.random((8, 8, 3)).astype(np.float32)
        out = ExposureProcessor().process(arr)
        np.testing.assert_allclose(out, arr, atol=1e-7)

    def test_color_zero_is_identity(self):
        rng = np.random.default_rng(seed=13)
        arr = rng.random((8, 8, 3)).astype(np.float32)
        out = ColorProcessor().process(arr)
        np.testing.assert_allclose(out, arr, atol=1e-7)
