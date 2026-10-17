"""Adjustment commands for undo/redo functionality."""

from typing import TYPE_CHECKING, Any, Dict, Optional

from src.commands.base_command import BaseCommand
from src.models.image_model import ImageModel
from src.processors.color_processor import ColorProcessor
from src.processors.exposure_processor import ExposureProcessor
from src.processing.pipeline import shared_pipeline
from src.utils.color_pipeline import LinearImage

if TYPE_CHECKING:
    # Avoided as a real top-level import: image_controller.py already
    # imports FROM this module (CombinedAdjustmentCommand,
    # ImageStateChangeCommand, AdjustmentStateCommand), so a top-level
    # `from src.controllers.image_controller import ImageController` here
    # would be a circular import. Only needed for the type hint below.
    from src.controllers.image_controller import ImageController


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
        tonal_params: Dict[str, float] = None,
        color_params: Dict[str, float] = None,
        curve_params: Dict[str, Any] = None,
        wb_params: Dict[str, float] = None,
        hsl_params: Dict[str, float] = None,
        color_grading_params: Dict[str, float] = None,
        texture_params: Dict[str, float] = None,
        clarity_params: Dict[str, float] = None,
        dehaze_params: Dict[str, float] = None,
        vignette_params: Dict[str, float] = None,
        grain_params: Dict[str, float] = None,
        sharpening_params: Dict[str, float] = None,
        luminance_nr_params: Dict[str, float] = None,
        color_nr_params: Dict[str, float] = None,
        remove_ca_params: Dict[str, float] = None,
        defringe_params: Dict[str, float] = None,
        geometry_params: Dict[str, float] = None,
        straighten_params: Dict[str, float] = None,
        crop_params: Dict[str, float] = None,
        mask_params: Dict[str, Any] = None,
        healing_params: Dict[str, Any] = None,
    ):
        """Initialize the combined adjustment command.

        Args:
            image_model: The image model to modify
            exposure_params: Exposure adjustment parameters
            tonal_params: Highlights/Shadows/Whites/Blacks parameters
            color_params: Color adjustment parameters
            curve_params: Tone curve parameters (``{"points": [...]}``)
            wb_params: White balance (Temperature/Tint) parameters
            hsl_params: HSL Color Mixer parameters (24-key flat dict)
            color_grading_params: Color Grading parameters (11-key flat dict)
        """
        super().__init__()
        self._image_model = image_model
        self._exposure_params = exposure_params or {}
        self._tonal_params = tonal_params or {}
        self._color_params = color_params or {}
        self._curve_params = curve_params or {}
        self._wb_params = wb_params or {}
        self._hsl_params = hsl_params or {}
        self._color_grading_params = color_grading_params or {}
        self._previous_image = image_model.get_current_image()
        self._new_image: Optional[LinearImage] = None

        self._texture_params = texture_params or {}
        self._clarity_params = clarity_params or {}
        self._dehaze_params = dehaze_params or {}
        self._vignette_params = vignette_params or {}
        self._grain_params = grain_params or {}
        self._sharpening_params = sharpening_params or {}
        self._luminance_nr_params = luminance_nr_params or {}
        self._color_nr_params = color_nr_params or {}
        self._remove_ca_params = remove_ca_params or {}
        self._defringe_params = defringe_params or {}
        self._geometry_params = geometry_params or {}
        self._straighten_params = straighten_params or {}
        self._crop_params = crop_params or {}
        self._mask_params = mask_params or {}
        self._healing_params = healing_params or {}

    def execute(self) -> None:
        """Execute the combined adjustment command."""
        super().execute()

        original = self._image_model.get_original_image()
        if original is None:
            return

        result = shared_pipeline().render(
            original,
            exposure_params=self._exposure_params,
            tonal_params=self._tonal_params,
            color_params=self._color_params,
            curve_params=self._curve_params,
            wb_params=self._wb_params,
            hsl_params=self._hsl_params,
            color_grading_params=self._color_grading_params,
            texture_params=self._texture_params,
            clarity_params=self._clarity_params,
            dehaze_params=self._dehaze_params,
            vignette_params=self._vignette_params,
            grain_params=self._grain_params,
            sharpening_params=self._sharpening_params,
            luminance_nr_params=self._luminance_nr_params,
            color_nr_params=self._color_nr_params,
            remove_ca_params=self._remove_ca_params,
            defringe_params=self._defringe_params,
            geometry_params=self._geometry_params,
            straighten_params=self._straighten_params,
            crop_params=self._crop_params,
            mask_params=self._mask_params,
            healing_params=self._healing_params,
        )

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


class AdjustmentStateCommand(BaseCommand):
    """Undo/redo command that restores a full (image, adjustment-state)
    snapshot via ``ImageController.apply_history_state`` -- not just the
    pixel buffer.

    This supersedes ``CombinedAdjustmentCommand``/``ImageStateChangeCommand``
    as the object actually pushed onto the undo/redo stack: those two
    classes are kept, unused by this new flow but still exercised by their
    own direct unit tests and still reused for their pixel-computation
    logic (``CombinedAdjustmentCommand.execute()`` in the synchronous
    fallback path), a deliberate choice to minimize unrelated test churn.
    See docs/planning/implementation-notes/
    2026-10-13-state-aware-undo-redo.md.
    """

    def __init__(
        self,
        controller: "ImageController",
        previous_image: LinearImage,
        previous_state: Dict[str, Any],
        new_image: LinearImage,
        new_state: Dict[str, Any],
    ):
        """Initialize the adjustment-state command.

        Args:
            controller: The ``ImageController`` whose
                ``apply_history_state`` performs the actual restore.
            previous_image: Rendered image before this edit gesture.
            previous_state: Full adjustment-state dict (the same shape
                ``ImageController.get_adjustment_state()`` returns) before
                this edit gesture.
            new_image: Rendered image after this edit gesture.
            new_state: Full adjustment-state dict after this edit gesture.
        """
        super().__init__()
        self._controller = controller
        self._previous_image = previous_image
        self._previous_state = previous_state
        self._new_image = new_image
        self._new_state = new_state

    def execute(self) -> None:
        """Apply the post-edit (image, adjustment-state) snapshot."""
        super().execute()
        self._controller.apply_history_state(self._new_image, self._new_state)

    def undo(self) -> None:
        """Restore the pre-edit (image, adjustment-state) snapshot."""
        super().undo()
        self._controller.apply_history_state(
            self._previous_image, self._previous_state
        )
