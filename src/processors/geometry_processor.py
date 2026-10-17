"""Lens/perspective geometry correction for linear-light images.

This is Phase I's ("Geometry and Crop", PDF sections 19-20) second
slice, filling in the slider-based half of "Geometry" that
:mod:`src.processors.straighten_processor` deliberately left out (see
that module's docstring section 1): **Distortion**, **Vertical**/
**Horizontal** perspective, **Scale**, and **X/Y Offset**. See
docs/planning/implementation-notes/2026-10-13-geometry-processor.md
for the full design rationale, including why Upright modes (Auto/
Guided/Level/Vertical/Full) and "Constrain Crop" remain explicitly out
of scope (they need vanishing-point detection or a dedicated
guided-line UI -- both much larger efforts than a plain-slider
processor).

Like every geometric processor in this codebase
(:class:`~src.processors.straighten_processor.StraightenProcessor`,
:class:`~src.processors.remove_chromatic_aberration_processor.RemoveChromaticAberrationProcessor`),
``GeometryProcessor`` preserves the exact input ``(H, W, C)`` shape and
fills any border newly exposed by a warp via ``cv2.BORDER_REFLECT_101``.

Pipeline, in order:

1. **Distortion** -- a radial lens-distortion correction, applied via
   ``cv2.remap`` with a single-term (``k1``) radial model (see
   :meth:`GeometryProcessor._apply_distortion`).
2. **Horizontal** perspective, then **Vertical** perspective, then
   **Scale**, then **Offset** -- each a homography/affine matrix
   expressed over the image's own corners, composed into ONE combined
   3x3 matrix and applied with a single ``cv2.warpPerspective`` call
   (see :meth:`GeometryProcessor._build_combined_matrix`). Composing
   them avoids three/four separate resample passes (each of which
   would re-interpolate and soften the image) for the common case of
   several of these sliders being touched at once.

Every parameter defaults to its own "no change" identity value
(``0.0`` for distortion/vertical/horizontal/offset_x/offset_y, ``100.0``
for scale). When ALL FIVE are at their identity value, :meth:`process`
returns ``source.copy()`` immediately -- no matrix is built, no
``cv2`` warp function is called -- mirroring
``StraightenProcessor.process``'s exact zero-cost-identity discipline
(both for performance, and so the all-defaults case is an exact
identity test).
"""

from __future__ import annotations

import cv2
import numpy as np

from src.processors.base_processor import BaseProcessor
from src.utils.color_pipeline import LinearImage


