"""Pure-numpy math for the Tone Curve: point normalization, monotonic
cubic interpolation, and a luminance histogram helper.

This module has no Qt/PIL dependency (same spirit as
:mod:`src.utils.color_pipeline`): both ``CurveProcessor`` and the
``CurveEditor`` widget import it, so the curve drawn on screen and the
curve actually applied to pixels are always the same function.

Points are ``(x, y)`` pairs in ``[0, 1]``, sorted by ``x``, with the
first point's ``x`` pinned to ``0.0`` and the last point's ``x`` pinned to
``1.0`` -- matching Lightroom's point curve, where only interior points
move in ``x``.
"""

from __future__ import annotations

from typing import Iterable, Sequence, Tuple

import numpy as np

Point = Tuple[float, float]

#: Identity curve: a straight line, i.e. a no-op.
DEFAULT_CURVE_POINTS: Tuple[Point, ...] = ((0.0, 0.0), (1.0, 1.0))

#: Minimum x-separation enforced between adjacent control points so the
#: curve stays a proper function (strictly increasing x) for the spline.
MIN_POINT_X_GAP = 1.0 / 256.0


def normalize_points(points: Iterable[Sequence[float]] | None) -> Tuple[Point, ...]:
    """Return a valid, sorted, endpoint-pinned tuple of control points.

    Tolerant of malformed input (missing, too few points, out-of-range
    values, unsorted x): falls back to :data:`DEFAULT_CURVE_POINTS` rather
    than raising, the same tolerance
    ``ImageController._normalize_adjustment_state`` already applies to
    float adjustment values.
    """
    if not points:
        return DEFAULT_CURVE_POINTS

    try:
        pairs = [(float(p[0]), float(p[1])) for p in points]
    except (TypeError, ValueError, IndexError):
        return DEFAULT_CURVE_POINTS

    if len(pairs) < 2:
        return DEFAULT_CURVE_POINTS

    pairs.sort(key=lambda p: p[0])

    clamped: list[Point] = []
    prev_x = -1.0
    for x, y in pairs:
        x = min(1.0, max(0.0, x))
        y = min(1.0, max(0.0, y))
        if x <= prev_x:
            x = min(1.0, prev_x + MIN_POINT_X_GAP)
        clamped.append((x, y))
        prev_x = x

    first_x, first_y = clamped[0]
    clamped[0] = (0.0, first_y)
    last_x, last_y = clamped[-1]
    clamped[-1] = (1.0, last_y)

    # Re-clamp interior points in case pinning an endpoint to 0.0/1.0
    # pushed it past a neighbor (only possible with pathological input).
    for i in range(1, len(clamped) - 1):
        x, y = clamped[i]
        lower = clamped[i - 1][0] + MIN_POINT_X_GAP
        upper = clamped[i + 1][0] - MIN_POINT_X_GAP
        if upper < lower:
            x = lower
        else:
            x = min(upper, max(lower, x))
        clamped[i] = (x, y)

    return tuple(clamped)


def is_identity_curve(points: Iterable[Sequence[float]] | None) -> bool:
    """True if ``points`` normalizes to the default straight-line curve."""
    normalized = normalize_points(points)
    return normalized == DEFAULT_CURVE_POINTS


def _pchip_slopes(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Fritsch-Carlson monotonic cubic tangents (weighted harmonic mean).

    Guarantees the interpolated curve never overshoots between control
    points -- important for a tone curve, where overshoot would show up as
    visible banding/posterization at a control point.
    """
    n = len(x)
    if n == 1:
        return np.zeros(1, dtype=np.float64)

    h = np.diff(x)
    delta = np.diff(y) / h
    m = np.zeros(n, dtype=np.float64)
    m[0] = delta[0]
    m[-1] = delta[-1]

    for i in range(1, n - 1):
        left, right = delta[i - 1], delta[i]
        if left == 0.0 or right == 0.0 or (left > 0) != (right > 0):
            m[i] = 0.0
        else:
            w1 = 2.0 * h[i] + h[i - 1]
            w2 = h[i] + 2.0 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / left + w2 / right)

    return m


def build_curve_lut(
    points: Iterable[Sequence[float]] | None, resolution: int = 256
) -> np.ndarray:
    """Sample the monotonic cubic curve through ``points`` into a LUT.

    Returns a ``float32`` array of length ``resolution``, evenly spaced
    over ``x in [0, 1]``, clamped to ``[0, 1]``.
    """
    pts = normalize_points(points)
    sample_x = np.linspace(0.0, 1.0, resolution, dtype=np.float64)

    xs = np.array([p[0] for p in pts], dtype=np.float64)
    ys = np.array([p[1] for p in pts], dtype=np.float64)

    if len(pts) == 1:
        return np.full(resolution, np.clip(ys[0], 0.0, 1.0), dtype=np.float32)

    m = _pchip_slopes(xs, ys)

    idx = np.clip(np.searchsorted(xs, sample_x, side="right") - 1, 0, len(xs) - 2)
    x0, x1 = xs[idx], xs[idx + 1]
    y0, y1 = ys[idx], ys[idx + 1]
    m0, m1 = m[idx], m[idx + 1]

    h = x1 - x0
    h_safe = np.where(h == 0.0, 1.0, h)
    t = (sample_x - x0) / h_safe
    t2 = t * t
    t3 = t2 * t

    h00 = 2.0 * t3 - 3.0 * t2 + 1.0
    h10 = t3 - 2.0 * t2 + t
    h01 = -2.0 * t3 + 3.0 * t2
    h11 = t3 - t2

    y = h00 * y0 + h10 * h * m0 + h01 * y1 + h11 * h * m1
    return np.clip(y, 0.0, 1.0).astype(np.float32)


def apply_curve_lut(values: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """Map ``values`` (any shape, in ``[0, 1]``) through ``lut``."""
    resolution = lut.shape[0]
    sample_x = np.linspace(0.0, 1.0, resolution, dtype=np.float32)
    return np.interp(values, sample_x, lut).astype(np.float32)


_LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def compute_luminance_histogram(image: np.ndarray, bins: int = 256) -> np.ndarray:
    """256-bin luminance histogram of ``image`` in the sRGB-encoded domain.

    Uses the sRGB-encoded (perceptual) domain, matching the domain the
    curve's x-axis represents, so the histogram lines up with the grid a
    user drags points against.
    """
    from src.utils.color_pipeline import linear_to_srgb

    srgb = linear_to_srgb(np.asarray(image, dtype=np.float32)[..., :3])
    luminance = srgb @ _LUMA_WEIGHTS
    counts, _ = np.histogram(luminance, bins=bins, range=(0.0, 1.0))
    return counts.astype(np.int64)


__all__ = [
    "Point",
    "DEFAULT_CURVE_POINTS",
    "MIN_POINT_X_GAP",
    "normalize_points",
    "is_identity_curve",
    "build_curve_lut",
    "apply_curve_lut",
    "compute_luminance_histogram",
]
