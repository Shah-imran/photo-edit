"""Unit tests for HistoryService."""

import pytest
from src.services.history_service import HistoryService
from src.commands.base_command import BaseCommand


class MockCommand(BaseCommand):
    """Mock command for testing."""
    
    def __init__(self):
        super().__init__()
        self.execute_count = 0
        self.undo_count = 0
    
    def execute(self):
        super().execute()
        self.execute_count += 1
    
    def undo(self):
        super().undo()
        self.undo_count += 1


class TestHistoryService:
    """Test cases for HistoryService class."""

    def test_history_service_initialization(self):
        """Test HistoryService can be initialized."""
        service = HistoryService()
        assert service is not None
        assert service.can_undo() is False
        assert service.can_redo() is False

    def test_execute_command(self):
        """Test executing a command."""
        service = HistoryService()
        command = MockCommand()
        
        service.execute_command(command)
        assert service.can_undo() is True
        assert command.execute_count == 1

    def test_undo_command(self):
        """Test undoing a command."""
        service = HistoryService()
        command = MockCommand()
        
        service.execute_command(command)
        result = service.undo()
        
        assert result is True
        assert command.undo_count == 1
        assert service.can_redo() is True

    def test_redo_command(self):
        """Test redoing a command."""
        service = HistoryService()
        command = MockCommand()
        
        service.execute_command(command)
        service.undo()
        result = service.redo()
        
        assert result is True
        assert command.execute_count == 2  # Once for execute, once for redo

    def test_undo_when_empty(self):
        """Test undoing when no commands."""
        service = HistoryService()
        result = service.undo()
        assert result is False

    def test_redo_when_empty(self):
        """Test redoing when no commands."""
        service = HistoryService()
        result = service.redo()
        assert result is False

    def test_multiple_undo_redo(self):
        """Test multiple undo and redo operations."""
        service = HistoryService()
        cmd1 = MockCommand()
        cmd2 = MockCommand()
        
        service.execute_command(cmd1)
        service.execute_command(cmd2)
        
        # Undo twice
        service.undo()
        service.undo()
        
        assert cmd2.undo_count == 1
        assert cmd1.undo_count == 1
        
        # Redo twice
        service.redo()
        service.redo()
        
        assert cmd1.execute_count == 2
        assert cmd2.execute_count == 2

    def test_clear_redo_on_new_command(self):
        """Test that redo stack is cleared when new command is executed."""
        service = HistoryService()
        cmd1 = MockCommand()
        cmd2 = MockCommand()
        
        service.execute_command(cmd1)
        service.undo()
        assert service.can_redo() is True
        
        service.execute_command(cmd2)
        assert service.can_redo() is False

    def test_history_size_limit(self):
        """Test that history size is limited."""
        service = HistoryService(max_history_size=3)
        
        for i in range(5):
            cmd = MockCommand()
            service.execute_command(cmd)
        
        assert service.get_history_count() == 3

    def test_clear_history(self):
        """Test clearing all history."""
        service = HistoryService()
        cmd1 = MockCommand()
        cmd2 = MockCommand()
        
        service.execute_command(cmd1)
        service.execute_command(cmd2)
        service.undo()
        
        service.clear_history()
        
        assert service.can_undo() is False
        assert service.can_redo() is False
        assert service.get_history_count() == 0
        assert service.get_redo_count() == 0

    def test_get_history_count(self):
        """Test getting history count."""
        service = HistoryService()
        assert service.get_history_count() == 0
        
        service.execute_command(MockCommand())
        assert service.get_history_count() == 1
        
        service.execute_command(MockCommand())
        assert service.get_history_count() == 2

    def test_get_redo_count(self):
        """Test getting redo count."""
        service = HistoryService()
        assert service.get_redo_count() == 0
        
        service.execute_command(MockCommand())
        service.undo()
        assert service.get_redo_count() == 1
