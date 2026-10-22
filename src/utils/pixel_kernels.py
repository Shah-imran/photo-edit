"""Compiled, multi-threaded pixel kernels with NumPy fallbacks.

The develop pipeline's hot loops run here. When Numba is installed each
kernel is JIT-compiled (``parallel=True``, cached on disk) and spreads rows
across all cores; otherwise the NumPy reference implementation runs. Both
paths must agree to within float32 rounding -- the tests check it.

Numba turned the 24 MP tone-curve lookup from ~430 ms (NumPy gather) into
~30 ms. See docs/planning/PERFORMANCE_OVERHAUL.md (Phases 3 and 5).
"""

from __future__ import annotations

import logging
import threading
import os
from time import perf_counter

import numpy as np

logger = logging.getLogger(__name__)

try:  # pragma: no cover - availability depends on the environment
    if os.environ.get("PHOTOEDIT_DISABLE_NUMBA") == "1":
        raise ImportError("disabled by PHOTOEDIT_DISABLE_NUMBA")
    import numba
    from numba import njit, prange

    # Numba's OpenMP pool crashed the process (access violation) once
    # OpenCV and Qt had loaded their own threading runtimes; the built-in
    # workqueue pool is stable. It must not be entered from two threads at
    # once, so every kernel call goes through _KERNEL_LOCK -- the preview
    # and full-resolution workers simply take turns (kernels run in ms).
    if "NUMBA_THREADING_LAYER" not in os.environ:
        numba.config.THREADING_LAYER = "workqueue"
    HAVE_NUMBA = True
except ImportError:  # pragma: no cover
    HAVE_NUMBA = False

_KERNEL_LOCK = threading.Lock()
_WARMED_UP = False


# -- Per-channel lookup tables -------------------------------------------


def _channel_luts_numpy(
    image: np.ndarray, luts: np.ndarray, active: np.ndarray, out: np.ndarray
) -> None:
    size = luts.shape[1]
    clipped = np.clip(np.nan_to_num(image[..., :3], nan=0.0), 0.0, 1.0)
    for channel in range(3):
        if active[channel]:
            # float64 index math, same as the compiled kernel.
            index = (
                clipped[..., channel].astype(np.float64) * (size - 1) + 0.5
            ).astype(np.int32)
            out[..., channel] = luts[channel][index]
        else:
            out[..., channel] = clipped[..., channel]


if HAVE_NUMBA:

    @njit(parallel=True, cache=True, fastmath=False)
    def _channel_luts_numba(image, luts, active, out):  # pragma: no cover
        height, width = image.shape[0], image.shape[1]
        top = luts.shape[1] - 1
        for y in prange(height):
            for x in range(width):
                for c in range(3):
                    v = image[y, x, c]
                    # "not (v >= 0)" also catches NaN, which would otherwise
                    # become an out-of-bounds table index.
                    if not (v >= 0.0):
                        v = 0.0
                    elif v > 1.0:
                        v = 1.0
                    if active[c]:
                        out[y, x, c] = luts[c, int(v * top + 0.5)]
                    else:
                        out[y, x, c] = v


def apply_channel_luts(
    image: np.ndarray, luts: np.ndarray, active=(True, True, True)
) -> np.ndarray:
    """Map each RGB channel through its own table.

    Args:
        image: ``(H, W, C>=3)`` float32 linear image. Channels after the
            third (e.g. alpha) are copied unchanged.
        luts: ``(3, N)`` float32 tables sampled uniformly over ``[0, 1]``.
        active: per-channel flags; an inactive channel is only clipped to
            ``[0, 1]`` (what the sRGB round-trip it replaces did).

    Returns:
        A new float32 array shaped like ``image``.
    """
    image = np.ascontiguousarray(image, dtype=np.float32)
    out = np.empty_like(image)
    if image.shape[2] > 3:
        out[..., 3:] = image[..., 3:]
    active_arr = np.asarray(active, dtype=np.bool_)
    if HAVE_NUMBA:
        with _KERNEL_LOCK:
            _channel_luts_numba(image, np.ascontiguousarray(luts), active_arr, out)
    else:
        _channel_luts_numpy(image, luts, active_arr, out)
    return out


# -- Stage kernels ---------------------------------------------------------
#
# Each mirrors its processor's NumPy implementation operation for operation
# (same float32 arithmetic order, same lookup-table indexing), so results
# match within float32 rounding. The processor keeps the NumPy code as the
# fallback and as the reference the parity tests compare against.

