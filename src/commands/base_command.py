"""Base command class for the command pattern."""

from abc import ABC, abstractmethod
from typing import Optional


class BaseCommand(ABC):
    """Abstract base class for all commands.
    
    This implements the command pattern, enabling undo/redo functionality.
    Each command encapsulates an operation that can be executed and undone.
    """

    def __init__(self):
        """Initialize the command."""
        self._executed = False

    @abstractmethod
    def execute(self) -> None:
        """Execute the command.
        
        Raises:
            RuntimeError: If command has already been executed
        """
        if self._executed:
            raise RuntimeError("Command has already been executed")
        self._executed = True

    @abstractmethod
    def undo(self) -> None:
        """Undo the command.
        
        Raises:
            RuntimeError: If command has not been executed yet
        """
        if not self._executed:
            raise RuntimeError("Command has not been executed yet")
        self._executed = False

    def redo(self) -> None:
        """Redo the command (same as execute).
        
        This is a convenience method that calls execute().
        """
        self.execute()

    def can_undo(self) -> bool:
        """Check if the command can be undone.
        
        Returns:
            True if command has been executed and can be undone
        """
        return self._executed

    def is_executed(self) -> bool:
        """Check if the command has been executed.
        
        Returns:
            True if command has been executed
        """
        return self._executed
