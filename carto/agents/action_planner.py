"""
ActionPlannerAgent — decides which action to perform next.

Given an ActionInventory and the current State, this agent decides:
- Which DiscoveredAction to execute next
- Why (rationale)
- Whether the run should stop

Decision strategy:
- Prefer unexplored areas over revisiting known pages
- Prefer high-priority actions (as scored by PageUnderstandingAgent)
- If on a login page and not authenticated, prioritise login
- Avoid cycles (actions that lead to already-visited stable states)
- Stop when coverage gain drops below a threshold or all paths explored
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from carto.agents.base import AgentError, BaseAgent
from carto.agents.prompts.action_planner import build_action_planner_prompt
from carto.contracts.envelope import MessageEnvelope
from carto.domain.inferences import ActionInventory, NextActionDecision
from carto.domain.models import ActionKind, State
from carto.llm.client import LLMClient, LLMError

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Response schema for the LLM
# ---------------------------------------------------------------------------


class NextActionResponse(BaseModel):
    """LLM response schema for action planning."""

    chosen_action_kind: str  # parsed to ActionKind
    chosen_css_selector: str | None = None
    chosen_href: str | None = None
    chosen_label: str | None = None
    fill_value: str | None = None
    rationale: str = ""
    expected_outcome: str | None = None
    estimated_coverage_gain: float | None = None
    should_stop: bool = False
    stop_reason: str | None = None


class ActionPlannerAgent(BaseAgent[ActionInventory, NextActionDecision]):
    """
    Selects the next action to execute based on ActionInventory + State.

    Construction
    ------------
    llm_client:
        An ``LLMClient`` implementation.
    model_name:
        Model identifier for audit trails.
    state:
        Current exploration state. Updated by the orchestrator before each call.
    debug:
        If True, store raw prompt/response on the inference.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        model_name: str | None = None,
        debug: bool = False,
    ) -> None:
        self._llm = llm_client
        self._model_name = model_name or llm_client.model_name
        self._debug = debug
        self._state: State | None = None

    @property
    def agent_name(self) -> str:
        return "action_planner_agent"

    def set_state(self, state: State) -> None:
        """Update the current exploration state (called by orchestrator)."""
        self._state = state

    def run(
        self,
        envelope: MessageEnvelope[ActionInventory],
        skip_login_fill: bool = False,
    ) -> MessageEnvelope[NextActionDecision]:
        inventory = envelope.payload

        # Use the injected state, or build a minimal fallback
        state = self._state or State(
            run_id=inventory.run_id,
            current_url="",
        )

        logger.info(
            "action_planner.start",
            run_id=inventory.run_id,
            action_count=len(inventory.discovered_actions),
            url=state.current_url,
        )

        prompt = build_action_planner_prompt(inventory, state, skip_login_fill=skip_login_fill)

        try:
            response = self._llm.complete(prompt, NextActionResponse)
        except LLMError as exc:
            raise AgentError(self.agent_name, str(exc)) from exc

        # Parse action kind from string to enum
        try:
            action_kind = ActionKind(response.chosen_action_kind)
        except ValueError:
            action_kind = ActionKind.UNKNOWN

        decision = NextActionDecision(
            run_id=inventory.run_id,
            source_observation_id=inventory.source_observation_id,
            agent_name=self.agent_name,
            model_name=self._model_name,
            chosen_action_kind=action_kind,
            chosen_css_selector=response.chosen_css_selector,
            chosen_href=response.chosen_href,
            chosen_label=response.chosen_label,
            fill_value=response.fill_value,
            rationale=response.rationale,
            expected_outcome=response.expected_outcome,
            estimated_coverage_gain=response.estimated_coverage_gain,
            should_stop=response.should_stop,
            stop_reason=response.stop_reason,
            raw_prompt=prompt if self._debug else None,
            raw_response=response.model_dump_json() if self._debug else None,
        )

        logger.info(
            "action_planner.complete",
            run_id=inventory.run_id,
            chosen_kind=decision.chosen_action_kind,
            should_stop=decision.should_stop,
        )

        return MessageEnvelope[NextActionDecision](
            source=self.agent_name,
            target="orchestrator",
            correlation_id=envelope.correlation_id,
            payload=decision,
        )
