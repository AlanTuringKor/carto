"""
DiffNarrativeAgent — LLM-enhanced role diff interpretation.

Consumes deterministic ``RoleDiffResult`` data and produces a
``DiffNarrative`` with evidence-backed insights.  This is an
additive layer — the deterministic diff remains the source of truth.

The agent is clearly marked as producing interpretive analysis,
never confirmed vulnerability findings.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from carto.agents.base import AgentError, BaseAgent
from carto.agents.prompts.diff_narrative import build_diff_narrative_prompt
from carto.contracts.envelope import MessageEnvelope
from carto.domain.diff_narrative import (
    DiffNarrative,
    InsightSeverity,
    ReportInsight,
)
from carto.domain.role_diff import RoleDiffResult
from carto.domain.role_surface import RoleSurface
from carto.llm.client import LLMClient, LLMError


# ---------------------------------------------------------------------------
# LLM response schema
# ---------------------------------------------------------------------------


class _InsightSchema(BaseModel):
    title: str = ""
    body: str = ""
    severity: str = "info"
    confidence: float = 0.5
    evidence_refs: list[str] = Field(default_factory=list)


class _NarrativeSchema(BaseModel):
    executive_summary: str = ""
    insights: list[_InsightSchema] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent input
# ---------------------------------------------------------------------------


class DiffNarrativeInput(BaseModel):
    """Input for the DiffNarrativeAgent."""

    diff: RoleDiffResult
    surface_a: RoleSurface
    surface_b: RoleSurface


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class DiffNarrativeAgent(BaseAgent):
    """
    LLM-backed agent that produces interpretive narrative
    from deterministic role diffs.
    """

    def __init__(
        self,
        llm: LLMClient,
        debug: bool = False,
    ) -> None:
        self._llm = llm
        self._debug = debug
        self._last_prompt: str | None = None

    @property
    def agent_name(self) -> str:
        return "diff_narrative_agent"

    def run(self, envelope: MessageEnvelope[DiffNarrativeInput]) -> MessageEnvelope[DiffNarrative]:
        """Produce a DiffNarrative from a RoleDiffResult."""
        input_data = envelope.payload
        diff = input_data.diff
        surface_a = input_data.surface_a
        surface_b = input_data.surface_b

        # Build prompt
        prompt = build_diff_narrative_prompt(diff, surface_a, surface_b)
        if self._debug:
            self._last_prompt = prompt

        # Call LLM
        try:
            response = self._llm.complete(prompt, _NarrativeSchema)
        except LLMError as exc:
            raise AgentError("diff_narrative_agent", f"LLM error: {exc}") from exc

        if not hasattr(response, "executive_summary") or not hasattr(response, "insights"):
            raise AgentError("diff_narrative_agent", f"Unexpected LLM response type: {type(response)}")

        # Map to DiffNarrative
        insights: list[ReportInsight] = []
        for raw in response.insights:
            severity = _parse_severity(raw.severity)
            insights.append(ReportInsight(
                title=raw.title,
                body=raw.body,
                severity=severity,
                confidence=max(0.0, min(1.0, raw.confidence)),
                evidence_refs=raw.evidence_refs,
            ))

        narrative = DiffNarrative(
            role_a_name=diff.role_a_name,
            role_b_name=diff.role_b_name,
            executive_summary=response.executive_summary,
            insights=insights,
            agent_name="diff_narrative_agent",
            model_name=getattr(self._llm, "model", "unknown"),
        )

        return MessageEnvelope(
            payload=narrative,
            source="diff_narrative_agent",
            target="orchestrator",
            correlation_id=envelope.correlation_id,
        )


def _parse_severity(raw: str) -> InsightSeverity:
    """Parse severity string, defaulting to INFO for unrecognised values."""
    try:
        return InsightSeverity(raw.lower())
    except ValueError:
        return InsightSeverity.INFO
