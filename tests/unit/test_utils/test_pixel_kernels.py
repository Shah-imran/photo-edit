"""Compiled kernels must match the NumPy reference and be safe to call
from several worker threads at once."""

import threading

import numpy as np
import pytest

from src.utils import pixel_kernels
from src.utils.pixel_kernels import apply_channel_luts


def _luts(size=4096):
    x = np.linspace(0.0, 1.0, size, dtype=np.float32)
    return np.stack([x**2, np.sqrt(x), 1.0 - x]).astype(np.float32)


def _reference(image, luts, active):
    out = np.empty_like(image)
    if image.shape[2] > 3:
        out[..., 3:] = image[..., 3:]
    pixel_kernels._channel_luts_numpy(image, luts, np.asarray(active), out)
    return out


@pytest.mark.parametrize("active", [(True, True, True), (True, False, True)])
def test_matches_numpy_reference(active):
    rng = np.random.default_rng(3)
    image = rng.uniform(-0.2, 1.3, size=(37, 53, 3)).astype(np.float32)
    luts = _luts()

    result = apply_channel_luts(image, luts, active)

    np.testing.assert_allclose(result, _reference(image, luts, active), atol=1e-6)


def test_inactive_channel_is_only_clipped():
    image = np.array([[[0.25, -0.5, 2.0]]], dtype=np.float32)
    result = apply_channel_luts(image, _luts(), (False, False, False))
    np.testing.assert_allclose(result, [[[0.25, 0.0, 1.0]]], atol=1e-7)


def test_nan_maps_to_zero_input_instead_of_crashing():
    image = np.full((4, 4, 3), np.nan, dtype=np.float32)
    luts = _luts()
    result = apply_channel_luts(image, luts)
    np.testing.assert_allclose(result[0, 0], luts[:, 0])


def test_extra_channels_pass_through():
    image = np.full((3, 3, 4), 0.3, dtype=np.float32)
    result = apply_channel_luts(image, _luts())
    np.testing.assert_array_equal(result[..., 3], image[..., 3])


def test_concurrent_calls_from_threads_are_safe():
    rng = np.random.default_rng(5)
    image = rng.random((200, 300, 3), dtype=np.float32)
    luts = _luts()
    expected = _reference(image, luts, (True, True, True))
    errors = []

    def run():
        try:
            for _ in range(20):
                np.testing.assert_allclose(apply_channel_luts(image, luts), expected, atol=1e-6)
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
