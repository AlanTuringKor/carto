"""Tests for domain models."""

from __future__ import annotations

from carto.domain.models import (
    Action,
    ActionKind,
    AuthState,
    FieldKind,
    Form,
    FormField,
    Page,
    Run,
    RunStatus,
    Session,
    SessionStatus,
    State,
)


class TestSession:
    def test_defaults(self) -> None:
        s = Session(target_url="https://example.com")
        assert s.session_id != ""
        assert s.status == SessionStatus.PENDING
        assert s.run_ids == []

    def test_model_copy_update(self) -> None:
        s = Session(target_url="https://example.com")
        s2 = s.model_copy(update={"status": SessionStatus.RUNNING})
        assert s2.status == SessionStatus.RUNNING
        assert s.status == SessionStatus.PENDING  # original unchanged


class TestRun:
    def test_create_run(self) -> None:
        r = Run(session_id="sid-1", start_url="https://example.com")
        assert r.run_id != ""
        assert r.status == RunStatus.PENDING
        assert r.step_count == 0

    def test_run_serialise_roundtrip(self) -> None:
        r = Run(session_id="sid-1", start_url="https://x.com")
        data = r.model_dump_json()
        r2 = Run.model_validate_json(data)
        assert r2.run_id == r.run_id
        assert r2.start_url == r.start_url


class TestPage:
    def test_page_fields(self) -> None:
        p = Page(run_id="run-1", url="https://example.com/login", normalised_url="https://example.com/login")
        assert p.auth_state == AuthState.UNKNOWN
        assert p.visit_count == 0


class TestAction:
    def test_action_defaults(self) -> None:
        a = Action(page_id="page-1", kind=ActionKind.CLICK)
        assert a.priority == 0.0
        assert a.metadata == {}

    def test_action_with_selector(self) -> None:
        a = Action(
            page_id="page-1",
            kind=ActionKind.FILL,
            css_selector="input[name='username']",
            label="Username",
        )
        assert a.css_selector == "input[name='username']"


class TestField:
    def test_field_kinds(self) -> None:
        f = FormField(kind=FieldKind.PASSWORD, name="password", required=True)
        assert f.required is True
        assert f.options == []


class TestForm:
    def test_form_with_fields(self) -> None:
        field = FormField(kind=FieldKind.TEXT, name="q")
        form = Form(page_id="page-1", action="/search", method="get", fields=[field])
        assert len(form.fields) == 1
        assert form.method == "get"


class TestState:
    def test_state_defaults(self) -> None:
        s = State(run_id="run-1", current_url="https://example.com")
        assert s.auth_state == AuthState.UNKNOWN
        assert s.visited_page_ids == []
        assert s.cookies == {}
