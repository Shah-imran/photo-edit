"""Healing brush (clone / content-aware heal) for linear-light images.

Phase J ("Healing and Masking", PDF sections 21-22) begins its Healing
half here with the data/processing-layer slice (slice 1 of 2) -- see
docs/planning/implementation-notes/2026-10-13-healing-processor.md for
the full design rationale. The interactive click-to-heal UI (placing
spots with the mouse, dragging a second point to pick the source, a
small "visualize spots" overlay) is a SEPARATE, later slice -- this one
only adds the processor, the adjustment-state/pipeline wiring, undo/redo
integration, and export correctness, plus a programmatic
(non-mouse-driven) way to set the complete list of spots
(``ImageController.on_heal_spots_changed``) that the later UI slice will
call into.

Unlike :class:`~src.processors.crop_processor.CropProcessor` (the one
processor that deliberately changes output shape), ``HealingProcessor``
preserves the exact input ``(H, W, C)`` shape -- healing blends pixel
VALUES within small local regions, it never removes or adds pixels. This
is also why it is safe to run FIRST in the pipeline, before every other
adjustment: healing is a repair operation on the "as-shot" pixels, not a
creative adjustment, and every later tonal/color/effects step should see
an already-healed image, exactly as Lightroom's own Spot Removal tool is
meant to be invisible groundwork. See the implementation note's pipeline-
ordering section for the full reasoning (this is the one genuinely new
architectural wrinkle in this slice, since every other Phase G/H/I/J
processor so far has been appended at a LATER pipeline position).

State shape (the ``"heal_spots"`` adjustment-state key): a list of dicts
(``[]`` by default -- a meaningful, falsy "no spots" value, following
the same falsy-skip convention every other processor in this codebase
already uses, just with a list instead of a dict/scalar):

.. code-block:: python

    {
        "dst_x": float, "dst_y": float,  # destination center, normalized [0, 1]
        "src_x": float, "src_y": float,  # source center, normalized [0, 1]
        "radius": float,                  # normalized fraction of min(width, height)
        "feather": float,                 # 0..1, soft-edge fraction of the radius
        "opacity": float,                 # 0..1, blend strength
        "mode": "heal" | "clone",
    }

Two modes only: **Clone** (a direct, feathered copy from source to
destination -- simple, cheap, always available, pure float32 arithmetic)
and **Heal** (a content-aware blend via OpenCV's own ``cv2.seamlessClone``,
which implements Poisson blending -- no Poisson-blending math is written
here, it is reused directly from OpenCV). ``cv2.seamlessClone`` requires
8-bit ``uint8`` input, but this pipeline works in linear-light float32
throughout, so Heal mode round-trips each spot's small working patch
through this codebase's EXISTING linear<->display conversion helpers
(:func:`~src.utils.color_pipeline.linear_to_srgb` /
:func:`~src.utils.color_pipeline.uint8_srgb_to_linear`) for that one
OpenCV call only -- a real, accepted v1 approximation (the Poisson blend
itself does not happen in true linear light), documented in depth in the
implementation note, including what was found empirically about 8-bit
round-trip precision. Clone mode has no such dependency at all -- it is
a pure float32 copy+feather.

No "auto-select a good source point" heuristic: ``src_x``/``src_y`` are
always caller-supplied. The later UI slice decides how to default or let
the user pick them; this processor only consumes whatever source point
it is given.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage, linear_to_srgb, uint8_srgb_to_linear

_HEAL_MODES = ("heal", "clone")

# cv2.seamlessClone can crash (a native C++ assertion/exception, not a
# Python-catchable ValueError in every OpenCV build) on a mask whose
# nonzero region is only a handful of pixels wide -- empirically
# confirmed with a 1-pixel mask on this environment's OpenCV 5.0.0. A
# spot this small has no visually meaningful "content-aware" blend to
# offer anyway, so below this pixel radius Heal mode silently falls back
# to Clone's own (always-safe) feathered-copy blend rather than risking
# a crash. See the implementation note for the empirical finding.
_MIN_HEAL_RADIUS_PX = 3

_SPOT_DEFAULTS: Dict[str, float] = {
    "dst_x": 0.5,
    "dst_y": 0.5,
    "src_x": 0.5,
    "src_y": 0.5,
    "radius": 0.05,
    "feather": 0.3,
    "opacity": 1.0,
}


class HealingProcessor(BaseProcessor):
    """Apply a list of independent clone/heal spots to a ``LinearImage``.

    ``heal_spots`` falsy (``None`` or ``[]``) is the documented "nothing
    to do" sentinel and returns an identity copy immediately, matching
    every other processor's zero-cost-skip convention. Each spot is
    defensively normalized/clamped; a spot with an unrecognized/missing
    ``"mode"`` or non-dict shape is skipped entirely rather than crashing
    the whole pipeline on one malformed entry (e.g. from old persisted
    data).
    """

    def process(
        self,
        image: LinearImage,
        heal_spots: Optional[List[Dict[str, Any]]] = None,
    ) -> LinearImage:
        """Apply every spot in ``heal_spots``, in order.

        Args:
            image: Input ``LinearImage``.
            heal_spots: A list of spot dicts (see module docstring), or
                ``None``/``[]`` for "no spots" -- returns an identity
                copy.

        Returns:
            New ``LinearImage``, same shape/dtype as the input.
        """
        source = np.asarray(image, dtype=np.float32)
        if not heal_spots:
            return source.copy()

        result = source.copy()
        for raw_spot in heal_spots:
            spot = self._normalize_spot(raw_spot)
            if spot is None:
                continue
            result = self._apply_spot(result, source, spot)
        return result.astype(np.float32, copy=False)

    # ------------------------------------------------------------------
    # Per-spot normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_spot(raw_spot: Any) -> Optional[Dict[str, Any]]:
        """Return a fully-clamped spot dict, or ``None`` to skip it.

        Never trusts the caller -- a spot may come from an old catalog
        entry, a malformed imported preset, or interactive UI input in
        the later slice. An unrecognized/missing ``"mode"`` or a
        non-dict entry is the one thing that skips the whole spot
        (there is no sensible default mode to fall back to); every other
        field is clamped/defaulted instead of rejected.
        """
        if not isinstance(raw_spot, dict):
            return None
        mode = raw_spot.get("mode")
        if mode not in _HEAL_MODES:
            return None

        def _safe_float(value: Any, default: float) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        spot: Dict[str, Any] = {"mode": mode}
        for key in ("dst_x", "dst_y", "src_x", "src_y"):
            value = _safe_float(raw_spot.get(key, _SPOT_DEFAULTS[key]), _SPOT_DEFAULTS[key])
            spot[key] = max(0.0, min(1.0, value))

        radius = _safe_float(raw_spot.get("radius", _SPOT_DEFAULTS["radius"]), _SPOT_DEFAULTS["radius"])
        spot["radius"] = max(1e-4, min(1.0, radius))

        feather = _safe_float(raw_spot.get("feather", _SPOT_DEFAULTS["feather"]), _SPOT_DEFAULTS["feather"])
        spot["feather"] = max(0.0, min(1.0, feather))

        opacity = _safe_float(raw_spot.get("opacity", _SPOT_DEFAULTS["opacity"]), _SPOT_DEFAULTS["opacity"])
        spot["opacity"] = max(0.0, min(1.0, opacity))

        return spot

    # ------------------------------------------------------------------
    # Per-spot application
    # ------------------------------------------------------------------

    def _apply_spot(
        self,
        result: np.ndarray,
        source: np.ndarray,
        spot: Dict[str, Any],
    ) -> np.ndarray:
        """Blend one spot into ``result``.

        ``source`` (the pristine, pre-this-processor image) is always
        what a spot's SOURCE patch is sampled from, never the
        progressively-edited ``result`` -- so spots never chain off each
        other's edits, keeping multi-spot application simple and order-
        independent for sampling (only the DESTINATION write order
        matters, for overlapping spots).
        """
        height, width = result.shape[0], result.shape[1]
        min_dim = max(float(min(height, width)), 1.0)
        radius_px = max(int(round(spot["radius"] * min_dim)), 1)

        dst_cx = min(max(int(round(spot["dst_x"] * width)), 0), width - 1)
        dst_cy = min(max(int(round(spot["dst_y"] * height)), 0), height - 1)
        src_cx = min(max(int(round(spot["src_x"] * width)), 0), width - 1)
        src_cy = min(max(int(round(spot["src_y"] * height)), 0), height - 1)

        # Clamp the patch's reach on each side to whichever of the
        # destination/source centers is closer to that edge, so the same
        # offsets are valid in-bounds for BOTH regions -- this is what
        # keeps a spot near the image edge from crashing or needing to
        # wrap/misalign: the patch is simply shrunk, symmetrically, to
        # whatever both centers can support.
        left_off = min(dst_cx, src_cx, radius_px)
        right_off = min(width - 1 - dst_cx, width - 1 - src_cx, radius_px)
        top_off = min(dst_cy, src_cy, radius_px)
        bottom_off = min(height - 1 - dst_cy, height - 1 - src_cy, radius_px)

        patch_h = top_off + bottom_off + 1
        patch_w = left_off + right_off + 1
        if patch_h <= 0 or patch_w <= 0:
            return result  # fully clipped away; nothing to do

        dst_top, dst_bottom = dst_cy - top_off, dst_cy + bottom_off + 1
        dst_left, dst_right = dst_cx - left_off, dst_cx + right_off + 1
        src_top, src_bottom = src_cy - top_off, src_cy + bottom_off + 1
        src_left, src_right = src_cx - left_off, src_cx + right_off + 1

        dst_region = result[dst_top:dst_bottom, dst_left:dst_right]
        src_region = source[src_top:src_bottom, src_left:src_right]

        alpha = self._patch_alpha(
            patch_h, patch_w, top_off, left_off, radius_px, spot["feather"]
        )
        spot_alpha = (alpha * spot["opacity"]).astype(np.float32)

        if spot["mode"] == "clone" or radius_px < _MIN_HEAL_RADIUS_PX:
            blended = self._clone_blend(dst_region, src_region, spot_alpha)
        else:
            blended = self._heal_blend(
                dst_region, src_region, spot_alpha, top_off, left_off, radius_px
            )

        result[dst_top:dst_bottom, dst_left:dst_right] = blended
        return result

    @staticmethod
    def _patch_alpha(
        patch_h: int,
        patch_w: int,
        center_y: int,
        center_x: int,
        radius_px: int,
        feather: float,
    ) -> np.ndarray:
        """Return a ``(patch_h, patch_w)`` float32 alpha field in ``[0, 1]``:
        1.0 at the spot's own center, falling to 0.0 at/beyond its
        pixel radius over a feathered outer band, reusing the same
        ``t * t * (3 - 2*t)`` cubic smoothstep
        :class:`~src.processors.mask_processor.MaskProcessor`/
        :class:`~src.processors.vignette_processor.VignetteProcessor`
        already use, for consistency with this codebase's established
        convention.
        """
        yy, xx = np.mgrid[0:patch_h, 0:patch_w].astype(np.float64)
        dist = np.sqrt((yy - center_y) ** 2 + (xx - center_x) ** 2)
        radius = max(float(radius_px), 1e-6)
        t = dist / radius

        inner = max(1.0 - feather, 0.0)
        span = max(feather, 1e-6)
        edge_t = np.clip((t - inner) / span, 0.0, 1.0)
        smooth = edge_t * edge_t * (3.0 - 2.0 * edge_t)
        alpha = 1.0 - smooth
        return np.clip(alpha, 0.0, 1.0).astype(np.float32)

    @staticmethod
    def _clone_blend(
        dst_region: np.ndarray, src_region: np.ndarray, spot_alpha: np.ndarray
    ) -> np.ndarray:
        """Direct, feathered float32 copy from source to destination."""
        alpha3 = spot_alpha[..., np.newaxis]
        return (dst_region * (1.0 - alpha3) + src_region * alpha3).astype(
            np.float32, copy=False
        )

    def _heal_blend(
        self,
        dst_region: np.ndarray,
        src_region: np.ndarray,
        spot_alpha: np.ndarray,
        center_y: int,
        center_x: int,
        radius_px: int,
    ) -> np.ndarray:
        """Content-aware (Poisson, via ``cv2.seamlessClone``) blend.

        Converts the small working patch to 8-bit via this codebase's
        existing linear<->display helpers (see module docstring), runs
        ``cv2.seamlessClone``, converts back, then blends the healed
        result into ``dst_region`` scaled by ``spot_alpha`` (the same
        feathered alpha field Clone uses) -- OpenCV's own
        ``seamlessClone`` has no opacity parameter, so opacity is applied
        here as a final linear interpolation, exactly like Clone's own
        blend.
        """
        patch_h, patch_w = dst_region.shape[0], dst_region.shape[1]
        dst_u8 = self._to_display_u8(dst_region)
        src_u8 = self._to_display_u8(src_region)

        mask_u8 = np.zeros((patch_h, patch_w), dtype=np.uint8)
        yy, xx = np.mgrid[0:patch_h, 0:patch_w]
        dist = np.sqrt((yy - center_y) ** 2 + (xx - center_x) ** 2)
        mask_u8[dist <= radius_px] = 255

        if not np.any(mask_u8):
            # Degenerate geometry (radius rounds to nothing within this
            # patch) -- fall back to Clone's always-safe blend.
            return self._clone_blend(dst_region, src_region, spot_alpha)

        center = (center_x, center_y)
        try:
            healed_u8 = cv2.seamlessClone(
                src_u8, dst_u8, mask_u8, center, cv2.NORMAL_CLONE
            )
        except cv2.error:
            # Defensive: a pathological geometry OpenCV itself rejects
            # (as a raisable cv2.error) falls back to Clone rather than
            # propagating a crash out of the processing pipeline.
            return self._clone_blend(dst_region, src_region, spot_alpha)

        healed_linear = uint8_srgb_to_linear(healed_u8)
        alpha3 = spot_alpha[..., np.newaxis]
        return (dst_region * (1.0 - alpha3) + healed_linear * alpha3).astype(
            np.float32, copy=False
        )

    @staticmethod
    def _to_display_u8(region: np.ndarray) -> np.ndarray:
        """Linear-light float32 -> sRGB-encoded uint8, for OpenCV only.

        Reuses :func:`~src.utils.color_pipeline.linear_to_srgb` (the
        actual OETF math -- not reimplemented here); only the trivial
        scale/round/clip-to-uint8 step is repeated locally, mirroring
        :mod:`src.utils.color_pipeline`'s own private
        ``_linear_to_srgb_u8`` helper exactly (that helper is private to
        its module, so this processor does not import it directly, but
        introduces no new conversion MATH of its own).
        """
        srgb = linear_to_srgb(region)
        scaled = np.round(srgb * 255.0)
        return np.ascontiguousarray(np.clip(scaled, 0.0, 255.0).astype(np.uint8))