if HAVE_NUMBA:

    @njit(parallel=True, cache=True)
    def _exposure_kernel(  # pragma: no cover
        image, out, exposure_mul, brightness_mul, do_exposure, do_brightness,
        do_contrast, contrast_factor, lin_to_srgb, srgb_to_lin, srgb_min,
        srgb_max, srgb_scale,
    ):
        height, width, channels = image.shape
        top = np.float32(lin_to_srgb.shape[0] - 1)
        half = np.float32(0.5)
        for y in prange(height):
            for x in range(width):
                for c in range(channels):
                    v = image[y, x, c]
                    if do_exposure:
                        v = v * exposure_mul
                    if do_brightness:
                        v = v * brightness_mul
                    if do_contrast:
                        t = v
                        if not (t >= 0.0):
                            t = np.float32(0.0)
                        elif t > 1.0:
                            t = np.float32(1.0)
                        s = lin_to_srgb[int(t * top)]
                        a = (s - half) * contrast_factor + half
                        if a < srgb_min:
                            a = srgb_min
                        elif a > srgb_max:
                            a = srgb_max
                        v = srgb_to_lin[int((a - srgb_min) * srgb_scale)]
                    out[y, x, c] = v

    @njit(parallel=True, cache=True)
    def _tonal_kernel(  # pragma: no cover
        image, out, do_points, black_point, span, highlights, shadows,
        recovery, wr, wg, wb,
    ):
        height, width, channels = image.shape
        half = np.float32(0.5)
        one = np.float32(1.0)
        three = np.float32(3.0)
        two = np.float32(2.0)
        for y in prange(height):
            for x in range(width):
                r = image[y, x, 0]
                g = image[y, x, 1]
                b = image[y, x, 2]
                if do_points:
                    r = (r - black_point) / span
                    g = (g - black_point) / span
                    b = (b - black_point) / span
                if highlights != 0.0:
                    lum = r * wr + g * wg + b * wb
                    t = (lum - half) / half
                    t = min(max(t, np.float32(0.0)), one)
                    weight = t * t * (three - two * t)
                    k = highlights * weight
                    r = r + k * (one - r) * recovery
                    g = g + k * (one - g) * recovery
                    b = b + k * (one - b) * recovery
                if shadows != 0.0:
                    lum = r * wr + g * wg + b * wb
                    t = (lum - half) / -half
                    t = min(max(t, np.float32(0.0)), one)
                    weight = t * t * (three - two * t)
                    k = shadows * weight
                    r = r + k * r * recovery
                    g = g + k * g * recovery
                    b = b + k * b * recovery
                out[y, x, 0] = r
                out[y, x, 1] = g
                out[y, x, 2] = b
                for c in range(3, channels):
                    out[y, x, c] = image[y, x, c]

    @njit(parallel=True, cache=True)
    def _vignette_kernel(  # pragma: no cover
        image, out, half_h, half_w, inv_sqrt2, midpoint, span, strength,
        darken, lighten_color,
    ):
        height, width, channels = image.shape
        one = np.float32(1.0)
        for y in prange(height):
            dy = (np.float32(y) + np.float32(0.5) - half_h) / half_h
            for x in range(width):
                dx = (np.float32(x) + np.float32(0.5) - half_w) / half_w
                radius = np.sqrt(dx * dx + dy * dy) * inv_sqrt2
                radius = min(max(radius, np.float32(0.0)), one)
                t = (radius - midpoint) / span
                t = min(max(t, np.float32(0.0)), one)
                edge = t * t * (np.float32(3.0) - np.float32(2.0) * t)
                for c in range(channels):
                    v = image[y, x, c]
                    if darken:
                        out[y, x, c] = v * (one - edge * strength)
                    else:
                        out[y, x, c] = v + (lighten_color - v) * edge * strength


