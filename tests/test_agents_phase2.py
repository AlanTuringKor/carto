"""Tests for Phase 2 agent implementations with mock LLM."""

from __future__ import annotations

import json

import pytest

from carto.agents.action_planner import ActionPlannerAgent
from carto.agents.base import AgentError
from carto.agents.form_filler import FormFillerAgent
from carto.agents.page_understanding import PageUnderstandingAgent
from carto.agents.state_diff import StateDiffAgent
from carto.contracts.envelope import MessageEnvelope
from carto.domain.inferences import (
    DiscoveredField,
    FormFillerInput,
    ActionInventory,
    InferenceKind,
    StateDiffInput,
)
from carto.domain.models import ActionKind, FieldKind, State
from carto.domain.observations import (
    ElementSnapshot,
    FormSnapshot,
    ObservationKind,
    PageObservation,
)
from carto.llm.client import LLMClient, LLMError


# ---------------------------------------------------------------------------
# Mock LLM client
# ---------------------------------------------------------------------------


class MockLLM:
    """Mock LLM that returns pre-configured JSON for each response model."""

    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses  # model_class_name → JSON string

    @property
    def model_name(self) -> str:
        return "mock-gpt"

    def complete(self, prompt: str, response_model: type) -> object:
        name = response_model.__name__
        if name not in self._responses:
            raise LLMError("mock-gpt", f"No mock response for {name}")
        return response_model.model_validate_json(self._responses[name])


class FailingMockLLM:
    """Mock LLM that always fails."""

    @property
    def model_name(self) -> str:
        return "failing-mock"

    def complete(self, prompt: str, response_model: type) -> object:
        raise LLMError("failing-mock", "API failure")


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

PAGE_UNDERSTANDING_RESPONSE = json.dumps({
    "page_title": "Login",
    "page_summary": "A login page for the application.",
    "page_cluster": "login",
    "auth_required": False,
    "is_login_page": True,
    "is_logout_page": False,
    "has_auth_forms": True,
    "csrf_hints": ["_csrf"],
    "auth_mechanisms_detected": ["cookie_session"],
    "login_form_selector": "form#login",
    "username_field_selector": "input[name='user']",
    "password_field_selector": "input[name='pass']",
    "discovered_actions": [
        {
            "label": "Submit Login",
            "kind": "submit",
            "css_selector": "button[type='submit']",
            "priority": 0.95,
        }
    ],
    "discovered_forms": [
        [
            {"name": "user", "kind": "text", "label": "Username", "required": True},
            {"name": "pass", "kind": "password", "label": "Password", "required": True},
        ]
    ],
    "navigation_links": ["/forgot-password"],
    "api_endpoints_observed": [],
    "interesting_patterns": ["No CSRF token on login form"],
})

ACTION_PLANNER_RESPONSE = json.dumps({
    "chosen_action_kind": "click",
    "chosen_css_selector": "button[type='submit']",
    "chosen_label": "Submit Login",
    "rationale": "Login form should be submitted to explore authenticated areas.",
    "expected_outcome": "Redirect to dashboard after login.",
    "estimated_coverage_gain": 0.8,
    "should_stop": False,
})

FORM_FILLER_RESPONSE = json.dumps({
    "form_css_selector": "form#login",
    "field_instructions": [
        {"css_selector": "input[name='user']", "value": "admin", "rationale": "Login username"},
        {"css_selector": "input[name='pass']", "value": "password123", "rationale": "Login password"},
    ],
    "should_submit": True,
    "is_login_form": True,
    "auth_field_selectors": ["input[name='user']", "input[name='pass']"],
})

STATE_DIFF_RESPONSE = json.dumps({
    "url_changed": True,
    "auth_state_changed": True,
    "login_detected": True,
    "logout_detected": False,
    "session_refresh_detected": False,
    "cookies_added": ["session_id"],
    "cookies_removed": [],
    "cookies_modified": [],
    "storage_keys_added": [],
    "storage_keys_removed": [],
    "role_changed": False,
    "security_observations": ["Session cookie set without Secure flag"],
    "summary": "User logged in. Session cookie created.",
})


