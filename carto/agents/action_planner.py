"""
ActionPlannerAgent — decides which action to perform next.

Given an ActionInventory and the current State, this agent decides:
- Which DiscoveredAction to execute next
- Why (rationale)
- Whether the run should stop

Decision strategy (Phase 2 implementation):
- Prefer unexplored areas over revisiting known pages
- Prefer high-priority actions (as scored by PageUnderstandingAgent)
- Avoid cycles (actions that lead to already-visited stable states)
- Respect role context (only attempt actions plausible for the role)
- Stop when coverage gain drops below a threshold or a stop condition is met

Phase 1: Interface is defined; LLM integration is a Phase 2 work item.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from carto.agents.base import AgentError, BaseAgent
from carto.contracts.envelope import MessageEnvelope
from carto.domain.inferences import ActionInventory, NextActionDecision
from carto.domain.models import State

logger = structlog.get_logger(__name__)


@dataclass
class PlannerInput:
    """
    Combined input payload for the ActionPlannerAgent.

    Wraps both the ActionInventory and the current State so they can be
    passed together in a single MessageEnvelope.
    """

    inventory: ActionInventory
    state: State

    # Pydantic envelope requires a BaseModel payload; adapt at call site.
    # Phase 2: convert this to a proper Pydantic model if envelope wrapping
    # becomes necessary at the planner boundary.


class ActionPlannerAgent(BaseAgent[ActionInventory, NextActionDecision]):
    """
    Selects the next action to execute based on ActionInventory + State.

    Construction
    ------------
    llm_client:
        Any object with a ``complete(prompt: str) -> str`` interface.

    TODO (Phase 2):
        - Build a prompt that includes: current URL, discovered actions,
          visited pages, active role, and exploration coverage.
        - Parse the JSON response into NextActionDecision.
        - Implement cycle detection to avoid infinite loops.
        - Add a configurable stop condition (max steps, coverage threshold).
    """

    def __init__(self, llm_client: object, model_name: str = "gpt-4o") -> None:
        self._llm = llm_client
        self._model_name = model_name

    @property
    def agent_name(self) -> str:
        return "action_planner_agent"

    def run(
        self,
        envelope: MessageEnvelope[ActionInventory],
    ) -> MessageEnvelope[NextActionDecision]:
        inventory = envelope.payload
        logger.info(
            "action_planner.start",
            run_id=inventory.run_id,
            action_count=len(inventory.discovered_actions),
        )

        # ------------------------------------------------------------------
        # TODO (Phase 2): Build the LLM prompt, call self._llm.complete(),
        # parse the JSON response, and populate NextActionDecision fields.
        # ------------------------------------------------------------------
        raise AgentError(
            self.agent_name,
            "LLM integration not implemented yet — Phase 2 work item.",
        )
