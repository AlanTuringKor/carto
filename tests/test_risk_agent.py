"""Tests for RiskAgent."""

import json

import pytest
from pydantic import BaseModel, Field

from carto.agents.risk import RiskAgent, RiskAssessmentResponse, RiskSignalResponse
from carto.contracts.envelope import MessageEnvelope
from carto.domain.artifacts import RiskSeverity
from carto.domain.inferences import ActionInventory, InferenceKind
from carto.domain.risk_input import RiskAssessment, RiskInput
from carto.llm.client import LLMError


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------


class MockLLM:
    def __init__(self, response_obj: object | None = None, error: str | None = None):
        self._response = response_obj
        self._error = error
        self.model_name = "mock-model"

    def complete(self, prompt: str, schema: type) -> object:
        if self._error:
            raise LLMError("mock-model", self._error)
        return self._response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_inventory() -> ActionInventory:
    return ActionInventory(
        run_id="r1",
        source_observation_id="obs-1",
        agent_name="page_understanding_agent",
        page_title="Login",
        page_summary="A login page",
        page_cluster="login",
        is_login_page=True,
        has_auth_forms=True,
    )


def _make_risk_input(inventory: ActionInventory | None = None) -> RiskInput:
    inv = inventory or _make_inventory()
    return RiskInput(
        inventory=inv,
        page_url="https://example.com/login",
        page_cluster="login",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRiskInput:
    def test_basic_construction(self):
        ri = _make_risk_input()
        assert ri.page_url == "https://example.com/login"
        assert ri.inventory.is_login_page

    def test_with_security_observations(self):
        ri = _make_risk_input()
        ri.security_observations = ["session cookie without Secure flag"]
        assert len(ri.security_observations) == 1


class TestRiskAssessment:
    def test_default_severity(self):
        ra = RiskAssessment(
            run_id="r1",
            source_observation_id="obs-1",
            agent_name="risk_agent",
        )
        assert ra.highest_severity == RiskSeverity.INFO
        assert ra.signals == []
        assert ra.kind == InferenceKind.RISK_SIGNAL


class TestRiskAgent:
    def test_successful_assessment(self):
        mock_response = RiskAssessmentResponse(
            signals=[
                RiskSignalResponse(
                    title="Missing CSRF token",
                    description="Login form has no CSRF token",
                    severity="medium",
                    evidence="No hidden CSRF field found",
                    cwe="CWE-352",
                ),
                RiskSignalResponse(
                    title="Password in form",
                    description="Password field detected",
                    severity="info",
                ),
            ],
            summary="Login page with missing CSRF protection.",
            highest_severity="medium",
        )

        llm = MockLLM(response_obj=mock_response)
        agent = RiskAgent(llm_client=llm)

        envelope = MessageEnvelope[RiskInput](
            source="orchestrator",
            target="risk_agent",
            correlation_id="r1",
            payload=_make_risk_input(),
        )

        result = agent.run(envelope)
        assessment = result.payload
        assert isinstance(assessment, RiskAssessment)
        assert len(assessment.signals) == 2
        assert assessment.signals[0].title == "Missing CSRF token"
        assert assessment.signals[0].cwe == "CWE-352"
        assert assessment.signals[0].severity == RiskSeverity.MEDIUM
        assert assessment.highest_severity == RiskSeverity.MEDIUM

    def test_empty_assessment(self):
        mock_response = RiskAssessmentResponse(
            signals=[],
            summary="No risk signals found.",
            highest_severity="info",
        )

        llm = MockLLM(response_obj=mock_response)
        agent = RiskAgent(llm_client=llm)

        envelope = MessageEnvelope[RiskInput](
            source="orchestrator",
            target="risk_agent",
            correlation_id="r1",
            payload=_make_risk_input(),
        )

        result = agent.run(envelope)
        assert len(result.payload.signals) == 0

    def test_llm_error_raises_agent_error(self):
        from carto.agents.base import AgentError

        llm = MockLLM(error="API timeout")
        agent = RiskAgent(llm_client=llm)

        envelope = MessageEnvelope[RiskInput](
            source="orchestrator",
            target="risk_agent",
            correlation_id="r1",
            payload=_make_risk_input(),
        )

        with pytest.raises(AgentError):
            agent.run(envelope)

    def test_debug_mode_stores_prompt(self):
        mock_response = RiskAssessmentResponse(
            signals=[], summary="No issues.", highest_severity="info",
        )

        llm = MockLLM(response_obj=mock_response)
        agent = RiskAgent(llm_client=llm, debug=True)

        envelope = MessageEnvelope[RiskInput](
            source="orchestrator",
            target="risk_agent",
            correlation_id="r1",
            payload=_make_risk_input(),
        )

        result = agent.run(envelope)
        assert result.payload.raw_prompt is not None
        assert result.payload.raw_response is not None

    def test_invalid_severity_defaults_to_info(self):
        mock_response = RiskAssessmentResponse(
            signals=[
                RiskSignalResponse(
                    title="Test", description="test",
                    severity="INVALID_SEVERITY",
                ),
            ],
            summary="test",
            highest_severity="INVALID",
        )

        llm = MockLLM(response_obj=mock_response)
        agent = RiskAgent(llm_client=llm)

        envelope = MessageEnvelope[RiskInput](
            source="orchestrator",
            target="risk_agent",
            correlation_id="r1",
            payload=_make_risk_input(),
        )

        result = agent.run(envelope)
        assert result.payload.signals[0].severity == RiskSeverity.INFO
        assert result.payload.highest_severity == RiskSeverity.INFO
