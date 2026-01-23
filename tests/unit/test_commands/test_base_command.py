"""Unit tests for BaseCommand."""

import pytest
from src.commands.base_command import BaseCommand


class ConcreteCommand(BaseCommand):
    """Concrete implementation of BaseCommand for testing."""
    
    def __init__(self):
        super().__init__()
        self.executed = False
        self.undone = False
    
    def execute(self):
        super().execute()
        self.executed = True
    
    def undo(self):
        super().undo()
        self.undone = True


class TestBaseCommand:
    """Test cases for BaseCommand class."""

    def test_command_initialization(self):
        """Test command can be initialized."""
        cmd = ConcreteCommand()
        assert cmd is not None
        assert cmd.is_executed() is False
        assert cmd.can_undo() is False

    def test_execute_command(self):
        """Test executing a command."""
        cmd = ConcreteCommand()
        cmd.execute()
        assert cmd.is_executed() is True
        assert cmd.executed is True
        assert cmd.can_undo() is True

    def test_execute_twice_raises_error(self):
        """Test that executing a command twice raises error."""
        cmd = ConcreteCommand()
        cmd.execute()
        with pytest.raises(RuntimeError, match="already been executed"):
            cmd.execute()

    def test_undo_command(self):
        """Test undoing a command."""
        cmd = ConcreteCommand()
        cmd.execute()
        cmd.undo()
        assert cmd.is_executed() is False
        assert cmd.undone is True

    def test_undo_without_execute_raises_error(self):
        """Test that undoing without executing raises error."""
        cmd = ConcreteCommand()
        with pytest.raises(RuntimeError, match="not been executed"):
            cmd.undo()

    def test_redo_command(self):
        """Test redoing a command."""
        cmd = ConcreteCommand()
        cmd.execute()
        cmd.undo()
        cmd.redo()
        assert cmd.is_executed() is True
        assert cmd.executed is True

    def test_can_undo(self):
        """Test can_undo method."""
        cmd = ConcreteCommand()
        assert cmd.can_undo() is False
        
        cmd.execute()
        assert cmd.can_undo() is True
        
        cmd.undo()
        assert cmd.can_undo() is False
