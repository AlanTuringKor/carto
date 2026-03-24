"""
StateDiffAgent — compares two State snapshots to detect meaningful changes.

Responsibilities:
- Detect new pages that appeared after an action
- Detect auth state transitions (login success, logout)
- Detect cookie and storage changes
- Detect session refresh events
- Flag security-relevant state transitions
- Summarise delta in a structured StateDelta
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from carto.agents.base import AgentError, BaseAgent
from carto.agents.prompts.state_diff import build_state_diff_prompt
from carto.contracts.envelope import MessageEnvelope
from carto.domain.inferences import StateDelta, StateDiffInput
from carto.llm.client import LLMClient, LLMError

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Response schema for the LLM
# ---------------------------------------------------------------------------


class StateDiffResponse(BaseModel):
    """LLM response schema for state diffing."""

    url_changed: bool = False
    auth_state_changed: bool = False
    login_detected: bool = False
    logout_detected: bool = False
    session_refresh_detected: bool = False
    cookies_added: list[str] = Field(default_factory=list)
    cookies_removed: list[str] = Field(default_factory=list)
    cookies_modified: list[str] = Field(default_factory=list)
    storage_keys_added: list[str] = Field(default_factory=list)
    storage_keys_removed: list[str] = Field(default_factory=list)
    role_changed: bool = False
    security_observations: list[str] = Field(default_factory=list)
    summary: str | None = None


class StateDiffAgent(BaseAgent[StateDiffInput, StateDelta]):
    """
    Compares two State snapshots and produces a StateDelta via LLM reasoning.

    Construction
    ------------
    llm_client:
        An ``LLMClient`` implementation.
    model_name:
        Model identifier for audit trails.
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

    @property
    def agent_name(self) -> str:
        return "state_diff_agent"

    def run(
        self,
        envelope: MessageEnvelope[StateDiffInput],
    ) -> MessageEnvelope[StateDelta]:
        input_data = envelope.payload

        logger.info(
            "state_diff.start",
            before_url=input_data.page_url_before,
            after_url=input_data.page_url_after,
        )

        prompt = build_state_diff_prompt(input_data)

        try:
            response = self._llm.complete(prompt, StateDiffResponse)
        except LLMError as exc:
            raise AgentError(self.agent_name, str(exc)) from exc

        delta = StateDelta(
            run_id=input_data.before.run_id,
            source_observation_id="state_diff_input",
            agent_name=self.agent_name,
            model_name=self._model_name,
            before_state_id=input_data.before.state_id,
            after_state_id=input_data.after.state_id,
            url_changed=response.url_changed,
            auth_state_changed=response.auth_state_changed,
            login_detected=response.login_detected,
            logout_detected=response.logout_detected,
            session_refresh_detected=response.session_refresh_detected,
            cookies_added=response.cookies_added,
            cookies_removed=response.cookies_removed,
            cookies_modified=response.cookies_modified,
            storage_keys_added=response.storage_keys_added,
            storage_keys_removed=response.storage_keys_removed,
            role_changed=response.role_changed,
            security_observations=response.security_observations,
            summary=response.summary,
            raw_prompt=prompt if self._debug else None,
            raw_response=response.model_dump_json() if self._debug else None,
        )

        logger.info(
            "state_diff.complete",
            auth_changed=delta.auth_state_changed,
            login=delta.login_detected,
            logout=delta.logout_detected,
        )

        return MessageEnvelope[StateDelta](
            source=self.agent_name,
            target="orchestrator",
            correlation_id=envelope.correlation_id,
            payload=delta,
        )