def _make_observation() -> PageObservation:
    return PageObservation(
        run_id="run-1",
        url="https://example.com/login",
        final_url="https://example.com/login",
        title="Login",
        interactive_elements=[
            ElementSnapshot(tag="input", attributes={"name": "user"}),
            ElementSnapshot(tag="button", text="Submit"),
        ],
        forms_raw=[
            FormSnapshot(action="/login", method="post", fields_raw=[]),
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPageUnderstandingAgent:
    def test_produces_action_inventory(self) -> None:
        llm = MockLLM({"ActionInventoryResponse": PAGE_UNDERSTANDING_RESPONSE})
        agent = PageUnderstandingAgent(llm)

        obs = _make_observation()
        envelope = MessageEnvelope[PageObservation](
            source="orchestrator",
            target="page_understanding_agent",
            correlation_id="run-1",
            payload=obs,
        )

        result = agent.run(envelope)
        inv = result.payload
        assert inv.kind == InferenceKind.ACTION_INVENTORY
        assert inv.is_login_page is True
        assert inv.page_cluster == "login"
        assert len(inv.discovered_actions) == 1
        assert inv.discovered_actions[0].label == "Submit Login"
        assert inv.agent_name == "page_understanding_agent"

    def test_raises_on_llm_failure(self) -> None:
        agent = PageUnderstandingAgent(FailingMockLLM())
        obs = _make_observation()
        envelope = MessageEnvelope[PageObservation](
            source="o", target="p", correlation_id="r", payload=obs
        )
        with pytest.raises(AgentError):
            agent.run(envelope)


class TestActionPlannerAgent:
    def test_produces_decision(self) -> None:
        llm = MockLLM({"NextActionResponse": ACTION_PLANNER_RESPONSE})
        agent = ActionPlannerAgent(llm)

        inventory = ActionInventory(
            run_id="run-1",
            source_observation_id="obs-1",
            agent_name="page_understanding_agent",
        )
        state = State(run_id="run-1", current_url="https://example.com/login")
        agent.set_state(state)

        envelope = MessageEnvelope[ActionInventory](
            source="orchestrator",
            target="action_planner_agent",
            correlation_id="run-1",
            payload=inventory,
        )

        result = agent.run(envelope)
        decision = result.payload
        assert decision.chosen_action_kind == ActionKind.CLICK
        assert decision.should_stop is False
        assert "Login" in decision.rationale

    def test_raises_on_llm_failure(self) -> None:
        agent = ActionPlannerAgent(FailingMockLLM())
        inventory = ActionInventory(
            run_id="r", source_observation_id="o", agent_name="p"
        )
        envelope = MessageEnvelope[ActionInventory](
            source="o", target="a", correlation_id="r", payload=inventory
        )
        with pytest.raises(AgentError):
            agent.run(envelope)


class TestFormFillerAgent:
    def test_produces_fill_plan(self) -> None:
        llm = MockLLM({"FormFillResponse": FORM_FILLER_RESPONSE})
        agent = FormFillerAgent(llm)

        input_data = FormFillerInput(
            form_fields=[
                DiscoveredField(name="user", kind=FieldKind.TEXT),
                DiscoveredField(name="pass", kind=FieldKind.PASSWORD),
            ],
            page_url="https://example.com/login",
            is_login_form=True,
        )
        envelope = MessageEnvelope[FormFillerInput](
            source="orchestrator",
            target="form_filler_agent",
            correlation_id="run-1",
            payload=input_data,
        )

        result = agent.run(envelope)
        plan = result.payload
        assert plan.is_login_form is True
        assert len(plan.field_instructions) == 2
        assert plan.should_submit is True

    def test_raises_on_llm_failure(self) -> None:
        agent = FormFillerAgent(FailingMockLLM())
        input_data = FormFillerInput(form_fields=[], page_url="https://x.com")
        envelope = MessageEnvelope[FormFillerInput](
            source="o", target="f", correlation_id="r", payload=input_data
        )
        with pytest.raises(AgentError):
            agent.run(envelope)


class TestStateDiffAgent:
    def test_produces_state_delta(self) -> None:
        llm = MockLLM({"StateDiffResponse": STATE_DIFF_RESPONSE})
        agent = StateDiffAgent(llm)

        before = State(run_id="run-1", current_url="https://example.com/login")
        after = State(
            run_id="run-1",
            current_url="https://example.com/dashboard",
            cookies={"session_id": "tok123"},
        )
        input_data = StateDiffInput(before=before, after=after)
        envelope = MessageEnvelope[StateDiffInput](
            source="orchestrator",
            target="state_diff_agent",
            correlation_id="run-1",
            payload=input_data,
        )

        result = agent.run(envelope)
        delta = result.payload
        assert delta.login_detected is True
        assert delta.auth_state_changed is True
        assert "session_id" in delta.cookies_added
        assert len(delta.security_observations) == 1

    def test_raises_on_llm_failure(self) -> None:
        agent = StateDiffAgent(FailingMockLLM())
        before = State(run_id="r", current_url="u")
        after = State(run_id="r", current_url="u")
        input_data = StateDiffInput(before=before, after=after)
        envelope = MessageEnvelope[StateDiffInput](
            source="o", target="s", correlation_id="r", payload=input_data
        )
        with pytest.raises(AgentError):
            agent.run(envelope)
