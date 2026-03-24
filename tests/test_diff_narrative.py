"""Tests for DiffNarrativeAgent."""

from pydantic import BaseModel, Field

from carto.agents.diff_narrative import DiffNarrativeAgent, DiffNarrativeInput
from carto.contracts.envelope import MessageEnvelope
from carto.domain.diff_narrative import InsightSeverity
from carto.domain.models import AuthState
from carto.domain.role_diff import (
    DiffEntry,
    RoleDiffResult,
    RoleSurfaceDelta,
    VisibilityCategory,
)
from carto.domain.role_surface import RoleSurface
from carto.llm.client import LLMError


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------


class _MockLLM:
    def __init__(self, response=None, error: str | None = None):
        self._response = response
        self._error = error
        self.model = "mock-model"

    def complete(self, prompt: str, schema: type) -> object:
        if self._error:
            raise LLMError("mock-model", self._error)
        return self._response


class _InsightItem(BaseModel):
    title: str = ""
    body: str = ""
    severity: str = "info"
    confidence: float = 0.5
    evidence_refs: list[str] = Field(default_factory=list)


class _NarrativeResponse(BaseModel):
    executive_summary: str = ""
    insights: list[_InsightItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_input() -> DiffNarrativeInput:
    surface_a = RoleSurface(
        role_name="admin", run_id="r1",
        urls={"https://example.com", "https://example.com/admin"},
        auth_state=AuthState.AUTHENTICATED,
    )
    surface_b = RoleSurface(
        role_name="viewer", run_id="r2",
        urls={"https://example.com"},
        auth_state=AuthState.AUTHENTICATED,
    )
    diff = RoleDiffResult(
        campaign_id="c1",
        role_a_name="admin",
        role_b_name="viewer",
        delta=RoleSurfaceDelta(
            url_diff=[
                DiffEntry(item="https://example.com", category=VisibilityCategory.SHARED),
                DiffEntry(item="https://example.com/admin", category=VisibilityCategory.ONLY_A),
            ],
            auth_boundary={"auth_states_match": "True"},
        ),
    )
    return DiffNarrativeInput(diff=diff, surface_a=surface_a, surface_b=surface_b)


def _env() -> MessageEnvelope:
    return MessageEnvelope(
        payload=_make_input(),
        source="test",
        target="diff_narrative_agent",
        correlation_id="test-run",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDiffNarrativeAgent:
    def test_successful_narrative(self):
        response = _NarrativeResponse(
            executive_summary="Admin has broader surface.",
            insights=[
                _InsightItem(
                    title="Admin-only pages",
                    body="Admin can access /admin which viewer cannot.",
                    severity="notable",
                    confidence=0.8,
                    evidence_refs=["https://example.com/admin"],
                ),
            ],
        )
        llm = _MockLLM(response=response)
        agent = DiffNarrativeAgent(llm)

        result = agent.run(_env())
        narrative = result.payload

        assert narrative.role_a_name == "admin"
        assert narrative.role_b_name == "viewer"
        assert narrative.executive_summary == "Admin has broader surface."
        assert narrative.insight_count == 1
        assert narrative.insights[0].severity == InsightSeverity.NOTABLE
        assert narrative.insights[0].confidence == 0.8

    def test_empty_insights(self):
        response = _NarrativeResponse(
            executive_summary="No significant differences.",
        )
        llm = _MockLLM(response=response)
        agent = DiffNarrativeAgent(llm)

        result = agent.run(_env())
        assert result.payload.insight_count == 0

    def test_llm_error(self):
        llm = _MockLLM(error="API timeout")
        agent = DiffNarrativeAgent(llm)

        try:
            agent.run(_env())
            assert False, "Should have raised"
        except Exception as e:
            assert "LLM error" in str(e)

    def test_debug_stores_prompt(self):
        response = _NarrativeResponse(executive_summary="Test.")
        llm = _MockLLM(response=response)
        agent = DiffNarrativeAgent(llm, debug=True)

        agent.run(_env())
        assert agent._last_prompt is not None
        assert "admin" in agent._last_prompt
        assert "viewer" in agent._last_prompt

    def test_invalid_severity_defaults_to_info(self):
        response = _NarrativeResponse(
            executive_summary="Test.",
            insights=[
                _InsightItem(
                    title="Test insight",
                    body="Description",
                    severity="UNKNOWN_LEVEL",
                    confidence=0.5,
                ),
            ],
        )
        llm = _MockLLM(response=response)
        agent = DiffNarrativeAgent(llm)

        result = agent.run(_env())
        assert result.payload.insights[0].severity == InsightSeverity.INFO

    def test_confidence_clamped(self):
        response = _NarrativeResponse(
            executive_summary="Test.",
            insights=[
                _InsightItem(
                    title="Test",
                    body="Desc",
                    severity="info",
                    confidence=1.5,
                ),
            ],
        )
        llm = _MockLLM(response=response)
        agent = DiffNarrativeAgent(llm)

        result = agent.run(_env())
        assert result.payload.insights[0].confidence == 1.0

    def test_model_name_captured(self):
        response = _NarrativeResponse(executive_summary="Test.")
        llm = _MockLLM(response=response)
        agent = DiffNarrativeAgent(llm)

        result = agent.run(_env())
        assert result.payload.model_name == "mock-model"