if HAVE_NUMBA:
    # OpenCV's float RGB<->HSV conversion (H in degrees, S/V in [0, 1]),
    # reproduced so HSV-based stages can run in one fused pass. Matches
    # cv2.cvtColor to ~3e-5 degrees of hue and ~1e-7 in RGB.
    _FLT_EPS = np.float32(np.finfo(np.float32).eps)

    @njit(cache=True, inline="always")
    def _rgb_to_hsv(r, g, b):  # pragma: no cover
        v = max(max(r, g), b)
        vmin = min(min(r, g), b)
        diff = v - vmin
        s = diff / (abs(v) + _FLT_EPS)
        d = np.float32(60.0) / (diff + _FLT_EPS)
        if v == r:
            h = (g - b) * d
        elif v == g:
            h = (b - r) * d + np.float32(120.0)
        else:
            h = (r - g) * d + np.float32(240.0)
        if h < 0.0:
            h += np.float32(360.0)
        return h, s, v

    @njit(cache=True, inline="always")
    def _hsv_to_rgb(h, s, v):  # pragma: no cover
        if s == 0.0:
            return v, v, v
        hh = h * np.float32(1.0 / 60.0)
        while hh < 0.0:
            hh += np.float32(6.0)
        while hh >= 6.0:
            hh -= np.float32(6.0)
        sector = int(np.floor(hh))
        f = hh - np.float32(sector)
        if sector < 0 or sector > 5:
            sector = 0
            f = np.float32(0.0)
        p = v * (np.float32(1.0) - s)
        q = v * (np.float32(1.0) - s * f)
        t = v * (np.float32(1.0) - s * (np.float32(1.0) - f))
        if sector == 0:
            return v, t, p
        if sector == 1:
            return q, v, p
        if sector == 2:
            return p, v, t
        if sector == 3:
            return p, q, v
        if sector == 4:
            return t, p, v
        return v, p, q

    @njit(cache=True, inline="always")
    def _clip01(x):  # pragma: no cover
        if not (x >= 0.0):
            return np.float32(0.0)
        if x > 1.0:
            return np.float32(1.0)
        return x

    @njit(parallel=True, cache=True)
    def _color_kernel(image, out, vibrance, do_vibrance, sat_factor, do_saturation):  # pragma: no cover
        height, width = image.shape[0], image.shape[1]
        half = np.float32(0.5)
        one = np.float32(1.0)
        for y in prange(height):
            for x in range(width):
                r = image[y, x, 0]
                g = image[y, x, 1]
                b = image[y, x, 2]
                if do_vibrance:
                    h, s, v = _rgb_to_hsv(_clip01(r), _clip01(g), _clip01(b))
                    s = _clip01(s + vibrance * (one - s) * half)
                    r, g, b = _hsv_to_rgb(h, s, v)
                if do_saturation:
                    h, s, v = _rgb_to_hsv(_clip01(r), _clip01(g), _clip01(b))
                    s = _clip01(s * sat_factor)
                    r, g, b = _hsv_to_rgb(h, s, v)
                out[y, x, 0] = r
                out[y, x, 1] = g
                out[y, x, 2] = b

    @njit(parallel=True, cache=True)
    def _hsl_kernel(  # pragma: no cover
        image, out, centers, hue_shift, sat_amount, lum_amount, band_width,
    ):
        height, width, channels = image.shape
        bands = centers.shape[0]
        half_width = band_width / 2.0
        two_pi = 2.0 * np.pi
        for y in prange(height):
            for x in range(width):
                h, s, v = _rgb_to_hsv(
                    _clip01(image[y, x, 0]), _clip01(image[y, x, 1]), _clip01(image[y, x, 2])
                )
                shift = 0.0
                sat_f = 0.0
                lum_d = 0.0
                for i in range(bands):
                    signed = ((h - centers[i] + 180.0) % 360.0) - 180.0
                    distance = abs(signed)
                    if distance < half_width:
                        weight = 0.5 * (1.0 + np.cos(two_pi * distance / band_width))
                        shift += weight * hue_shift[i]
                        sat_f += weight * sat_amount[i]
                        lum_d += weight * lum_amount[i]
                new_h = np.float32((h + shift) % 360.0)
                new_s = _clip01(np.float32(s * (1.0 + sat_f)))
                new_v = _clip01(np.float32(v + lum_d))
                r, g, b = _hsv_to_rgb(new_h, new_s, new_v)
                out[y, x, 0] = r
                out[y, x, 1] = g
                out[y, x, 2] = b
                for c in range(3, channels):
                    out[y, x, c] = image[y, x, c]

    @njit(parallel=True, cache=True)
    def _grading_kernel(  # pragma: no cover
        image, out, centers, width_, amounts, tints, lums,
    ):
        height, width, channels = image.shape
        half_w = width_ / 2.0
        two_pi = 2.0 * np.pi
        for y in prange(height):
            for x in range(width):
                r = image[y, x, 0]
                g = image[y, x, 1]
                b = image[y, x, 2]
                v = max(max(_clip01(r), _clip01(g)), _clip01(b))
                w0 = 0.0
                w1 = 0.0
                w2 = 0.0
                d = abs(v - centers[0])
                if d < half_w:
                    w0 = 0.5 * (1.0 + np.cos(two_pi * d / width_))
                d = abs(v - centers[1])
                if d < half_w:
                    w1 = 0.5 * (1.0 + np.cos(two_pi * d / width_))
                d = abs(v - centers[2])
                if d < half_w:
                    w2 = 0.5 * (1.0 + np.cos(two_pi * d / width_))
                total = w0 + w1 + w2
                if total > 0.0:
                    w0 /= total
                    w1 /= total
                    w2 /= total
                else:
                    w0 = 0.0
                    w1 = 0.0
                    w2 = 0.0
                a0 = w0 * amounts[0]
                a1 = w1 * amounts[1]
                a2 = w2 * amounts[2]
                amount = a0 + a1 + a2
                lum = w0 * lums[0] + w1 * lums[1] + w2 * lums[2]
                if amount < 0.0:
                    amount = 0.0
                elif amount > 1.0:
                    amount = 1.0
                keep = 1.0 - amount
                for c in range(3):
                    numerator = a0 * tints[0, c] + a1 * tints[1, c] + a2 * tints[2, c]
                    tint = numerator / amount if amount > 0.0 else 0.0
                    out[y, x, c] = np.float32(
                        image[y, x, c] * keep + tint * amount + lum
                    )
                for c in range(3, channels):
                    out[y, x, c] = image[y, x, c]

    @njit(parallel=True, cache=True)
    def _luma_kernel(image, out):  # pragma: no cover
        height, width = image.shape[0], image.shape[1]
        for y in prange(height):
            for x in range(width):
                out[y, x] = (
                    np.float32(0.2126) * image[y, x, 0]
                    + np.float32(0.7152) * image[y, x, 1]
                    + np.float32(0.0722) * image[y, x, 2]
                )

    @njit(parallel=True, cache=True)
    def _defringe_kernel(  # pragma: no cover
        image, luma, gx, gy, out, amount, edge_eps, chroma_gate, purple, green,
        band_width,
    ):
        height, width, channels = image.shape
        for y in prange(height):
            for x in range(width):
                ax = gx[y, x] / np.float32(8.0)
                ay = gy[y, x] / np.float32(8.0)
                grad = np.sqrt(ax * ax + ay * ay)
                edge = grad / (grad + edge_eps)
                cr = _clip01(image[y, x, 0])
                cg = _clip01(image[y, x, 1])
                cb = _clip01(image[y, x, 2])
                maxc = max(max(cr, cg), cb)
                minc = min(min(cr, cg), cb)
                delta = maxc - minc
                safe = np.float32(1.0) if delta < 1e-6 else delta
                if maxc == cr:
                    hue = 60.0 * (((cg - cb) / safe) % 6.0)
                elif maxc == cg:
                    hue = 60.0 * ((cb - cr) / safe + 2.0)
                else:
                    hue = 60.0 * ((cr - cg) / safe + 4.0)
                chroma = min(max(delta / chroma_gate, 0.0), 1.0)
                dp = abs(hue - purple) % 360.0
                dp = min(dp, 360.0 - dp)
                dg = abs(hue - green) % 360.0
                dg = min(dg, 360.0 - dg)
                membership = np.exp(-0.5 * (dp / band_width) ** 2) + np.exp(
                    -0.5 * (dg / band_width) ** 2
                )
                membership = min(max(membership, 0.0), 1.0) * chroma
                strength = amount * edge * membership
                neutral = luma[y, x]
                for c in range(3):
                    v = image[y, x, c]
                    out[y, x, c] = np.float32(v + strength * (neutral - v))
                for c in range(3, channels):
                    v = image[y, x, c]
                    out[y, x, c] = np.float32(v + strength * (neutral - v))