class GeometryProcessor(BaseProcessor):
    """Apply Distortion, Vertical/Horizontal perspective, Scale, and X/Y
    Offset corrections, preserving the exact input shape.

    Ranges (all ``0``/``100`` values below are the "no change" identity):

    - ``distortion``: ``-100`` .. ``100``, default ``0``. Negative
      values correct barrel distortion (pull in the edges); positive
      values correct pincushion distortion (push out the edges) -- see
      section 3 of the implementation note for the empirically-verified
      sign convention and the chosen ``k1`` constant.
    - ``vertical``: ``-100`` .. ``100``, default ``0``. Keystone
      correction for vertical (top/bottom) convergence -- see section 4.
    - ``horizontal``: ``-100`` .. ``100``, default ``0``. Keystone
      correction for horizontal (left/right) convergence -- mirrors
      ``vertical``'s construction, rotated 90 degrees.
    - ``scale``: ``50`` .. ``150`` (percent), default ``100``. Uniform
      zoom around the image center; ``>100`` zooms in, ``<100`` zooms
      out (border-filled).
    - ``offset_x``, ``offset_y``: ``-50`` .. ``50`` (percent of width/
      height respectively), default ``0``. Pixel-space translation.
    """

    _DISTORTION_MIN = -100.0
    _DISTORTION_MAX = 100.0
    _VERTICAL_MIN = -100.0
    _VERTICAL_MAX = 100.0
    _HORIZONTAL_MIN = -100.0
    _HORIZONTAL_MAX = 100.0
    _SCALE_MIN = 50.0
    _SCALE_MAX = 150.0
    _OFFSET_MIN = -50.0
    _OFFSET_MAX = 50.0

    # Tuned so that distortion=+/-100 produces a clearly visible but not
    # absurd warp: at a 100x100 reference image, this moves the corners
    # by roughly 8-9 px (~8-9% of the half-diagonal) -- see the
    # implementation note section 3 for the measurement this was tuned
    # against.
    _DISTORTION_K = 0.35

    # The maximum fraction of the image's half-width/half-height that
    # a vertical/horizontal perspective slider may shift a near/far
    # edge's corners by, at the slider's extreme (+/-100). Kept well
    # below 1.0 so the mapped quadrilateral never degenerates (a corner
    # crossing the image's own center line) even at the extremes -- see
    # the implementation note section 4.
    _PERSPECTIVE_MAX_FRACTION = 0.4

    def process(
        self,
        image: LinearImage,
        distortion: float = 0.0,
        vertical: float = 0.0,
        horizontal: float = 0.0,
        scale: float = 100.0,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
    ) -> LinearImage:
        """Apply Distortion, Vertical/Horizontal perspective, Scale, and
        Offset, in that order, preserving the exact input shape."""
        source = np.asarray(image, dtype=np.float32)

        distortion = float(
            np.clip(distortion, self._DISTORTION_MIN, self._DISTORTION_MAX)
        )
        vertical = float(np.clip(vertical, self._VERTICAL_MIN, self._VERTICAL_MAX))
        horizontal = float(
            np.clip(horizontal, self._HORIZONTAL_MIN, self._HORIZONTAL_MAX)
        )
        scale = float(np.clip(scale, self._SCALE_MIN, self._SCALE_MAX))
        offset_x = float(np.clip(offset_x, self._OFFSET_MIN, self._OFFSET_MAX))
        offset_y = float(np.clip(offset_y, self._OFFSET_MIN, self._OFFSET_MAX))

        if (
            distortion == 0.0
            and vertical == 0.0
            and horizontal == 0.0
            and scale == 100.0
            and offset_x == 0.0
            and offset_y == 0.0
        ):
            return source.copy()

        height, width = source.shape[0], source.shape[1]
        result = source

        if distortion != 0.0:
            result = self._apply_distortion(result, distortion)

        if vertical != 0.0 or horizontal != 0.0 or scale != 100.0 or \
           offset_x != 0.0 or offset_y != 0.0:
            matrix = self._build_combined_matrix(
                width, height, vertical, horizontal, scale, offset_x, offset_y
            )
            result = cv2.warpPerspective(
                result,
                matrix,
                (width, height),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT_101,
            )

        return result.astype(np.float32, copy=False)

    def _apply_distortion(self, source: LinearImage, distortion: float) -> LinearImage:
        """Radial lens-distortion correction via a single-term (``k1``)
        model, applied with ``cv2.remap``.

        Uses a synthetic camera matrix (``fx = fy = max(width,
        height)``, principal point at the image center) and maps each
        OUTPUT pixel back to its source location via
        ``source = normalized * (1 + k1 * r^2)``, the standard
        single-term Brown-Conrady radial model evaluated directly
        (rather than via ``cv2.undistort``, which expects a distorted
        source and independently chosen output camera matrix -- this
        direct remap keeps the sign convention and the identity-at-r=0
        behavior explicit and easy to reason about).
        """
        height, width = source.shape[0], source.shape[1]
        fx = fy = float(max(width, height))
        cx, cy = (width - 1) / 2.0, (height - 1) / 2.0

        # See the class docstring/implementation note: the sign is
        # inverted relative to the user-facing slider so that negative
        # `distortion` (correct barrel) pulls edges IN and positive
        # (correct pincushion) pushes edges OUT -- verified empirically
        # against this exact formula, not assumed.
        k1 = -(distortion / 100.0) * self._DISTORTION_K

        xs, ys = np.meshgrid(
            np.arange(width, dtype=np.float32),
            np.arange(height, dtype=np.float32),
        )
        xn = (xs - cx) / fx
        yn = (ys - cy) / fy
        radial = 1.0 + k1 * (xn * xn + yn * yn)
        map_x = (xn * radial * fx + cx).astype(np.float32)
        map_y = (yn * radial * fy + cy).astype(np.float32)

        result = cv2.remap(
            source,
            map_x,
            map_y,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )
        return result.astype(np.float32, copy=False)

    def _build_combined_matrix(
        self,
        width: int,
        height: int,
        vertical: float,
        horizontal: float,
        scale: float,
        offset_x: float,
        offset_y: float,
    ) -> np.ndarray:
        """Return one combined 3x3 homography for horizontal perspective,
        then vertical perspective, then scale, then offset (applied to a
        point in that order: ``offset @ scale @ vertical @ horizontal``).

        Composing four matrices into one keeps a single ``cv2.warpPerspective``
        resample pass regardless of how many of these four sliders are
        touched at once, instead of re-interpolating (and softening the
        image) once per active slider.
        """
        matrix = np.eye(3, dtype=np.float64)

        # A degenerate 1-pixel-wide or 1-pixel-tall image has coincident
        # corners along that axis, which makes getPerspectiveTransform's
        # 4-point solve singular (producing a NaN-filled matrix). Both
        # keystone corrections are meaningless for such an image anyway
        # (there is no "top/bottom" or "left/right" edge to tilt), so
        # they are skipped rather than guarded with a special-cased
        # fallback matrix -- mirroring how Straighten/Remove CA simply
        # verified (rather than special-cased) their own tiny-image
        # behavior.
        perspective_safe = width >= 2 and height >= 2
        if horizontal != 0.0 and perspective_safe:
            matrix = self._horizontal_matrix(width, height, horizontal) @ matrix
        if vertical != 0.0 and perspective_safe:
            matrix = self._vertical_matrix(width, height, vertical) @ matrix
        if scale != 100.0:
            matrix = self._scale_matrix(width, height, scale) @ matrix
        if offset_x != 0.0 or offset_y != 0.0:
            matrix = self._offset_matrix(width, height, offset_x, offset_y) @ matrix

        return matrix.astype(np.float32)

    def _vertical_matrix(
        self, width: int, height: int, vertical: float
    ) -> np.ndarray:
        """Homography tilting the top/bottom edges horizontally in
        opposite directions (keystone correction for vertical/building-
        convergence perspective).

        Positive ``vertical`` narrows the top edge and widens the bottom
        edge (adds/exaggerates the "shot looking up at a tall subject"
        convergence look); negative widens the top and narrows the
        bottom (the common real-world correction direction -- undoing
        that convergence so verticals become parallel). Verified
        empirically against this exact corner mapping, the same way
        Straighten's own sign convention was -- see the implementation
        note section 4.
        """
        shift = (vertical / 100.0) * self._PERSPECTIVE_MAX_FRACTION * (width / 2.0)
        src = np.float32(
            [[0, 0], [width - 1, 0], [0, height - 1], [width - 1, height - 1]]
        )
        dst = np.float32(
            [
                [0 + shift, 0],
                [width - 1 - shift, 0],
                [0 - shift, height - 1],
                [width - 1 + shift, height - 1],
            ]
        )
        return cv2.getPerspectiveTransform(src, dst).astype(np.float64)

    def _horizontal_matrix(
        self, width: int, height: int, horizontal: float
    ) -> np.ndarray:
        """Homography tilting the left/right edges vertically in
        opposite directions (keystone correction for horizontal
        convergence) -- the 90-degree-rotated counterpart of
        :meth:`_vertical_matrix`.

        Positive ``horizontal`` narrows the left edge's height and
        widens the right edge's height; negative does the opposite.
        """
        shift = (horizontal / 100.0) * self._PERSPECTIVE_MAX_FRACTION * (height / 2.0)
        src = np.float32(
            [[0, 0], [width - 1, 0], [0, height - 1], [width - 1, height - 1]]
        )
        dst = np.float32(
            [
                [0, 0 + shift],
                [width - 1, 0 - shift],
                [0, height - 1 - shift],
                [width - 1, height - 1 + shift],
            ]
        )
        return cv2.getPerspectiveTransform(src, dst).astype(np.float64)

    def _scale_matrix(self, width: int, height: int, scale: float) -> np.ndarray:
        """Affine (as a 3x3 homography) uniform zoom around the image
        center. ``scale`` is a percentage (``100`` == no change)."""
        center = ((width - 1) / 2.0, (height - 1) / 2.0)
        affine = cv2.getRotationMatrix2D(center, 0.0, scale / 100.0)
        return np.vstack([affine, [0.0, 0.0, 1.0]]).astype(np.float64)

    def _offset_matrix(
        self, width: int, height: int, offset_x: float, offset_y: float
    ) -> np.ndarray:
        """Translation (as a 3x3 homography), in pixels, derived from
        ``offset_x``/``offset_y`` percentages of width/height
        respectively. Positive values shift image content right/down."""
        tx = (offset_x / 100.0) * width
        ty = (offset_y / 100.0) * height
        return np.array(
            [[1.0, 0.0, tx], [0.0, 1.0, ty], [0.0, 0.0, 1.0]], dtype=np.float64
        )
