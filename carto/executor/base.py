"""
BaseExecutor — abstract interface for all executor implementations.

Only the executor is allowed to cause side effects.
All orchestrator interactions with the outside world go through here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from carto.contracts.commands import (
    Command,
)
from carto.domain.observations import Observation


class BaseExecutor(ABC):
    """
    Abstract base for executor implementations.

    The executor is the *only* component in the system allowed to:
    - Control a browser
    - Make network requests
    - Write files to disk

    All other components (agents, orchestrator) are pure functions of
    their inputs.

    Subclasses must implement ``execute`` and may override individual
    ``_handle_*`` methods to keep dispatch logic readable.
    """

    @abstractmethod
    async def start(self) -> None:
        """Initialise the executor (e.g. launch browser)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Clean up resources (e.g. close browser)."""
        ...

    @abstractmethod
    async def execute(self, command: Command) -> Observation:
        """
        Execute a single command and return the resulting observation.

        Parameters
        ----------
        command:
            A typed Command instance.  The executor dispatches on
            ``command.kind`` and returns an appropriate Observation.

        Returns
        -------
        Observation
            Typically a ``PageObservation`` for navigation/interaction
            commands or an ``ErrorObservation`` if the action failed.

        Raises
        ------
        ExecutorError
            For unrecoverable errors that should propagate to the
            orchestrator (e.g. browser crash, page not found).
        """
        ...

    async def __aenter__(self) -> BaseExecutor:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()


class ExecutorError(Exception):
    """Raised for unrecoverable executor-level errors."""

    def __init__(self, command_id: str, reason: str) -> None:
        self.command_id = command_id
        self.reason = reason
        super().__init__(f"[command={command_id}] {reason}")