def _run(kernel, *args) -> None:
    with _KERNEL_LOCK:
        kernel(*args)


def exposure(image, exposure_mul, brightness_mul, contrast_factor, lin_to_srgb,
             srgb_to_lin, srgb_min, srgb_max):
    """Exposure/brightness/contrast in one pass, or None without Numba.

    Pass ``None`` for any multiplier/factor whose slider is at zero.
    """
    if not HAVE_NUMBA:
        return None
    image = np.ascontiguousarray(image, dtype=np.float32)
    out = np.empty_like(image)
    f32 = np.float32
    scale = f32((lin_to_srgb.shape[0] - 1) / (srgb_max - srgb_min))

    def value(x):  # 0.0 is a real factor (slider at -100); only None is "off"
        return f32(1.0) if x is None else f32(x)

    _run(
        _exposure_kernel, image, out,
        value(exposure_mul), value(brightness_mul),
        exposure_mul is not None, brightness_mul is not None,
        contrast_factor is not None, value(contrast_factor),
        lin_to_srgb, srgb_to_lin, f32(srgb_min), f32(srgb_max), scale,
    )
    return out


def tonal(image, black_point, span, highlights, shadows, recovery, weights):
    """Whites/blacks, highlights and shadows in one pass, or None.

    ``black_point``/``span`` are None when whites and blacks are zero;
    ``highlights``/``shadows`` are the slider values divided by 100.
    """
    if not HAVE_NUMBA:
        return None
    image = np.ascontiguousarray(image, dtype=np.float32)
    out = np.empty_like(image)
    f32 = np.float32
    _run(
        _tonal_kernel, image, out, black_point is not None,
        f32(0.0 if black_point is None else black_point),
        f32(1.0 if span is None else span), f32(highlights),
        f32(shadows), f32(recovery), f32(weights[0]), f32(weights[1]),
        f32(weights[2]),
    )
    return out


