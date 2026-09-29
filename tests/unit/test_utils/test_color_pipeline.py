"""Unit tests for src.utils.color_pipeline."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from src.utils.color_pipeline import (
    linear_to_pil,
    linear_to_qimage,
    linear_to_srgb,
    pil_to_linear,
    srgb_to_linear,
    to_linear,
)


@pytest.fixture(scope="module")
def qapp():
    """QImage construction does not need a QGuiApplication, but some
    PyQt6 builds emit warnings without one. We make a QApplication just
    in case."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestSrgbConversionEndpoints:
    """Endpoints of the sRGB OETF/EOTF must round-trip exactly."""

    def test_srgb_to_linear_endpoints(self):
        assert srgb_to_linear(np.array(0.0, dtype=np.float32)) == pytest.approx(0.0, abs=1e-7)
        assert srgb_to_linear(np.array(1.0, dtype=np.float32)) == pytest.approx(1.0, abs=1e-6)

    def test_linear_to_srgb_endpoints(self):
        assert linear_to_srgb(np.array(0.0, dtype=np.float32)) == pytest.approx(0.0, abs=1e-7)
        assert linear_to_srgb(np.array(1.0, dtype=np.float32)) == pytest.approx(1.0, abs=1e-6)

    def test_round_trip_within_tolerance(self):
        x = np.linspace(0.0, 1.0, 257, dtype=np.float32)
        round_trip = linear_to_srgb(srgb_to_linear(x))
        np.testing.assert_allclose(round_trip, x, atol=1e-5)


class TestSrgbConversionPiecewise:
    """The piecewise transition near 0.04045 / 0.0031308 must be smooth."""

    def test_continuity_at_threshold(self):
        # A small epsilon around the sRGB transition; the EOTF should
        # be continuous in value (not necessarily in derivative) within
        # tight float tolerance.
        eps = 1e-6
        below = srgb_to_linear(np.array(0.04045 - eps, dtype=np.float32))
        above = srgb_to_linear(np.array(0.04045 + eps, dtype=np.float32))
        assert abs(float(below) - float(above)) < 5e-5

    def test_mid_grey_pil_value_matches_iec_formula(self):
        """sRGB 128/255 should land at the IEC piecewise EOTF value."""
        pil = Image.new("RGB", (1, 1), color=(128, 128, 128))
        arr = pil_to_linear(pil)
        # Reference value from the IEC 61966-2-1 formula.
        expected = ((128 / 255.0 + 0.055) / 1.055) ** 2.4
        np.testing.assert_allclose(arr, expected, atol=1e-4)


class TestPilToLinear:
    """PIL boundary conversions."""

    def test_returns_float32_three_channel(self):
        pil = Image.new("RGB", (4, 3), color=(64, 128, 192))
        arr = pil_to_linear(pil)
        assert isinstance(arr, np.ndarray)
        assert arr.dtype == np.float32
        assert arr.shape == (3, 4, 3)
        assert 0.0 <= arr.min() <= arr.max() <= 1.0

    def test_grayscale_broadcasts_to_three_channels(self):
        pil = Image.new("L", (2, 2), color=200)
        arr = pil_to_linear(pil)
        assert arr.shape == (2, 2, 3)
        # All three channels identical in a grayscale->RGB conversion.
        np.testing.assert_allclose(arr[..., 0], arr[..., 1])
        np.testing.assert_allclose(arr[..., 1], arr[..., 2])

    def test_rgba_drops_alpha(self):
        pil = Image.new("RGBA", (2, 2), color=(50, 100, 150, 64))
        arr = pil_to_linear(pil)
        assert arr.shape == (2, 2, 3)


