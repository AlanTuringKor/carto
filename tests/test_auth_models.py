"""Tests for auth domain models."""

from __future__ import annotations

from carto.domain.auth import (
    AuthContext,
    AuthEvidence,
    AuthMechanism,
    AuthTransition,
    LoginFlowObservation,
    RedactedValue,
)


class TestRedactedValue:
    def test_from_raw_short_value(self) -> None:
        rv = RedactedValue.from_raw("abc")
        assert rv.preview == "***"
        assert rv.length == 3
        assert len(rv.fingerprint) == 64  # SHA-256 hex

    def test_from_raw_long_value(self) -> None:
        rv = RedactedValue.from_raw("my-secret-token-value")
        assert rv.preview == "my-***lue"
        assert rv.length == 21

    def test_fingerprint_is_deterministic(self) -> None:
        rv1 = RedactedValue.from_raw("same-value")
        rv2 = RedactedValue.from_raw("same-value")
        assert rv1.fingerprint == rv2.fingerprint

    def test_different_values_different_fingerprints(self) -> None:
        rv1 = RedactedValue.from_raw("value-a")
        rv2 = RedactedValue.from_raw("value-b")
        assert rv1.fingerprint != rv2.fingerprint

    def test_str_representation(self) -> None:
        rv = RedactedValue.from_raw("some-long-token")
        s = str(rv)
        assert "REDACTED" in s
        assert "some-long-token" not in s

    def test_serialise_roundtrip(self) -> None:
        rv = RedactedValue.from_raw("secret-123")
        json_str = rv.model_dump_json()
        rv2 = RedactedValue.model_validate_json(json_str)
        assert rv2.fingerprint == rv.fingerprint
        assert rv2.preview == rv.preview
        # Raw value is NOT in JSON
        assert "secret-123" not in json_str


class TestAuthEvidence:
    def test_creation(self) -> None:
        rv = RedactedValue.from_raw("session-token-abc")
        ev = AuthEvidence(
            mechanism=AuthMechanism.COOKIE,
            key_name="sessionid",
            value=rv,
            source="cookie",
        )
        assert ev.mechanism == AuthMechanism.COOKIE
        assert ev.key_name == "sessionid"
        assert ev.value.length == 17


class TestAuthContext:
    def test_defaults(self) -> None:
        ctx = AuthContext()
        assert ctx.is_authenticated is False
        assert ctx.primary_mechanism == AuthMechanism.UNKNOWN
        assert ctx.evidence == []

    def test_with_evidence(self) -> None:
        ev = AuthEvidence(
            mechanism=AuthMechanism.BEARER_TOKEN,
            key_name="Authorization",
            value=RedactedValue.from_raw("Bearer eyJhbGc..."),
            source="response_header",
        )
        ctx = AuthContext(
            is_authenticated=True,
            primary_mechanism=AuthMechanism.BEARER_TOKEN,
            evidence=[ev],
            bearer_token_present=True,
        )
        assert ctx.is_authenticated is True
        assert len(ctx.evidence) == 1


class TestLoginFlowObservation:
    def test_creation(self) -> None:
        lfo = LoginFlowObservation(
            page_url="https://example.com/login",
            form_action="/auth/login",
            username_field_selector="input[name='email']",
            password_field_selector="input[name='password']",
            csrf_field_name="_csrf",
        )
        assert lfo.form_method == "post"
        assert lfo.has_remember_me is False
        assert lfo.csrf_field_name == "_csrf"


class TestAuthTransition:
    def test_login_transition(self) -> None:
        t = AuthTransition(
            before_authenticated=False,
            after_authenticated=True,
            trigger_label="Login button click",
            summary="User logged in via form submission",
        )
        assert t.before_authenticated is False
        assert t.after_authenticated is True

    def test_serialise_roundtrip(self) -> None:
        t = AuthTransition(
            before_authenticated=True,
            after_authenticated=False,
        )
        json_str = t.model_dump_json()
        t2 = AuthTransition.model_validate_json(json_str)
        assert t2.transition_id == t.transition_id