def vignette(image, midpoint, strength, darken, lighten_color):
    """Radial vignette in one pass, or None without Numba."""
    if not HAVE_NUMBA:
        return None
    image = np.ascontiguousarray(image, dtype=np.float32)
    out = np.empty_like(image)
    f32 = np.float32
    height, width = image.shape[0], image.shape[1]
    _run(
        _vignette_kernel, image, out,
        f32(max(height / 2.0, 1e-6)), f32(max(width / 2.0, 1e-6)),
        f32(1.0 / np.sqrt(2.0)), f32(midpoint), f32(max(1.0 - midpoint, 1e-6)),
        f32(strength), bool(darken), f32(lighten_color),
    )
    return out


def color(image, vibrance, saturation_factor):
    """Vibrance then saturation (HSV-based) in one pass, or None.

    ``vibrance`` is the slider value / 100 and ``saturation_factor`` the
    clipped ``1 + value / 100`` multiplier; pass None for an untouched one.
    Only plain RGB images are supported (the reference uses cv2 HSV).
    """
    if not HAVE_NUMBA or image.shape[2] != 3:
        return None
    image = np.ascontiguousarray(image, dtype=np.float32)
    out = np.empty_like(image)
    f32 = np.float32
    _run(
        _color_kernel, image, out,
        f32(0.0 if vibrance is None else vibrance), vibrance is not None,
        f32(1.0 if saturation_factor is None else saturation_factor),
        saturation_factor is not None,
    )
    return out


def hsl(image, centers, hue_shift, sat_amount, lum_amount, band_width):
    """8-band HSL mixer in one pass, or None. Per-band arrays are already
    scaled (degrees of hue shift, saturation factor, value delta)."""
    if not HAVE_NUMBA:
        return None
    image = np.ascontiguousarray(image, dtype=np.float32)
    out = np.empty_like(image)
    _run(
        _hsl_kernel, image, out,
        np.asarray(centers, dtype=np.float64),
        np.asarray(hue_shift, dtype=np.float64),
        np.asarray(sat_amount, dtype=np.float64),
        np.asarray(lum_amount, dtype=np.float64),
        float(band_width),
    )
    return out


def color_grading(image, centers, width, amounts, tints, lums):
    """Shadows/midtones/highlights grading in one pass, or None."""
    if not HAVE_NUMBA:
        return None
    image = np.ascontiguousarray(image, dtype=np.float32)
    out = np.empty_like(image)
    _run(
        _grading_kernel, image, out,
        np.asarray(centers, dtype=np.float64), float(width),
        np.asarray(amounts, dtype=np.float64),
        np.ascontiguousarray(tints, dtype=np.float64),
        np.asarray(lums, dtype=np.float64),
    )
    return out


def luma(image):
    """Rec. 709 luminance plane, or None without Numba."""
    if not HAVE_NUMBA:
        return None
    image = np.ascontiguousarray(image, dtype=np.float32)
    out = np.empty(image.shape[:2], dtype=np.float32)
    _run(_luma_kernel, image, out)
    return out


def defringe(image, luma_plane, gx, gy, amount, edge_eps, chroma_gate, purple,
             green, band_width):
    """Purple/green fringe removal given precomputed Sobel gradients."""
    if not HAVE_NUMBA:
        return None
    image = np.ascontiguousarray(image, dtype=np.float32)
    out = np.empty_like(image)
    _run(
        _defringe_kernel, image, luma_plane, np.ascontiguousarray(gx),
        np.ascontiguousarray(gy), out, float(amount), float(edge_eps),
        float(chroma_gate), float(purple), float(green), float(band_width),
    )
    return out



if HAVE_NUMBA:
    # Arithmetic around the blurs of the spatial stages (the blurs stay in
    # OpenCV). Each replaces several full-image NumPy passes with one.

    @njit(parallel=True, cache=True)
    def _unsharp_kernel(source, blurred, amount, out):  # pragma: no cover
        height, width, channels = source.shape
        for y in prange(height):
            for x in range(width):
                for c in range(channels):
                    v = source[y, x, c]
                    out[y, x, c] = v + amount * (v - blurred[y, x, c])

    @njit(parallel=True, cache=True)
    def _masked_unsharp_kernel(source, blurred, amount, eps, out):  # pragma: no cover
        height, width, channels = source.shape
        for y in prange(height):
            for x in range(width):
                for c in range(channels):
                    v = source[y, x, c]
                    d = v - blurred[y, x, c]
                    m = abs(d)
                    out[y, x, c] = v + amount * d * (m / (m + eps))

    @njit(parallel=True, cache=True)
    def _dark_channel_kernel(source, out):  # pragma: no cover
        height, width = source.shape[0], source.shape[1]
        for y in prange(height):
            for x in range(width):
                out[y, x] = min(min(source[y, x, 0], source[y, x, 1]), source[y, x, 2])

    @njit(parallel=True, cache=True)
    def _dehaze_kernel(source, veil, strength, denom, out):  # pragma: no cover
        height, width, channels = source.shape
        for y in prange(height):
            for x in range(width):
                k = strength * veil[y, x]
                for c in range(channels):
                    out[y, x, c] = (source[y, x, c] - k) / denom

    @njit(parallel=True, cache=True)
    def _chroma_split_kernel(source, wr, wg, wb, luminance, chroma):  # pragma: no cover
        height, width = source.shape[0], source.shape[1]
        for y in prange(height):
            for x in range(width):
                r = source[y, x, 0]
                b = source[y, x, 2]
                lum = wr * r + wg * source[y, x, 1] + wb * b
                luminance[y, x] = lum
                chroma[y, x, 0] = r - lum
                chroma[y, x, 1] = b - lum

    @njit(parallel=True, cache=True)
    def _chroma_merge_kernel(luminance, chroma, smoothed, t, wr, wg, wb, out):  # pragma: no cover
        height, width = luminance.shape[0], luminance.shape[1]
        for y in prange(height):
            for x in range(width):
                cr = chroma[y, x, 0] + t * (smoothed[y, x, 0] - chroma[y, x, 0])
                cb = chroma[y, x, 1] + t * (smoothed[y, x, 1] - chroma[y, x, 1])
                lum = luminance[y, x]
                out[y, x, 0] = lum + cr
                out[y, x, 1] = lum - (wr * cr + wb * cb) / wg
                out[y, x, 2] = lum + cb


