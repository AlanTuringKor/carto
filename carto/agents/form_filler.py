"""
FormFillerAgent — plans how to fill a form with contextually appropriate data.

Phase 2 work item.  This module defines the interface so the orchestrator
can reference the type and the agent can be wired in without structural
changes later.

Responsibilities (Phase 2):
- Understand the semantic meaning of each field (username, email, search, etc.)
- Generate appropriate test values based on the field semantics and role context
- Ensure at least one submission path per form is explored
- Optionally attempt boundary-value and injection payloads under a
  ``security_mode`` flag (Phase 3)
"""

from __future__ import annotations

from carto.agents.base import AgentError, BaseAgent
from carto.contracts.envelope import MessageEnvelope
from carto.domain.inferences import ActionInventory, FormFillPlan


class FormFillerAgent(BaseAgent[ActionInventory, FormFillPlan]):
    """
    Generates a FormFillPlan from an ActionInventory containing forms.

    TODO (Phase 2):
        - Accept a list of DiscoveredFields as input.
        - Generate FieldFillInstruction for each field based on semantic
          meaning and current RoleProfile.
        - Flag fields that may be injectable (Phase 3).
    """

    def __init__(self, llm_client: object, model_name: str = "gpt-4o") -> None:
        self._llm = llm_client
        self._model_name = model_name

    @property
    def agent_name(self) -> str:
        return "form_filler_agent"

    def run(
        self,
        envelope: MessageEnvelope[ActionInventory],
    ) -> MessageEnvelope[FormFillPlan]:
        raise AgentError(
            self.agent_name,
            "FormFillerAgent not implemented — Phase 2 work item.",
        )
