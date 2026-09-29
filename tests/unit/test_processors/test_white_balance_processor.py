"""Unit tests for WhiteBalanceProcessor (Temperature/Tint)."""

import numpy as np
import pytest

from src.processors.white_balance_processor import WhiteBalanceProcessor


@pytest.fixture
def processor():
    return WhiteBalanceProcessor()


def _solid(value, shape=(2, 2, 3)):
    return np.full(shape, value, dtype=np.float32)


class TestIdentity:
    def test_all_zero_params_is_identity(self, processor):
        rgb = np.random.rand(4, 4, 3).astype(np.float32)
        result = processor.process(rgb)
        np.testing.assert_array_equal(result, rgb)

    def test_returns_new_array_not_same_object(self, processor):
        rgb = _solid(0.5)
        result = processor.process(rgb)
        assert result is not rgb


class TestDocumentedFormula:
    def test_matches_documented_formula(self, processor):
        rgb = _solid(0.5)
        temperature, tint = 40.0, -20.0
        result = processor.process(rgb, temperature=temperature, tint=tint)

        t = temperature / 100.0
        n = tint / 100.0
        strength = WhiteBalanceProcessor._TEMPERATURE_STRENGTH
        r_expected = 0.5 * (1.0 + t * strength + n * strength * 0.5)
        g_expected = 0.5 * (1.0 - n * strength)
        b_expected = 0.5 * (1.0 - t * strength + n * strength * 0.5)

        np.testing.assert_allclose(result[0, 0, 0], r_expected, atol=1e-6)
        np.testing.assert_allclose(result[0, 0, 1], g_expected, atol=1e-6)
        np.testing.assert_allclose(result[0, 0, 2], b_expected, atol=1e-6)


class TestTemperature:
    def test_positive_temperature_boosts_red_cuts_blue(self, processor):
        mid = _solid(0.5)
        result = processor.process(mid, temperature=50.0)
        assert result[0, 0, 0] > mid[0, 0, 0]
        assert result[0, 0, 2] < mid[0, 0, 2]
        assert result[0, 0, 1] == pytest.approx(mid[0, 0, 1])

    def test_negative_temperature_boosts_blue_cuts_red(self, processor):
        mid = _solid(0.5)
        result = processor.process(mid, temperature=-50.0)
        assert result[0, 0, 2] > mid[0, 0, 2]
        assert result[0, 0, 0] < mid[0, 0, 0]


class TestTint:
    def test_positive_tint_cuts_green_boosts_red_and_blue(self, processor):
        mid = _solid(0.5)
        result = processor.process(mid, tint=50.0)
        assert result[0, 0, 1] < mid[0, 0, 1]
        assert result[0, 0, 0] > mid[0, 0, 0]
        assert result[0, 0, 2] > mid[0, 0, 2]

    def test_negative_tint_boosts_green(self, processor):
        mid = _solid(0.5)
        result = processor.process(mid, tint=-50.0)
        assert result[0, 0, 1] > mid[0, 0, 1]


class TestOutputProperties:
    def test_dtype_stays_float32(self, processor):
        result = processor.process(_solid(0.5), temperature=40.0)
        assert result.dtype == np.float32

    def test_no_clipping_inside_processor(self, processor):
        # A bright pixel pushed warmer can legitimately exceed 1.0; clipping
        # happens at final encode, not inside the processor (matches
        # ExposureProcessor's convention).
        bright = _solid(0.99)
        result = processor.process(bright, temperature=100.0)
        assert result[0, 0, 0] > 1.0


class TestRgbaPassthrough:
    def test_alpha_channel_untouched(self, processor):
        rgba = np.full((2, 2, 4), 0.5, dtype=np.float32)
        rgba[..., 3] = 0.3
        result = processor.process(rgba, temperature=40.0, tint=-20.0)
        np.testing.assert_array_equal(result[..., 3], rgba[..., 3])