def unsharp(source, blurred, amount):
    """``source + amount * (source - blurred)`` in one pass, or None."""
    if not HAVE_NUMBA:
        return None
    source = np.ascontiguousarray(source, dtype=np.float32)
    out = np.empty_like(source)
    _run(_unsharp_kernel, source, np.ascontiguousarray(blurred, dtype=np.float32),
         np.float32(amount), out)
    return out


def masked_unsharp(source, blurred, amount, eps):
    """Edge-masked unsharp mask (sharpening) in one pass, or None."""
    if not HAVE_NUMBA:
        return None
    source = np.ascontiguousarray(source, dtype=np.float32)
    out = np.empty_like(source)
    _run(_masked_unsharp_kernel, source, np.ascontiguousarray(blurred, dtype=np.float32),
         np.float32(amount), np.float32(eps), out)
    return out


def dark_channel(source):
    """Per-pixel min over R, G, B, or None."""
    if not HAVE_NUMBA:
        return None
    source = np.ascontiguousarray(source, dtype=np.float32)
    out = np.empty(source.shape[:2], dtype=np.float32)
    _run(_dark_channel_kernel, source, out)
    return out


def dehaze_combine(source, veil, strength, denom):
    """``(source - strength * veil) / denom`` in one pass, or None."""
    if not HAVE_NUMBA:
        return None
    source = np.ascontiguousarray(source, dtype=np.float32)
    out = np.empty_like(source)
    _run(_dehaze_kernel, source, np.ascontiguousarray(veil, dtype=np.float32),
         np.float32(strength), np.float32(denom), out)
    return out


def chroma_split(source, weights):
    """``(luminance, chroma)`` with chroma = (R - Y, B - Y), or None."""
    if not HAVE_NUMBA:
        return None
    source = np.ascontiguousarray(source, dtype=np.float32)
    luminance = np.empty(source.shape[:2], dtype=np.float32)
    chroma = np.empty(source.shape[:2] + (2,), dtype=np.float32)
    wr, wg, wb = (np.float32(w) for w in weights)
    _run(_chroma_split_kernel, source, wr, wg, wb, luminance, chroma)
    return luminance, chroma


def chroma_merge(luminance, chroma, smoothed, t, weights):
    """Blend chroma toward ``smoothed`` by ``t`` and rebuild RGB, or None."""
    if not HAVE_NUMBA:
        return None
    out = np.empty(luminance.shape + (3,), dtype=np.float32)
    wr, wg, wb = (np.float32(w) for w in weights)
    _run(_chroma_merge_kernel, luminance, chroma,
         np.ascontiguousarray(smoothed, dtype=np.float32), np.float32(t), wr, wg, wb, out)
    return out



