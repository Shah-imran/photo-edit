"""Unit tests for adjustment commands."""

from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image

from src.commands.adjustment_commands import AdjustmentStateCommand
from src.models.image_model import ImageModel
from src.utils.color_pipeline import pil_to_linear


@pytest.fixture
def sample_linear_image(sample_image):
    return pil_to_linear(sample_image)


class TestAdjustmentStateCommand:
    """Test cases for AdjustmentStateCommand -- the state-aware command
    ImageController actually pushes onto history. See
    docs/planning/implementation-notes/2026-10-13-state-aware-undo-redo.md.
    """

    def _make_command(self, sample_linear_image):
        controller = MagicMock()
        previous_image = sample_linear_image
        new_image = sample_linear_image.copy()
        previous_state = {"exposure": 0.0}
        new_state = {"exposure": 1.0}
        command = AdjustmentStateCommand(
            controller=controller,
            previous_image=previous_image,
            previous_state=previous_state,
            new_image=new_image,
            new_state=new_state,
        )
        return controller, command, previous_image, previous_state, new_image, new_state

    def test_execute_calls_apply_history_state_with_new_snapshot(
        self, sample_linear_image
    ):
        controller, command, _, _, new_image, new_state = self._make_command(
            sample_linear_image
        )

        command.execute()

        controller.apply_history_state.assert_called_once_with(new_image, new_state)

    def test_undo_calls_apply_history_state_with_previous_snapshot(
        self, sample_linear_image
    ):
        controller, command, previous_image, previous_state, _, _ = (
            self._make_command(sample_linear_image)
        )

        command.execute()
        controller.apply_history_state.reset_mock()
        command.undo()

        controller.apply_history_state.assert_called_once_with(
            previous_image, previous_state
        )

    def test_undo_before_execute_raises(self, sample_linear_image):
        _, command, _, _, _, _ = self._make_command(sample_linear_image)

        with pytest.raises(RuntimeError):
            command.undo()

    def test_execute_twice_raises(self, sample_linear_image):
        _, command, _, _, _, _ = self._make_command(sample_linear_image)

        command.execute()
        with pytest.raises(RuntimeError):
            command.execute()

    def test_redo_after_undo_calls_apply_history_state_with_new_snapshot(
        self, sample_linear_image
    ):
        controller, command, _, _, new_image, new_state = self._make_command(
            sample_linear_image
        )

        command.execute()
        command.undo()
        controller.apply_history_state.reset_mock()
        command.redo()

        controller.apply_history_state.assert_called_once_with(new_image, new_state)
