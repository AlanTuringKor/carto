"""Tests for redaction utilities."""

from __future__ import annotations

from carto.domain.auth import RedactedValue
from carto.utils.redaction import (
    extract_auth_evidence,
    is_sensitive_key,
    redact_cookies,
    redact_dict,
    redact_value,
)


class TestIsSensitiveKey:
    def test_token_keys(self) -> None:
        assert is_sensitive_key("access_token")
        assert is_sensitive_key("csrf_token")
        assert is_sensitive_key("xsrf-token")
        assert is_sensitive_key("auth_token")

    def test_session_keys(self) -> None:
        assert is_sensitive_key("session_id")
        assert is_sensitive_key("sessionid")
        assert is_sensitive_key("PHPSESSID")

    def test_password_keys(self) -> None:
        assert is_sensitive_key("password")
        assert is_sensitive_key("user_password")
        assert is_sensitive_key("passwd")

    def test_api_key_keys(self) -> None:
        assert is_sensitive_key("api_key")
        assert is_sensitive_key("apikey")
        assert is_sensitive_key("api-key")

    def test_non_sensitive_keys(self) -> None:
        assert not is_sensitive_key("username")
        assert not is_sensitive_key("page_title")
        assert not is_sensitive_key("url")
        assert not is_sensitive_key("step_count")


class TestRedactValue:
    def test_basic(self) -> None:
        rv = redact_value("my-secret")
        assert isinstance(rv, RedactedValue)
        assert rv.length == 9


class TestRedactDict:
    def test_auto_detect(self) -> None:
        d = {"session_id": "abc123", "page_title": "Home"}
        result = redact_dict(d)
        assert isinstance(result["session_id"], RedactedValue)
        assert result["page_title"] == "Home"

    def test_explicit_keys(self) -> None:
        d = {"custom_field": "secret", "other": "public"}
        result = redact_dict(d, sensitive_keys={"custom_field"}, auto_detect=False)
        assert isinstance(result["custom_field"], RedactedValue)
        assert result["other"] == "public"

    def test_no_redaction(self) -> None:
        d = {"name": "Alan", "url": "https://example.com"}
        result = redact_dict(d, auto_detect=True)
        assert result["name"] == "Alan"
        assert result["url"] == "https://example.com"


class TestRedactCookies:
    def test_all_values_redacted(self) -> None:
        cookies = {"sessionid": "abc123", "theme": "dark"}
        result = redact_cookies(cookies)
        assert isinstance(result["sessionid"], RedactedValue)
        assert isinstance(result["theme"], RedactedValue)


class TestExtractAuthEvidence:
    def test_sensitive_cookies(self) -> None:
        evidence = extract_auth_evidence(
            cookies={"session_token": "tok123", "theme": "dark"},
        )
        # "session_token" matches sensitive pattern, "theme" does not
        assert len(evidence) == 1
        assert evidence[0].key_name == "session_token"
        assert evidence[0].mechanism.value == "cookie"

    def test_bearer_header(self) -> None:
        evidence = extract_auth_evidence(
            cookies={},
            headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9"},
        )
        assert len(evidence) == 1
        assert evidence[0].mechanism.value == "bearer_token"

    def test_local_storage_token(self) -> None:
        evidence = extract_auth_evidence(
            cookies={},
            local_storage={"access_token": "tok456", "ui_state": "collapsed"},
        )
        assert len(evidence) == 1
        assert evidence[0].key_name == "access_token"

    def test_session_storage(self) -> None:
        evidence = extract_auth_evidence(
            cookies={},
            session_storage={"csrf_token": "csrf-xyz", "tab_id": "123"},
        )
        assert len(evidence) == 1
        assert evidence[0].key_name == "csrf_token"

    def test_combined(self) -> None:
        evidence = extract_auth_evidence(
            cookies={"sid": "c1"},
            headers={"Authorization": "Bearer tok"},
            local_storage={"jwt": "j1"},
            session_storage={"auth_state": "s1"},
        )
        assert len(evidence) == 4
