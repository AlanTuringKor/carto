"""Tests for structured event models."""

from carto.domain.auth import RedactedValue
from carto.domain.events import (
    Event,
    EventKind,
    _redact_data,
    approval_requested_event,
    approval_resolved_event,
    auth_transition_event,
    command_issued_event,
    command_result_event,
    decision_made_event,
    error_event,
    form_fill_planned_event,
    inference_produced_event,
    page_observed_event,
    run_completed_event,
    run_started_event,
    state_diff_computed_event,
    step_started_event,
)


class TestEventModel:
    def test_event_has_id_and_timestamp(self):
        e = Event(kind=EventKind.RUN_STARTED, run_id="r1")
        assert e.event_id
        assert e.timestamp
        assert e.kind == EventKind.RUN_STARTED

    def test_event_data_default(self):
        e = Event(kind=EventKind.ERROR, run_id="r1")
        assert e.data == {}


class TestEventKinds:
    def test_all_kinds_exist(self):
        assert len(EventKind) == 15

    def test_kinds_are_strings(self):
        for k in EventKind:
            assert isinstance(k.value, str)


class TestRedactData:
    def test_sensitive_key_redacted(self):
        result = _redact_data({"csrf_token": "secret123", "theme": "dark"})
        assert "secret123" not in str(result["csrf_token"])
        assert result["theme"] == "dark"

    def test_redacted_value_preserved(self):
        rv = RedactedValue.from_raw("tok")
        result = _redact_data({"token": rv})
        assert isinstance(result["token"], str)

    def test_nested_dict_redacted(self):
        result = _redact_data({"outer": {"password": "abc"}})
        assert "abc" not in str(result["outer"]["password"])


class TestFactoryFunctions:
    def test_run_started(self):
        e = run_started_event("r1", "s1", "https://example.com")
        assert e.kind == EventKind.RUN_STARTED
        assert e.run_id == "r1"
        assert e.data["start_url"] == "https://example.com"

    def test_run_completed(self):
        e = run_completed_event("r1", "s1", "completed", 10)
        assert e.kind == EventKind.RUN_COMPLETED
        assert e.data["step_count"] == 10

    def test_step_started(self):
        e = step_started_event("r1", 5, "https://example.com/page")
        assert e.step == 5

    def test_page_observed(self):
        e = page_observed_event("r1", 1, "o1", "https://x.com", "Page", 200, 10, 2)
        assert e.kind == EventKind.PAGE_OBSERVED
        assert e.data["element_count"] == 10

    def test_page_observed_with_cookies(self):
        e = page_observed_event(
            "r1", 1, "o1", "https://x.com", "P", 200, 0, 0,
            cookies={"session": "abc"},
        )
        assert "session" in e.data["cookie_names"]

    def test_inference_produced(self):
        e = inference_produced_event("r1", 2, "action_inventory", "page_agent", "i1")
        assert e.kind == EventKind.INFERENCE_PRODUCED

    def test_decision_made(self):
        e = decision_made_event("r1", 3, "click", "Submit", "best action")
        assert e.data["rationale"] == "best action"

    def test_command_issued(self):
        e = command_issued_event("r1", 4, "click", "c1", "#btn")
        assert e.data["command_kind"] == "click"

    def test_command_result(self):
        e = command_result_event("r1", 4, "c1", True, result_url="https://x.com")
        assert e.data["success"] is True

    def test_form_fill_planned(self):
        e = form_fill_planned_event("r1", 5, 3, True, True)
        assert e.data["is_login_form"] is True

    def test_state_diff_computed(self):
        e = state_diff_computed_event("r1", 6, True, True, False, "logged in")
        assert e.data["login_detected"] is True

    def test_auth_transition(self):
        e = auth_transition_event("r1", 7, False, True, "login_detected")
        assert e.kind == EventKind.AUTH_TRANSITION

    def test_approval_requested(self):
        e = approval_requested_event("r1", 8, "req1", "destructive_action", "Delete")
        assert e.data["reason"] == "destructive_action"

    def test_approval_resolved(self):
        e = approval_resolved_event("r1", 8, "req1", "approved", "human")
        assert e.data["decided_by"] == "human"


    def test_error(self):
        e = error_event("r1", 10, "RuntimeError", "boom")
        assert e.data["error_type"] == "RuntimeError"
