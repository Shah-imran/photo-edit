"""Unit tests for adjustment commands."""

from unittest.mock import MagicMock

import pytest
from PIL import Image

from src.commands.adjustment_commands import (
    AdjustmentCommand,
    AdjustmentStateCommand,
    CombinedAdjustmentCommand,
)
from src.models.image_model import ImageModel
from src.utils.color_pipeline import pil_to_linear


@pytest.fixture
def sample_linear_image(sample_image):
    return pil_to_linear(sample_image)


class TestAdjustmentCommand:
    """Test cases for AdjustmentCommand class."""

    def test_command_initialization(self, sample_linear_image):
        """Test AdjustmentCommand can be initialized."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        
        cmd = AdjustmentCommand(
            model,
            adjustment_type='exposure',
            parameters={'exposure': 1.0}
        )
        assert cmd is not None

    def test_execute_exposure_adjustment(self, sample_linear_image):
        """Test executing exposure adjustment."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        
        cmd = AdjustmentCommand(
            model,
            adjustment_type='exposure',
            parameters={'exposure': 1.0, 'contrast': 0.0, 'brightness': 0.0}
        )
        cmd.execute()
        
        assert cmd.is_executed() is True
        assert model.is_modified() is True

    def test_undo_adjustment(self, sample_linear_image):
        """Test undoing adjustment."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        original_image = model.get_current_image()
        
        cmd = AdjustmentCommand(
            model,
            adjustment_type='exposure',
            parameters={'exposure': 1.0}
        )
        cmd.execute()
        cmd.undo()
        
        assert cmd.is_executed() is False

    def test_get_parameters(self, sample_linear_image):
        """Test getting command parameters."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        params = {'exposure': 1.0, 'contrast': 50.0}
        
        cmd = AdjustmentCommand(
            model,
            adjustment_type='exposure',
            parameters=params
        )
        
        retrieved = cmd.get_parameters()
        assert retrieved == params


