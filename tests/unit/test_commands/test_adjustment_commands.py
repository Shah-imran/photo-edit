"""Unit tests for adjustment commands."""

import pytest
from PIL import Image
from src.commands.adjustment_commands import AdjustmentCommand, CombinedAdjustmentCommand
from src.models.image_model import ImageModel


class TestAdjustmentCommand:
    """Test cases for AdjustmentCommand class."""

    def test_command_initialization(self, sample_image):
        """Test AdjustmentCommand can be initialized."""
        model = ImageModel()
        model.set_original_image(sample_image)
        
        cmd = AdjustmentCommand(
            model,
            adjustment_type='exposure',
            parameters={'exposure': 1.0}
        )
        assert cmd is not None

    def test_execute_exposure_adjustment(self, sample_image):
        """Test executing exposure adjustment."""
        model = ImageModel()
        model.set_original_image(sample_image)
        
        cmd = AdjustmentCommand(
            model,
            adjustment_type='exposure',
            parameters={'exposure': 1.0, 'contrast': 0.0, 'brightness': 0.0}
        )
        cmd.execute()
        
        assert cmd.is_executed() is True
        assert model.is_modified() is True

    def test_undo_adjustment(self, sample_image):
        """Test undoing adjustment."""
        model = ImageModel()
        model.set_original_image(sample_image)
        original_image = model.get_current_image()
        
        cmd = AdjustmentCommand(
            model,
            adjustment_type='exposure',
            parameters={'exposure': 1.0}
        )
        cmd.execute()
        cmd.undo()
        
        assert cmd.is_executed() is False

    def test_get_parameters(self, sample_image):
        """Test getting command parameters."""
        model = ImageModel()
        model.set_original_image(sample_image)
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

    def test_command_initialization(self, sample_image):
        """Test CombinedAdjustmentCommand can be initialized."""
        model = ImageModel()
        model.set_original_image(sample_image)
        
        cmd = CombinedAdjustmentCommand(model)
        assert cmd is not None

    def test_execute_combined_adjustments(self, sample_image):
        """Test executing combined adjustments."""
        model = ImageModel()
        model.set_original_image(sample_image)
        
        cmd = CombinedAdjustmentCommand(
            model,
            exposure_params={'exposure': 0.5, 'contrast': 10.0, 'brightness': 5.0},
            color_params={'saturation': 20.0, 'vibrance': 10.0}
        )
        cmd.execute()
        
        assert cmd.is_executed() is True
        assert model.is_modified() is True

    def test_undo_combined_adjustments(self, sample_image):
        """Test undoing combined adjustments."""
        model = ImageModel()
        model.set_original_image(sample_image)
        
        cmd = CombinedAdjustmentCommand(
            model,
            exposure_params={'exposure': 1.0},
            color_params={'saturation': 50.0}
        )
        cmd.execute()
        cmd.undo()
        
        assert cmd.is_executed() is False

    def test_exposure_only(self, sample_image):
        """Test with only exposure adjustments."""
        model = ImageModel()
        model.set_original_image(sample_image)
        
        cmd = CombinedAdjustmentCommand(
            model,
            exposure_params={'exposure': 2.0}
        )
        cmd.execute()
        
        assert cmd.is_executed() is True

    def test_color_only(self, sample_image):
        """Test with only color adjustments."""
        model = ImageModel()
        model.set_original_image(sample_image)
        
        cmd = CombinedAdjustmentCommand(
            model,
            color_params={'saturation': 50.0}
        )
        cmd.execute()
        
        assert cmd.is_executed() is True