class TestLinearToPil:
    """linear -> PIL boundary."""

    def test_zeros_to_black(self):
        arr = np.zeros((2, 2, 3), dtype=np.float32)
        pil = linear_to_pil(arr)
        assert pil.mode == "RGB"
        assert np.array(pil).max() == 0

    def test_ones_to_white(self):
        arr = np.ones((2, 2, 3), dtype=np.float32)
        pil = linear_to_pil(arr)
        assert np.array(pil).min() == 255

    def test_clips_out_of_gamut_high(self):
        arr = np.full((1, 1, 3), 1.5, dtype=np.float32)
        pil = linear_to_pil(arr)
        assert tuple(np.array(pil)[0, 0]) == (255, 255, 255)

    def test_clips_out_of_gamut_low(self):
        arr = np.full((1, 1, 3), -0.1, dtype=np.float32)
        pil = linear_to_pil(arr)
        assert tuple(np.array(pil)[0, 0]) == (0, 0, 0)

    def test_rejects_wrong_shape(self):
        with pytest.raises(ValueError, match="expected shape"):
            linear_to_pil(np.zeros((10, 10), dtype=np.float32))


class TestLinearToQImage:
    """linear -> QImage boundary."""

    def test_returns_rgb888_qimage_correct_size(self, qapp):
        arr = np.full((5, 7, 3), 0.5, dtype=np.float32)
        qimg = linear_to_qimage(arr)
        assert isinstance(qimg, QImage)
        assert qimg.format() == QImage.Format.Format_RGB888
        assert qimg.width() == 7
        assert qimg.height() == 5

    def test_values_round_trip_via_buffer(self, qapp):
        # Build an array that is exactly representable as 8-bit sRGB
        # so we can compare without quantization noise. Width 4 keeps
        # 3*4=12 bytes/row aligned to 4 bytes (no padding to strip).
        srgb_u8 = np.array(
            [[[0, 64, 128, 192], [255, 32, 96, 200], [10, 20, 30, 40]]],
            dtype=np.uint8,
        ).reshape(1, 4, 3)
        arr = srgb_to_linear(srgb_u8.astype(np.float32) / 255.0)
        qimg = linear_to_qimage(arr)
        assert qimg.width() == 4
        assert qimg.height() == 1

        bpl = qimg.bytesPerLine()
        height, width = qimg.height(), qimg.width()
        ptr = qimg.bits()
        ptr.setsize(height * bpl)
        raw = np.frombuffer(bytes(ptr), dtype=np.uint8).reshape(height, bpl)
        # Strip any per-row padding to get the true HxWx3 image.
        round_trip = raw[:, : width * 3].reshape(height, width, 3)
        np.testing.assert_array_equal(round_trip, srgb_u8)


class TestPilLinearRoundTrip:
    """End-to-end PIL -> linear -> PIL round-trip is byte-stable."""

    def test_round_trip_byte_identity(self):
        rng = np.random.default_rng(seed=42)
        original = rng.integers(0, 256, size=(8, 8, 3), dtype=np.uint8)
        pil = Image.fromarray(original, mode="RGB")
        arr = pil_to_linear(pil)
        round_trip = np.array(linear_to_pil(arr), dtype=np.uint8)
        # Byte-identity within +/- 1 LSB (rounding).
        diff = np.abs(round_trip.astype(np.int16) - original.astype(np.int16))
        assert diff.max() <= 1


class TestToLinearCoercion:
    """to_linear accepts both PIL and ndarray for the transitional viewer API."""

    def test_passes_through_float32_ndarray(self):
        arr = np.zeros((2, 2, 3), dtype=np.float32)
        out = to_linear(arr)
        assert out is arr  # no copy

    def test_casts_float64_ndarray(self):
        arr = np.zeros((2, 2, 3), dtype=np.float64)
        out = to_linear(arr)
        assert out.dtype == np.float32

    def test_converts_pil_image(self):
        pil = Image.new("RGB", (2, 2), color=(10, 20, 30))
        out = to_linear(pil)
        assert out.shape == (2, 2, 3)
        assert out.dtype == np.float32

    def test_rejects_unknown_type(self):
        with pytest.raises(TypeError, match="to_linear"):
            to_linear("not-an-image")
