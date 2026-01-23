"""History service for managing undo/redo operations."""

from typing import List, Optional
from src.commands.base_command import BaseCommand


class HistoryService:
    """Service for managing command history and undo/redo operations.
    
    This service maintains a stack of commands and provides undo/redo
    functionality for the application.
    """

    def __init__(self, max_history_size: int = 50):
        """Initialize HistoryService.
        
        Args:
            max_history_size: Maximum number of commands to keep in history
        """
        self._undo_stack: List[BaseCommand] = []
        self._redo_stack: List[BaseCommand] = []
        self._max_history_size = max_history_size

    def execute_command(self, command: BaseCommand) -> None:
        """Execute a command and add it to the history.
        
        Args:
            command: Command to execute
        """
        # Clear redo stack when new command is executed
        self._redo_stack.clear()
        
        # Execute the command
        command.execute()
        
        # Add to undo stack
        self._undo_stack.append(command)
        
        # Limit history size
        if len(self._undo_stack) > self._max_history_size:
            self._undo_stack.pop(0)

    def undo(self) -> bool:
        """Undo the last command.
        
        Returns:
            True if undo was successful, False if nothing to undo
        """
        if not self.can_undo():
            return False
        
        command = self._undo_stack.pop()
        command.undo()
        self._redo_stack.append(command)
        return True

    def redo(self) -> bool:
        """Redo the last undone command.
        
        Returns:
            True if redo was successful, False if nothing to redo
        """
        if not self.can_redo():
            return False
        
        command = self._redo_stack.pop()
        command.redo()
        self._undo_stack.append(command)
        return True

    def can_undo(self) -> bool:
        """Check if undo is possible.
        
        Returns:
            True if there are commands to undo
        """
        return len(self._undo_stack) > 0

    def can_redo(self) -> bool:
        """Check if redo is possible.
        
        Returns:
            True if there are commands to redo
        """
        return len(self._redo_stack) > 0

    def clear_history(self) -> None:
        """Clear all command history."""
        self._undo_stack.clear()
        self._redo_stack.clear()

    def get_history_count(self) -> int:
        """Get the number of commands in undo history.
        
        Returns:
            Number of commands that can be undone
        """
        return len(self._undo_stack)

    def get_redo_count(self) -> int:
        """Get the number of commands in redo history.
        
        Returns:
            Number of commands that can be redone
        """
        return len(self._redo_stack)