class TestCombinedAdjustmentCommand:
    """Test cases for CombinedAdjustmentCommand class."""

    def test_command_initialization(self, sample_linear_image):
        """Test CombinedAdjustmentCommand can be initialized."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        
        cmd = CombinedAdjustmentCommand(model)
        assert cmd is not None

    def test_execute_combined_adjustments(self, sample_linear_image):
        """Test executing combined adjustments."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        
        cmd = CombinedAdjustmentCommand(
            model,
            exposure_params={'exposure': 0.5, 'contrast': 10.0, 'brightness': 5.0},
            color_params={'saturation': 20.0, 'vibrance': 10.0}
        )
        cmd.execute()
        
        assert cmd.is_executed() is True
        assert model.is_modified() is True

    def test_undo_combined_adjustments(self, sample_linear_image):
        """Test undoing combined adjustments."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        
        cmd = CombinedAdjustmentCommand(
            model,
            exposure_params={'exposure': 1.0},
            color_params={'saturation': 50.0}
        )
        cmd.execute()
        cmd.undo()
        
        assert cmd.is_executed() is False

    def test_exposure_only(self, sample_linear_image):
        """Test with only exposure adjustments."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        
        cmd = CombinedAdjustmentCommand(
            model,
            exposure_params={'exposure': 2.0}
        )
        cmd.execute()
        
        assert cmd.is_executed() is True

    def test_color_only(self, sample_linear_image):
        """Test with only color adjustments."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)

        cmd = CombinedAdjustmentCommand(
            model,
            color_params={'saturation': 50.0}
        )
        cmd.execute()

        assert cmd.is_executed() is True

    def test_curve_only(self, sample_linear_image):
        """Test with only a tone curve adjustment."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)

        cmd = CombinedAdjustmentCommand(
            model,
            curve_params={'points': ((0.0, 0.0), (0.5, 0.7), (1.0, 1.0))},
        )
        cmd.execute()

        assert cmd.is_executed() is True
        assert model.is_modified() is True

    def test_undo_curve_only(self, sample_linear_image):
        """Test undoing a curve-only adjustment restores the previous image."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        previous = model.get_current_image()

        cmd = CombinedAdjustmentCommand(
            model,
            curve_params={'points': ((0.0, 0.0), (0.5, 0.7), (1.0, 1.0))},
        )
        cmd.execute()
        cmd.undo()

        assert cmd.is_executed() is False
        assert model.get_current_image() is previous

    def test_wb_only(self, sample_linear_image):
        """Test with only a white balance adjustment."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)

        cmd = CombinedAdjustmentCommand(
            model,
            wb_params={'temperature': 30.0, 'tint': -10.0},
        )
        cmd.execute()

        assert cmd.is_executed() is True
        assert model.is_modified() is True

    def test_undo_wb_only(self, sample_linear_image):
        """Test undoing a wb-only adjustment restores the previous image."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        previous = model.get_current_image()

        cmd = CombinedAdjustmentCommand(
            model,
            wb_params={'temperature': 30.0, 'tint': -10.0},
        )
        cmd.execute()
        cmd.undo()

        assert cmd.is_executed() is False
        assert model.get_current_image() is previous

    def test_color_grading_only(self, sample_linear_image):
        """Test with only a Color Grading adjustment."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)

        cmd = CombinedAdjustmentCommand(
            model,
            color_grading_params={'shadows_sat': 40.0, 'shadows_hue': 200.0},
        )
        cmd.execute()

        assert cmd.is_executed() is True
        assert model.is_modified() is True

    def test_undo_color_grading_only(self, sample_linear_image):
        """Test undoing a color-grading-only adjustment restores the previous image."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        previous = model.get_current_image()

        cmd = CombinedAdjustmentCommand(
            model,
            color_grading_params={'shadows_sat': 40.0, 'shadows_hue': 200.0},
        )
        cmd.execute()
        cmd.undo()

        assert cmd.is_executed() is False
        assert model.get_current_image() is previous

    def test_hsl_only(self, sample_linear_image):
        """Test with only an HSL Color Mixer adjustment."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)

        cmd = CombinedAdjustmentCommand(
            model,
            hsl_params={'red_sat': 40.0},
        )
        cmd.execute()

        assert cmd.is_executed() is True
        assert model.is_modified() is True

    def test_undo_hsl_only(self, sample_linear_image):
        """Test undoing an hsl-only adjustment restores the previous image."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        previous = model.get_current_image()

        cmd = CombinedAdjustmentCommand(
            model,
            hsl_params={'red_sat': 40.0},
        )
        cmd.execute()
        cmd.undo()

        assert cmd.is_executed() is False
        assert model.get_current_image() is previous

    def test_texture_only_and_undo(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        previous = model.get_current_image()
        command = CombinedAdjustmentCommand(
            model, texture_params={"texture": 50.0}
        )
        command.execute()
        assert model.is_modified() is True
        command.undo()
        assert model.get_current_image() is previous

    def test_clarity_only_and_undo(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        previous = model.get_current_image()
        command = CombinedAdjustmentCommand(
            model, clarity_params={"clarity": 50.0}
        )
        command.execute()
        assert model.is_modified() is True
        command.undo()
        assert model.get_current_image() is previous

    def test_dehaze_only_and_undo(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        previous = model.get_current_image()
        command = CombinedAdjustmentCommand(
            model, dehaze_params={"dehaze": 50.0}
        )
        command.execute()
        assert model.is_modified() is True

    def test_vignette_only_and_undo(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        previous = model.get_current_image()
        command = CombinedAdjustmentCommand(
            model, vignette_params={"vignette": 50.0}
        )
        command.execute()
        assert model.is_modified() is True
        command.undo()
        assert model.get_current_image() is previous

    def test_grain_only_and_undo(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        previous = model.get_current_image()
        command = CombinedAdjustmentCommand(
            model, grain_params={"grain": 50.0}
        )
        command.execute()
        assert model.is_modified() is True
        command.undo()
        assert model.get_current_image() is previous

    def test_sharpening_only_and_undo(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        previous = model.get_current_image()
        command = CombinedAdjustmentCommand(
            model, sharpening_params={"sharpening": 50.0}
        )
        command.execute()
        assert model.is_modified() is True

    def test_luminance_nr_only_and_undo(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        previous = model.get_current_image()
        command = CombinedAdjustmentCommand(
            model, luminance_nr_params={"luminance_nr": 50.0}
        )
        command.execute()
        assert model.is_modified() is True
        command.undo()
        assert model.get_current_image() is previous

    def test_color_nr_only_and_undo(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        previous = model.get_current_image()
        command = CombinedAdjustmentCommand(
            model, color_nr_params={"color_nr": 50.0}
        )
        command.execute()
        assert model.is_modified() is True
        command.undo()
        assert model.get_current_image() is previous

    def test_remove_ca_only_and_undo(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        previous = model.get_current_image()
        command = CombinedAdjustmentCommand(
            model, remove_ca_params={"remove_ca": 50.0}
        )
        command.execute()
        assert model.is_modified() is True
        command.undo()
        assert model.get_current_image() is previous

    def test_defringe_only_and_undo(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        previous = model.get_current_image()
        command = CombinedAdjustmentCommand(
            model, defringe_params={"defringe": 50.0}
        )
        command.execute()
        assert model.is_modified() is True
        command.undo()
        assert model.get_current_image() is previous

    def test_straighten_only_and_undo(self, sample_linear_image):
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        previous = model.get_current_image()
        command = CombinedAdjustmentCommand(
            model, straighten_params={"straighten": 10.0}
        )
        command.execute()
        assert model.is_modified() is True
        new_image = model.get_current_image()
        assert new_image.shape == sample_linear_image.shape
        command.undo()
        assert model.get_current_image() is previous

    def test_crop_only_and_undo(self, sample_linear_image):
        """Crop is the one processor that deliberately changes shape --
        confirm the combined command's synchronous fallback applies it
        correctly and undo restores the uncropped image."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        previous = model.get_current_image()
        command = CombinedAdjustmentCommand(
            model, crop_params={"x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.75}
        )
        command.execute()
        assert model.is_modified() is True
        new_image = model.get_current_image()
        assert new_image.shape != sample_linear_image.shape
        assert new_image.shape[0] < sample_linear_image.shape[0]
        assert new_image.shape[1] < sample_linear_image.shape[1]
        command.undo()
        assert model.get_current_image() is previous

    def test_crop_applied_after_straighten(self, sample_linear_image):
        """Crop must be the absolute last step, after Straighten -- see
        docs/planning/implementation-notes/2026-10-13-crop-processor.md
        section 1."""
        model = ImageModel()
        model.set_original_image(sample_linear_image)
        command = CombinedAdjustmentCommand(
            model,
            straighten_params={"straighten": 10.0},
            crop_params={"x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.75},
        )
        command.execute()
        new_image = model.get_current_image()
        # If crop ran before straighten, straighten's warpAffine (which
        # locks output to its own input's exact dimensions) would have
        # re-grown the shape back to the original, uncropped size.
        assert new_image.shape[0] < sample_linear_image.shape[0]
        assert new_image.shape[1] < sample_linear_image.shape[1]


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
