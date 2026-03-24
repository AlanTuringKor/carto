"""
StateDiffAgent — compares two State snapshots to detect meaningful changes.

Phase 2 work item.  This module defines the interface only.

Responsibilities (Phase 2):
- Detect new pages that appeared after an action
- Detect pages that disappeared (session expiry, role change)
- Detect auth state transitions (login success, logout)
- Detect role changes (e.g. privilege escalation indicators)
- Summarise delta in a structured StateDelta
"""

from __future__ import annotations

from carto.agents.base import AgentError, BaseAgent
from carto.contracts.envelope import MessageEnvelope
from carto.domain.inferences import ActionInventory, StateDelta


class StateDiffAgent(BaseAgent[ActionInventory, StateDelta]):
    """
    Compares two State snapshots and produces a StateDelta.

    Note: The current Input type is ActionInventory as a placeholder.
    Phase 2 will introduce a dedicated StateDiffInput model containing
    before/after State objects.

    TODO (Phase 2):
        - Define StateDiffInput(before: State, after: State).
        - Diff visited pages, auth_state, cookies, and role.
        - Flag unexpected state transitions as potential security signals.
    """

    def __init__(self, llm_client: object, model_name: str = "gpt-4o") -> None:
        self._llm = llm_client
        self._model_name = model_name

    @property
    def agent_name(self) -> str:
        return "state_diff_agent"

    def run(
        self,
        envelope: MessageEnvelope[ActionInventory],
    ) -> MessageEnvelope[StateDelta]:
        raise AgentError(
            self.agent_name,
            "StateDiffAgent not implemented — Phase 2 work item.",
        )
