"""
RiskAgent — identifies security-relevant patterns and risk signals.

This agent consumes evidence from PageUnderstanding, StateDiff, and
auth context to produce structured ``RiskSignal`` findings.  It:
- Identifies evidence-backed security hotspots
- Maps findings to CWE identifiers
- Assigns severity levels
- Prioritises exploration targets
- NEVER fabricates confirmed vulnerabilities

The agent is reasoning-only (no side effects) and calls the LLM
via the ``LLMClient`` protocol.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from carto.agents.base import AgentError, BaseAgent
from carto.agents.prompts.risk import build_risk_prompt
from carto.contracts.envelope import MessageEnvelope
from carto.domain.artifacts import RiskSeverity, RiskSignal
from carto.domain.risk_input import RiskAssessment, RiskInput
from carto.llm.client import LLMClient, LLMError

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# LLM response schema
# ---------------------------------------------------------------------------


class RiskSignalResponse(BaseModel):
    """A single risk signal from the LLM."""

    title: str
    description: str
    severity: str = "info"
    evidence: str | None = None
    cwe: str | None = None


class RiskAssessmentResponse(BaseModel):
    """LLM response schema for risk assessment."""

    signals: list[RiskSignalResponse] = Field(default_factory=list)
    summary: str | None = None
    highest_severity: str = "info"


# ---------------------------------------------------------------------------
# RiskAgent
# ---------------------------------------------------------------------------


class RiskAgent(BaseAgent[RiskInput, RiskAssessment]):
    """
    Analyses evidence to identify security-relevant patterns.

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
        return "risk_agent"

    def run(
        self,
        envelope: MessageEnvelope[RiskInput],
    ) -> MessageEnvelope[RiskAssessment]:
        input_data = envelope.payload

        logger.info(
            "risk_agent.start",
            page_url=input_data.page_url,
            action_count=len(input_data.inventory.discovered_actions),
        )

        prompt = build_risk_prompt(input_data)

        try:
            response = self._llm.complete(prompt, RiskAssessmentResponse)
        except LLMError as exc:
            raise AgentError(self.agent_name, str(exc)) from exc

        # Convert response signals to domain RiskSignal objects
        signals: list[RiskSignal] = []
        for sig in response.signals:
            try:
                severity = RiskSeverity(sig.severity.lower())
            except ValueError:
                severity = RiskSeverity.INFO

            signals.append(
                RiskSignal(
                    run_id=input_data.inventory.run_id,
                    page_id=None,
                    action_id=None,
                    inference_id=input_data.inventory.inference_id,
                    severity=severity,
                    title=sig.title,
                    description=sig.description,
                    evidence=sig.evidence,
                    cwe=sig.cwe,
                )
            )

        # Determine highest severity
        try:
            highest = RiskSeverity(response.highest_severity.lower())
        except ValueError:
            highest = RiskSeverity.INFO

        assessment = RiskAssessment(
            run_id=input_data.inventory.run_id,
            source_observation_id=input_data.inventory.source_observation_id,
            agent_name=self.agent_name,
            model_name=self._model_name,
            signals=signals,
            summary=response.summary,
            highest_severity=highest,
            raw_prompt=prompt if self._debug else None,
            raw_response=response.model_dump_json() if self._debug else None,
        )

        logger.info(
            "risk_agent.complete",
            signal_count=len(signals),
            highest_severity=str(highest),
        )

        return MessageEnvelope[RiskAssessment](
            source=self.agent_name,
            target="orchestrator",
            correlation_id=envelope.correlation_id,
            payload=assessment,
        )