if HAVE_NUMBA:
    # Local-adjustment masks: the mask weight (linear or radial gradient),
    # the local exposure/contrast/saturation and the blend in one pass.
    # Mirrors MaskProcessor._process_numpy (ExposureProcessor's LUT
    # contrast, ColorProcessor's HSV saturation).

    @njit(cache=True, inline="always")
    def _mask_alpha(x, y, width, height, mtype, geom, invert):  # pragma: no cover
        if mtype == 0:  # linear: 0 at (x0, y0) rising to 1 at (x1, y1)
            x0 = geom[0] * width
            y0 = geom[1] * height
            dx = geom[2] * width - x0
            dy = geom[3] * height - y0
            length_sq = dx * dx + dy * dy
            if length_sq < 1e-9:
                alpha = 1.0
            else:
                t = ((x + 0.5 - x0) * dx + (y + 0.5 - y0) * dy) / length_sq
                alpha = min(max(t, 0.0), 1.0)
        else:  # radial ellipse with a smoothstep feather
            px = (x + 0.5) / max(width, 1.0)
            py = (y + 0.5) / max(height, 1.0)
            ddx = (px - geom[0]) / geom[2]
            ddy = (py - geom[1]) / geom[3]
            dist = np.sqrt(ddx * ddx + ddy * ddy)
            feather = geom[4]
            inner = max(1.0 - feather, 0.0)
            span = max(feather, 1e-6)
            t = min(max((dist - inner) / span, 0.0), 1.0)
            alpha = 1.0 - t * t * (3.0 - 2.0 * t)
            alpha = min(max(alpha, 0.0), 1.0)
        a = np.float32(alpha)
        if invert:
            a = np.float32(1.0) - a
        return a

    @njit(cache=True, inline="always")
    def _mask_tone(  # pragma: no cover
        v, exposure_mul, do_exposure, contrast_factor, do_contrast,
        lin_to_srgb, srgb_to_lin, srgb_min, srgb_max, srgb_scale,
    ):
        if do_exposure:
            v = v * exposure_mul
        if do_contrast:
            t = v
            if not (t >= 0.0):
                t = np.float32(0.0)
            elif t > 1.0:
                t = np.float32(1.0)
            sv = lin_to_srgb[int(t * np.float32(lin_to_srgb.shape[0] - 1))]
            a = (sv - np.float32(0.5)) * contrast_factor + np.float32(0.5)
            if a < srgb_min:
                a = srgb_min
            elif a > srgb_max:
                a = srgb_max
            v = srgb_to_lin[int((a - srgb_min) * srgb_scale)]
        return v

    @njit(cache=True, inline="always")
    def _mask_local_pixel(  # pragma: no cover
        r, g, b, exposure_mul, do_exposure, contrast_factor, do_contrast,
        lin_to_srgb, srgb_to_lin, srgb_min, srgb_max, srgb_scale, sat_factor, do_sat,
    ):
        # Scalars only: a per-pixel tuple/list here is a heap allocation.
        r = _mask_tone(r, exposure_mul, do_exposure, contrast_factor, do_contrast,
                       lin_to_srgb, srgb_to_lin, srgb_min, srgb_max, srgb_scale)
        g = _mask_tone(g, exposure_mul, do_exposure, contrast_factor, do_contrast,
                       lin_to_srgb, srgb_to_lin, srgb_min, srgb_max, srgb_scale)
        b = _mask_tone(b, exposure_mul, do_exposure, contrast_factor, do_contrast,
                       lin_to_srgb, srgb_to_lin, srgb_min, srgb_max, srgb_scale)
        if do_sat:
            h, sv, vv = _rgb_to_hsv(_clip01(r), _clip01(g), _clip01(b))
            sv = _clip01(sv * sat_factor)
            r, g, b = _hsv_to_rgb(h, sv, vv)
        return r, g, b

    @njit(parallel=True, cache=True)
    def _mask_local_kernel(  # pragma: no cover
        source, out, exposure_mul, do_exposure, contrast_factor, do_contrast,
        lin_to_srgb, srgb_to_lin, srgb_min, srgb_max, srgb_scale, sat_factor, do_sat,
    ):
        height, width = source.shape[0], source.shape[1]
        for y in prange(height):
            for x in range(width):
                r, g, b = _mask_local_pixel(
                    source[y, x, 0], source[y, x, 1], source[y, x, 2],
                    exposure_mul, do_exposure, contrast_factor, do_contrast,
                    lin_to_srgb, srgb_to_lin, srgb_min, srgb_max, srgb_scale,
                    sat_factor, do_sat,
                )
                out[y, x, 0] = r
                out[y, x, 1] = g
                out[y, x, 2] = b

    @njit(parallel=True, cache=True)
    def _mask_blend_kernel(  # pragma: no cover
        source, local, use_local, out, mtype, geom, invert,
        exposure_mul, do_exposure, contrast_factor, do_contrast,
        lin_to_srgb, srgb_to_lin, srgb_min, srgb_max, srgb_scale, sat_factor, do_sat,
    ):
        height, width, channels = source.shape
        one = np.float32(1.0)
        for y in prange(height):
            for x in range(width):
                a = _mask_alpha(float(x), float(y), float(width), float(height), mtype, geom, invert)
                if a == 0.0:
                    for c in range(channels):
                        out[y, x, c] = source[y, x, c]
                    continue
                if use_local:
                    lr = local[y, x, 0]
                    lg = local[y, x, 1]
                    lb = local[y, x, 2]
                else:
                    lr, lg, lb = _mask_local_pixel(
                        source[y, x, 0], source[y, x, 1], source[y, x, 2],
                        exposure_mul, do_exposure, contrast_factor, do_contrast,
                        lin_to_srgb, srgb_to_lin, srgb_min, srgb_max, srgb_scale,
                        sat_factor, do_sat,
                    )
                keep = one - a
                out[y, x, 0] = source[y, x, 0] * keep + lr * a
                out[y, x, 1] = source[y, x, 1] * keep + lg * a
                out[y, x, 2] = source[y, x, 2] * keep + lb * a
                for c in range(3, channels):
                    out[y, x, c] = source[y, x, c]


