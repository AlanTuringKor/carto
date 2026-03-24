"""
PageUnderstandingAgent — interprets raw PageObservation into ActionInventory.

This agent is responsible for:
- Summarising the page purpose and cluster (e.g. "login", "dashboard")
- Extracting all interactive elements as DiscoveredActions
- Parsing forms into DiscoveredFields
- Detecting authentication patterns (login forms, CSRF tokens, session cookies)
- Flagging patterns that may be security-relevant

The LLM receives the page's accessible text, title, URL, and a compact
representation of the DOM elements, then returns a structured ActionInventory.
"""

from __future__ import annotations

import structlog

from carto.agents.base import AgentError, BaseAgent
from carto.agents.prompts.page_understanding import build_page_understanding_prompt
from carto.contracts.envelope import MessageEnvelope
from carto.domain.inferences import ActionInventory
from carto.domain.observations import PageObservation
from carto.llm.client import LLMClient, LLMError

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Response schema — a subset of ActionInventory fields the LLM fills in.
# We parse into this, then construct the full ActionInventory with metadata.
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field
from carto.domain.inferences import DiscoveredAction, DiscoveredField


class ActionInventoryResponse(BaseModel):
    """LLM response schema for page understanding."""

    page_title: str | None = None
    page_summary: str | None = None
    page_cluster: str | None = None
    auth_required: bool = False
    is_login_page: bool = False
    is_logout_page: bool = False
    has_auth_forms: bool = False
    csrf_hints: list[str] = Field(default_factory=list)
    auth_mechanisms_detected: list[str] = Field(default_factory=list)
    login_form_selector: str | None = None
    username_field_selector: str | None = None
    password_field_selector: str | None = None
    discovered_actions: list[DiscoveredAction] = Field(default_factory=list)
    discovered_forms: list[list[DiscoveredField]] = Field(default_factory=list)
    navigation_links: list[str] = Field(default_factory=list)
    api_endpoints_observed: list[str] = Field(default_factory=list)
    interesting_patterns: list[str] = Field(default_factory=list)


class PageUnderstandingAgent(BaseAgent[PageObservation, ActionInventory]):
    """
    Converts a PageObservation into an ActionInventory via LLM reasoning.

    Construction
    ------------
    llm_client:
        An ``LLMClient`` implementation (e.g. ``OpenAIClient``).
    model_name:
        Model identifier for audit trails.
    debug:
        If True, store raw prompt/response on the inference for debugging.
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

        prompt = build_page_understanding_prompt(observation)

        try:
            response = self._llm.complete(prompt, ActionInventoryResponse)
        except LLMError as exc:
            raise AgentError(self.agent_name, str(exc)) from exc

        # Build the full ActionInventory from the LLM response + observation metadata
        inventory = ActionInventory(
            run_id=observation.run_id,
            source_observation_id=observation.observation_id,
            agent_name=self.agent_name,
            model_name=self._model_name,
            page_title=response.page_title,
            page_summary=response.page_summary,
            page_cluster=response.page_cluster,
            auth_required=response.auth_required,
            is_login_page=response.is_login_page,
            is_logout_page=response.is_logout_page,
            has_auth_forms=response.has_auth_forms,
            csrf_hints=response.csrf_hints,
            auth_mechanisms_detected=response.auth_mechanisms_detected,
            login_form_selector=response.login_form_selector,
            username_field_selector=response.username_field_selector,
            password_field_selector=response.password_field_selector,
            discovered_actions=response.discovered_actions,
            discovered_forms=response.discovered_forms,
            navigation_links=response.navigation_links,
            api_endpoints_observed=response.api_endpoints_observed,
            interesting_patterns=response.interesting_patterns,
            raw_prompt=prompt if self._debug else None,
            raw_response=response.model_dump_json() if self._debug else None,
        )

        logger.info(
            "page_understanding.complete",
            run_id=observation.run_id,
            actions=len(inventory.discovered_actions),
            forms=len(inventory.discovered_forms),
            is_login=inventory.is_login_page,
            cluster=inventory.page_cluster,
        )

        return MessageEnvelope[ActionInventory](
            source=self.agent_name,
            target="action_planner_agent",
            correlation_id=envelope.correlation_id,
            payload=inventory,
        )
