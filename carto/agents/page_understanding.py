"""
PageUnderstandingAgent — interprets raw PageObservation into ActionInventory.

This agent is responsible for:
- Summarising the page purpose and cluster (e.g. "login", "dashboard")
- Extracting all interactive elements as DiscoveredActions
- Parsing forms into DiscoveredFields
- Flagging patterns that may be security-relevant

The LLM is expected to receive the page's accessible text, title, URL,
and a compact representation of the DOM elements, then return a structured
ActionInventory.

Phase 1: The prompt is a placeholder.  Wire the real LLM client in Phase 2.
"""

from __future__ import annotations

import structlog

from carto.agents.base import AgentError, BaseAgent
from carto.contracts.envelope import MessageEnvelope
from carto.domain.inferences import ActionInventory
from carto.domain.observations import PageObservation

logger = structlog.get_logger(__name__)


class PageUnderstandingAgent(BaseAgent[PageObservation, ActionInventory]):
    """
    Converts a PageObservation into an ActionInventory.

    Construction
    ------------
    llm_client:
        Any object with a ``complete(prompt: str) -> str`` interface.
        Injected to keep the agent independent of provider details.

    TODO (Phase 2):
        - Implement the LLM prompt with page title, URL, accessible text,
          and serialised interactive elements.
        - Parse LLM JSON response into ActionInventory.
        - Add structured logging of raw_prompt / raw_response when debug
          mode is enabled.
    """

    def __init__(self, llm_client: object, model_name: str = "gpt-4o") -> None:
        self._llm = llm_client
        self._model_name = model_name

    @property
    def agent_name(self) -> str:
        return "page_understanding_agent"

    def run(
        self,
        envelope: MessageEnvelope[PageObservation],
    ) -> MessageEnvelope[ActionInventory]:
        observation = envelope.payload
        logger.info(
            "page_understanding.start",
            run_id=observation.run_id,
            url=observation.url,
            element_count=len(observation.interactive_elements),
        )

        # ------------------------------------------------------------------
        # TODO (Phase 2): Build the LLM prompt, call self._llm.complete(),
        # parse the JSON response, and populate ActionInventory fields.
        # ------------------------------------------------------------------
        raise AgentError(
            self.agent_name,
            "LLM integration not implemented yet — Phase 2 work item.",
        )
