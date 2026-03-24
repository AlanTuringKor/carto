"""
BaseAgent — abstract interface for all LLM reasoning components.

Design constraints:
- Agents MUST NOT cause side effects (no browser calls, no disk writes).
- Agents MUST return a typed MessageEnvelope.
- Agents receive typed MessageEnvelopes as input.
- The LLM client is injected at construction time so it can be swapped
  for tests or alternative providers without touching agent logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel

from carto.contracts.envelope import MessageEnvelope

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class BaseAgent(ABC, Generic[InputT, OutputT]):
    """
    Generic abstract base class for all agents.

    Type parameters
    ---------------
    InputT:
        The Pydantic model carried in the input ``MessageEnvelope``.
    OutputT:
        The Pydantic model carried in the output ``MessageEnvelope``.

    Subclasses must implement ``run`` and ``agent_name``.

    Thread/async safety:
        ``run`` is defined as a regular method here because agents are
        expected to be called sequentially from the orchestrator loop.
        Phase 2 can convert to ``async def run`` if parallel agent
        execution becomes desirable.
    """

    @property
    @abstractmethod
    def agent_name(self) -> str:
        """Stable logical name used in envelope ``source`` fields."""
        ...

    @abstractmethod
    def run(
        self,
        envelope: MessageEnvelope[InputT],
    ) -> MessageEnvelope[OutputT]:
        """
        Process the input envelope and return an output envelope.

        The implementation MUST:
        - Read only from ``envelope.payload``.
        - Return a new ``MessageEnvelope`` with:
            - ``source`` = ``self.agent_name``
            - ``target`` = the intended recipient
            - ``correlation_id`` = ``envelope.correlation_id``
            - ``payload`` = typed OutputT instance
        - Not mutate any external state.
        - Not call the browser executor.

        Raises
        ------
        AgentError
            If the LLM call fails or the response cannot be parsed.
        """
        ...


class AgentError(Exception):
    """Raised when an agent cannot produce a valid output."""

    def __init__(self, agent_name: str, reason: str) -> None:
        self.agent_name = agent_name
        self.reason = reason
        super().__init__(f"[{agent_name}] {reason}")
