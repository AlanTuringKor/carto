"""Tests for inference models."""

from __future__ import annotations

from carto.domain.inferences import (
    ActionInventory,
    DiscoveredAction,
    FormFillPlan,
    InferenceKind,
    NextActionDecision,
    StateDelta,
)
from carto.domain.models import ActionKind


class TestActionInventory:
    def test_defaults(self) -> None:
        inv = ActionInventory(
            run_id="run-1",
            source_observation_id="obs-1",
            agent_name="page_understanding_agent",
        )
        assert inv.kind == InferenceKind.ACTION_INVENTORY
        assert inv.discovered_actions == []
        assert inv.auth_required is False

    def test_with_actions(self) -> None:
        action = DiscoveredAction(
            label="Login",
            kind=ActionKind.CLICK,
            css_selector="button.login",
            priority=0.9,
        )
        inv = ActionInventory(
            run_id="run-1",
            source_observation_id="obs-1",
            agent_name="page_understanding_agent",
            discovered_actions=[action],
        )
        assert len(inv.discovered_actions) == 1
        assert inv.discovered_actions[0].priority == 0.9


class TestNextActionDecision:
    def test_stop_decision(self) -> None:
        d = NextActionDecision(
            run_id="run-1",
            source_observation_id="obs-1",
            agent_name="action_planner_agent",
            chosen_action_kind=ActionKind.NAVIGATE,
            rationale="All paths explored.",
            should_stop=True,
            stop_reason="coverage_complete",
        )
        assert d.should_stop is True
        assert d.kind == InferenceKind.NEXT_ACTION_DECISION

    def test_navigate_decision(self) -> None:
        d = NextActionDecision(
            run_id="run-1",
            source_observation_id="obs-1",
            agent_name="action_planner_agent",
            chosen_action_kind=ActionKind.NAVIGATE,
            chosen_href="https://example.com/admin",
            rationale="Admin area not yet explored.",
        )
        assert d.chosen_href == "https://example.com/admin"


class TestFormFillPlanStub:
    def test_empty_plan(self) -> None:
        plan = FormFillPlan(
            run_id="run-1",
            source_observation_id="obs-1",
            agent_name="form_filler_agent",
        )
        assert plan.kind == InferenceKind.FORM_FILL_PLAN
        assert plan.field_instructions == []


class TestStateDeltaStub:
    def test_empty_delta(self) -> None:
        delta = StateDelta(
            run_id="run-1",
            source_observation_id="obs-1",
            agent_name="state_diff_agent",
            before_state_id="s1",
            after_state_id="s2",
        )
        assert delta.kind == InferenceKind.STATE_DELTA
        assert delta.auth_state_changed is False