def _mask_point_args(exposure_mul, contrast_factor, sat_factor, luts):
    lin_to_srgb, srgb_to_lin, srgb_min, srgb_max = luts
    f32 = np.float32
    return (
        f32(1.0 if exposure_mul is None else exposure_mul), exposure_mul is not None,
        f32(1.0 if contrast_factor is None else contrast_factor), contrast_factor is not None,
        lin_to_srgb, srgb_to_lin, f32(srgb_min), f32(srgb_max),
        f32((lin_to_srgb.shape[0] - 1) / (srgb_max - srgb_min)),
        f32(1.0 if sat_factor is None else sat_factor), sat_factor is not None,
    )


def mask_local(source, exposure_mul, contrast_factor, sat_factor, luts):
    """The mask's local exposure/contrast/saturation over every pixel, or
    None without Numba. ``None`` multipliers/factors mean "off"."""
    if not HAVE_NUMBA:
        return None
    source = np.ascontiguousarray(source, dtype=np.float32)
    out = np.empty(source.shape[:2] + (3,), dtype=np.float32)
    _run(_mask_local_kernel, source, out,
         *_mask_point_args(exposure_mul, contrast_factor, sat_factor, luts))
    return out


def mask_blend(source, local, mtype, geom, invert, exposure_mul, contrast_factor,
               sat_factor, luts):
    """Blend the mask's local adjustment into ``source`` by its weight, or
    None without Numba. ``local`` is a precomputed local image (used when
    local clarity needs a blur) or None to compute it per pixel."""
    if not HAVE_NUMBA:
        return None
    source = np.ascontiguousarray(source, dtype=np.float32)
    out = np.empty_like(source)
    use_local = local is not None
    local_arr = (np.ascontiguousarray(local, dtype=np.float32) if use_local
                 else np.zeros((1, 1, 3), dtype=np.float32))
    _run(_mask_blend_kernel, source, local_arr, use_local, out, int(mtype),
         np.asarray(geom, dtype=np.float64), bool(invert),
         *_mask_point_args(exposure_mul, contrast_factor, sat_factor, luts))
    return out


def warm_up() -> None:
    """Compile (or load from the on-disk cache) every kernel once.

    Call from a background thread at startup so the first slider move
    doesn't pay the one-off JIT cost (~1 s per kernel when uncached).
    """
    global _WARMED_UP
    if not HAVE_NUMBA or _WARMED_UP:
        return
    _WARMED_UP = True
    start = perf_counter()
    tiny = np.zeros((2, 2, 3), dtype=np.float32)
    apply_channel_luts(tiny, np.zeros((3, 4), dtype=np.float32))
    lut = np.zeros(8, dtype=np.float32)
    exposure(tiny, 2.0, 1.1, 1.2, lut, lut, -0.5, 1.5)
    tonal(tiny, 0.0, 1.0, 0.2, 0.2, 0.6, (0.2, 0.7, 0.1))
    vignette(tiny, 0.6, 0.5, True, 1.0)
    color(tiny, 0.2, 1.2)
    hsl(tiny, [0.0, 90.0], [10.0, 0.0], [0.2, 0.0], [0.0, 0.1], 90.0)
    color_grading(tiny, [0.0, 0.5, 1.0], 1.0, [0.1, 0.0, 0.0], np.zeros((3, 3)), [0.0, 0.1, 0.0])
    plane = luma(tiny)
    defringe(tiny, plane, plane, plane, 0.5, 0.1, 0.05, 290.0, 110.0, 25.0)
    unsharp(tiny, tiny, 0.5)
    masked_unsharp(tiny, tiny, 0.5, 0.02)
    dehaze_combine(tiny, dark_channel(tiny), 0.5, 0.6)
    lum, chroma = chroma_split(tiny, (0.2, 0.7, 0.1))
    chroma_merge(lum, chroma, chroma, 0.5, (0.2, 0.7, 0.1))
    luts = (np.zeros(8, np.float32), np.zeros(8, np.float32), -0.5, 1.5)
    mask_blend(tiny, None, 1, (0.5, 0.5, 0.3, 0.3, 0.5), False, 2.0, 1.2, 1.1, luts)
    mask_blend(tiny, mask_local(tiny, 2.0, 1.2, 1.1, luts), 0, (0.1, 0.1, 0.9, 0.9, 0.0),
               True, 2.0, 1.2, 1.1, luts)
    logger.info("PERF kernels.warm_up numba ms=%.0f", (perf_counter() - start) * 1000)
