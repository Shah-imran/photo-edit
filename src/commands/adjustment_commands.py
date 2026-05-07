"""Adjustment commands for undo/redo functionality."""

from typing import Any, Dict, Optional

from src.commands.base_command import BaseCommand
from src.models.image_model import ImageModel
from src.processors.color_processor import ColorProcessor
from src.processors.exposure_processor import ExposureProcessor
from src.utils.color_pipeline import LinearImage


class AdjustmentCommand(BaseCommand):
    """Command for applying image adjustments.
    
    This command stores the adjustment parameters and can apply/unapply them
    for undo/redo functionality.
    """

    def __init__(
        self,
        image_model: ImageModel,
        adjustment_type: str,
        parameters: Dict[str, float],
        previous_image: Optional[LinearImage] = None,
    ):
        """Initialize the adjustment command.

        Args:
            image_model: The image model to modify.
            adjustment_type: Type of adjustment ('exposure', 'color').
            parameters: Dictionary of adjustment parameters.
            previous_image: The ``LinearImage`` state before adjustment (for undo).
        """
        super().__init__()
        self._image_model = image_model
        self._adjustment_type = adjustment_type
        self._parameters = parameters
        self._previous_image = (
            previous_image
            if previous_image is not None
            else image_model.get_current_image()
        )
        self._new_image: Optional[LinearImage] = None

        self._exposure_processor = ExposureProcessor()
        self._color_processor = ColorProcessor()

    def execute(self) -> None:
        """Execute the adjustment command."""
        super().execute()

        original = self._image_model.get_original_image()
        if original is None:
            return

        if self._adjustment_type == "exposure":
            self._new_image = self._exposure_processor.process(
                original, **self._parameters
            )
        elif self._adjustment_type == "color":
            self._new_image = self._color_processor.process(
                original, **self._parameters
            )

        if self._new_image is not None:
            self._image_model.current_image = self._new_image
            self._image_model.set_modified(True)

    def undo(self) -> None:
        """Undo the adjustment command."""
        super().undo()

        if self._previous_image is not None:
            self._image_model.current_image = self._previous_image

    def get_parameters(self) -> Dict[str, float]:
        """Get the adjustment parameters.
        
        Returns:
            Dictionary of parameters
        """
        return self._parameters.copy()


class CombinedAdjustmentCommand(BaseCommand):
    """Command for applying multiple adjustments at once.
    
    This command combines exposure and color adjustments into a single
    operation for better performance and cleaner undo/redo.
    """

    def __init__(
        self,
        image_model: ImageModel,
        exposure_params: Dict[str, float] = None,
        color_params: Dict[str, float] = None
    ):
        """Initialize the combined adjustment command.
        
        Args:
            image_model: The image model to modify
            exposure_params: Exposure adjustment parameters
            color_params: Color adjustment parameters
        """
        super().__init__()
        self._image_model = image_model
        self._exposure_params = exposure_params or {}
        self._color_params = color_params or {}
        self._previous_image = image_model.get_current_image()
        self._new_image: Optional[LinearImage] = None

        self._exposure_processor = ExposureProcessor()
        self._color_processor = ColorProcessor()

    def execute(self) -> None:
        """Execute the combined adjustment command."""
        super().execute()

        original = self._image_model.get_original_image()
        if original is None:
            return

        result = original.copy()

        if self._exposure_params:
            result = self._exposure_processor.process(result, **self._exposure_params)

        if self._color_params:
            result = self._color_processor.process(result, **self._color_params)

        self._new_image = result
        self._image_model.current_image = result
        self._image_model.set_modified(True)

    def undo(self) -> None:
        """Undo the combined adjustment command."""
        super().undo()

        if self._previous_image is not None:
            self._image_model.current_image = self._previous_image


class ImageStateChangeCommand(BaseCommand):
    """Command that records an already-rendered image state.

    This is used by the threaded adjustment path: the worker has already
    performed the expensive processing, so history must not re-run the
    processors on the UI thread.
    """

    def __init__(
        self,
        image_model: ImageModel,
        previous_image: LinearImage,
        new_image: LinearImage,
    ):
        super().__init__()
        self._image_model = image_model
        self._previous_image = previous_image
        self._new_image = new_image

    def execute(self) -> None:
        """Apply the already-rendered new image."""
        super().execute()
        self._image_model.current_image = self._new_image
        self._image_model.set_modified(True)

    def undo(self) -> None:
        """Restore the image state from before this adjustment gesture."""
        super().undo()
        self._image_model.current_image = self._previous_image
