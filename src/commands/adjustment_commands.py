"""Adjustment commands for undo/redo functionality."""

from typing import Dict, Any, Optional
from PIL import Image
from src.commands.base_command import BaseCommand
from src.models.image_model import ImageModel
from src.processing.adjustment_pipeline import apply_basic_adjustments
from src.processors.exposure_processor import ExposureProcessor
from src.processors.color_processor import ColorProcessor


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
        previous_image: Optional[Image.Image] = None
    ):
        """Initialize the adjustment command.
        
        Args:
            image_model: The image model to modify
            adjustment_type: Type of adjustment ('exposure', 'color')
            parameters: Dictionary of adjustment parameters
            previous_image: The image state before adjustment (for undo)
        """
        super().__init__()
        self._image_model = image_model
        self._adjustment_type = adjustment_type
        self._parameters = parameters
        self._previous_image = previous_image or image_model.get_current_image()
        self._new_image: Optional[Image.Image] = None
        
        # Processors
        self._exposure_processor = ExposureProcessor()
        self._color_processor = ColorProcessor()

    def execute(self) -> None:
        """Execute the adjustment command."""
        super().execute()
        
        # Get the original image to apply adjustments to
        original = self._image_model.get_original_image()
        if original is None:
            return
        
        # Apply all accumulated adjustments
        if self._adjustment_type == 'exposure':
            self._new_image = self._exposure_processor.process(
                original,
                **self._parameters
            )
        elif self._adjustment_type == 'color':
            self._new_image = self._color_processor.process(
                original,
                **self._parameters
            )
        
        # Update the model
        if self._new_image:
            self._image_model.current_image = self._new_image
            self._image_model.set_modified(True)

    def undo(self) -> None:
        """Undo the adjustment command."""
        super().undo()
        
        # Restore the previous image
        if self._previous_image:
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
        tonal_params: Dict[str, float] = None,
        color_params: Dict[str, float] = None,
        new_image: Optional[Image.Image] = None
    ):
        """Initialize the combined adjustment command.

        Args:
            image_model: The image model to modify
            exposure_params: Exposure adjustment parameters
            tonal_params: Highlights/Shadows/Whites/Blacks parameters
            color_params: Color adjustment parameters
            new_image: Optional pre-computed result for these parameters
                (e.g. already produced by the background processing worker's
                full-resolution render). When provided, ``execute()`` reuses
                it instead of recomputing the same full-resolution adjustment
                a second time on the calling thread.
        """
        super().__init__()
        self._image_model = image_model
        self._exposure_params = exposure_params or {}
        self._tonal_params = tonal_params or {}
        self._color_params = color_params or {}
        self._previous_image = image_model.get_current_image()
        self._new_image: Optional[Image.Image] = new_image

    def execute(self) -> None:
        """Execute the combined adjustment command."""
        super().execute()

        if self._new_image is None:
            original = self._image_model.get_original_image()
            if original is None:
                return

            self._new_image = apply_basic_adjustments(
                original,
                exposure_params=self._exposure_params,
                tonal_params=self._tonal_params,
                color_params=self._color_params,
            )

        self._image_model.current_image = self._new_image
        self._image_model.set_modified(True)

    def undo(self) -> None:
        """Undo the combined adjustment command."""
        super().undo()
        
        if self._previous_image:
            self._image_model.current_image = self._previous_image
