"""Base processor class for image processing operations."""

from abc import ABC, abstractmethod

from src.utils.color_pipeline import LinearImage


class BaseProcessor(ABC):
    """Abstract base class for image processors.

    All concrete processors operate on the canonical pipeline format:
    ``np.ndarray``, shape ``(H, W, 3)``, dtype ``float32``, values in
    ``[0, 1]``, **linear-light** with sRGB primaries (see
    :mod:`src.utils.color_pipeline`).

    Implementations should treat the input as immutable and return a
    new array. Out-of-gamut values (``< 0`` or ``> 1``) are allowed to
    flow through; clipping happens at the boundary (PIL/QImage), not in
    every processor.
    """

    @abstractmethod
    def process(self, image: LinearImage, **kwargs) -> LinearImage:
        """Process a linear-light float32 image.

        Args:
            image: Input ``LinearImage`` (see module docstring).
            **kwargs: Processor-specific parameters.

        Returns:
            A new ``LinearImage`` with adjustments applied.
        """
        pass
