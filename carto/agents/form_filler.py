"""
FormFillerAgent — plans how to fill a form with contextually appropriate data.

Responsibilities:
- Understand the semantic meaning of each field (username, email, search, etc.)
- Generate appropriate test values based on field semantics and role context
- Recognise login forms and use provided credentials
- Preserve CSRF tokens (never overwrite hidden CSRF fields)
- Flag fields that contain authentication credentials
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from carto.agents.base import AgentError, BaseAgent
from carto.agents.prompts.form_filler import build_form_filler_prompt
from carto.contracts.envelope import MessageEnvelope
from carto.domain.inferences import (
    FieldFillInstruction,
    FormFillerInput,
    FormFillPlan,
)
from carto.llm.client import LLMClient, LLMError

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Response schema for the LLM
# ---------------------------------------------------------------------------


class FormFillResponse(BaseModel):
    """LLM response schema for form filling."""

    form_css_selector: str | None = None
    field_instructions: list[FieldFillInstruction] = Field(default_factory=list)
    should_submit: bool = True
    is_login_form: bool = False
    auth_field_selectors: list[str] = Field(default_factory=list)


class FormFillerAgent(BaseAgent[FormFillerInput, FormFillPlan]):
    """
    Generates a FormFillPlan from a FormFillerInput.

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
        return "form_filler_agent"

    def run(
        self,
        envelope: MessageEnvelope[FormFillerInput],
    ) -> MessageEnvelope[FormFillPlan]:
        input_data = envelope.payload

        logger.info(
            "form_filler.start",
            page_url=input_data.page_url,
            field_count=len(input_data.form_fields),
            is_login=input_data.is_login_form,
        )

        prompt = build_form_filler_prompt(input_data)

        try:
            response = self._llm.complete(prompt, FormFillResponse)
        except LLMError as exc:
            raise AgentError(self.agent_name, str(exc)) from exc

        plan = FormFillPlan(
            run_id=envelope.correlation_id,
            source_observation_id="form_fill_request",
            agent_name=self.agent_name,
            model_name=self._model_name,
            form_css_selector=response.form_css_selector or input_data.form_selector,
            field_instructions=response.field_instructions,
            should_submit=response.should_submit,
            is_login_form=response.is_login_form or input_data.is_login_form,
            auth_field_selectors=response.auth_field_selectors,
            raw_prompt=prompt if self._debug else None,
            raw_response=response.model_dump_json() if self._debug else None,
        )

        logger.info(
            "form_filler.complete",
            instructions=len(plan.field_instructions),
            is_login=plan.is_login_form,
            should_submit=plan.should_submit,
        )

        return MessageEnvelope[FormFillPlan](
            source=self.agent_name,
            target="orchestrator",
            correlation_id=envelope.correlation_id,
            payload=plan,
        )
