"""Adjustment commands for undo/redo functionality."""

from typing import TYPE_CHECKING, Any, Dict

from src.commands.base_command import BaseCommand
from src.utils.color_pipeline import LinearImage

if TYPE_CHECKING:
    # Avoided as a real top-level import: image_controller.py already
    # imports FROM this module (CombinedAdjustmentCommand,
    # ImageStateChangeCommand, AdjustmentStateCommand), so a top-level
    # `from src.controllers.image_controller import ImageController` here
    # would be a circular import. Only needed for the type hint below.
    from src.controllers.image_controller import ImageController


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
