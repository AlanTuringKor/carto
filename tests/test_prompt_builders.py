"""Tests for prompt builders."""

from __future__ import annotations

from carto.agents.prompts.action_planner import build_action_planner_prompt
from carto.agents.prompts.form_filler import build_form_filler_prompt
from carto.agents.prompts.page_understanding import build_page_understanding_prompt
from carto.agents.prompts.state_diff import build_state_diff_prompt
from carto.domain.inferences import (
    ActionInventory,
    DiscoveredAction,
    DiscoveredField,
    FormFillerInput,
    InferenceKind,
    StateDiffInput,
)
from carto.domain.models import ActionKind, AuthState, FieldKind, State
from carto.domain.observations import (
    ElementSnapshot,
    FormSnapshot,
    ObservationKind,
    PageObservation,
)


def _make_observation() -> PageObservation:
    return PageObservation(
        run_id="run-1",
        url="https://example.com/login",
        final_url="https://example.com/login",
        title="Login Page",
        status_code=200,
        accessible_text="Please enter your username and password",
        interactive_elements=[
            ElementSnapshot(tag="input", text="", attributes={"type": "text", "name": "username"}),
            ElementSnapshot(tag="input", text="", attributes={"type": "password", "name": "password"}),
            ElementSnapshot(tag="button", text="Log In"),
        ],
        forms_raw=[
            FormSnapshot(
                action="/auth/login",
                method="post",
                fields_raw=[
                    {"tag": "input", "type": "text", "name": "username"},
                    {"tag": "input", "type": "password", "name": "password"},
                    {"tag": "input", "type": "hidden", "name": "_csrf"},
                ],
            ),
        ],
        cookies={"session_id": "abc123"},
    )


class TestPageUnderstandingPrompt:
    def test_contains_url(self) -> None:
        obs = _make_observation()
        prompt = build_page_understanding_prompt(obs)
        assert "https://example.com/login" in prompt

    def test_contains_accessible_text(self) -> None:
        obs = _make_observation()
        prompt = build_page_understanding_prompt(obs)
        assert "username and password" in prompt

    def test_contains_elements(self) -> None:
        obs = _make_observation()
        prompt = build_page_understanding_prompt(obs)
        assert "<input>" in prompt or "input" in prompt.lower()

    def test_contains_form_fields(self) -> None:
        obs = _make_observation()
        prompt = build_page_understanding_prompt(obs)
        assert "_csrf" in prompt

    def test_contains_auth_hints(self) -> None:
        obs = _make_observation()
        prompt = build_page_understanding_prompt(obs)
        assert "session_id" in prompt

    def test_contains_json_instructions(self) -> None:
        obs = _make_observation()
        prompt = build_page_understanding_prompt(obs)
        assert "JSON" in prompt


class TestActionPlannerPrompt:
    def test_contains_actions(self) -> None:
        inventory = ActionInventory(
            run_id="run-1",
            source_observation_id="obs-1",
            agent_name="page_understanding_agent",
            discovered_actions=[
                DiscoveredAction(label="Login", kind=ActionKind.CLICK, priority=0.9),
            ],
        )
        state = State(run_id="run-1", current_url="https://example.com/login")
        prompt = build_action_planner_prompt(inventory, state)
        assert "Login" in prompt
        assert "0.9" in prompt

    def test_contains_state(self) -> None:
        inventory = ActionInventory(
            run_id="run-1",
            source_observation_id="obs-1",
            agent_name="page_understanding_agent",
        )
        state = State(
            run_id="run-1",
            current_url="https://example.com",
            auth_state=AuthState.AUTHENTICATED,
        )
        prompt = build_action_planner_prompt(inventory, state)
        assert "authenticated" in prompt.lower()


class TestFormFillerPrompt:
    def test_contains_fields(self) -> None:
        input_data = FormFillerInput(
            form_fields=[
                DiscoveredField(name="email", kind=FieldKind.EMAIL, label="Email"),
            ],
            page_url="https://example.com/register",
        )
        prompt = build_form_filler_prompt(input_data)
        assert "email" in prompt.lower()

    def test_login_context(self) -> None:
        input_data = FormFillerInput(
            form_fields=[
                DiscoveredField(name="username", kind=FieldKind.TEXT),
                DiscoveredField(name="password", kind=FieldKind.PASSWORD),
            ],
            page_url="https://example.com/login",
            is_login_form=True,
            role_username="admin",
            role_password="secret123",
        )
        prompt = build_form_filler_prompt(input_data)
        assert "admin" in prompt
        assert "Login Form Context" in prompt


class TestStateDiffPrompt:
    def test_contains_before_after(self) -> None:
        before = State(
            run_id="run-1",
            current_url="https://example.com/login",
            cookies={"theme": "dark"},
        )
        after = State(
            run_id="run-1",
            current_url="https://example.com/dashboard",
            cookies={"theme": "dark", "session": "tok123"},
        )
        input_data = StateDiffInput(
            before=before,
            after=after,
            page_url_before="https://example.com/login",
            page_url_after="https://example.com/dashboard",
        )
        prompt = build_state_diff_prompt(input_data)
        assert "Before" in prompt
        assert "After" in prompt
        assert "session" in prompt
