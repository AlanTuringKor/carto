"""
Redaction utilities for Carto.

Provides helpers for masking sensitive values (tokens, session IDs,
passwords) so they never appear in logs, LLM prompts, or exported
artefacts in raw form.

Design:
    - Every sensitive value is converted to a ``RedactedValue`` with
      a SHA-256 fingerprint (for identity comparison) and a masked
      preview (for debugging).
    - A configurable set of key-name patterns identifies which dict
      keys should be treated as sensitive.
    - Redaction is applied at the boundary (before logging, before
      prompt construction) — not at storage time — so raw values
      are available when explicitly needed.
"""

from __future__ import annotations

import re

from carto.domain.auth import AuthEvidence, AuthMechanism, RedactedValue

# ---------------------------------------------------------------------------
# Sensitive key patterns
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"token",
        r"session",
        r"auth",
        r"csrf",
        r"xsrf",
        r"bearer",
        r"password",
        r"passwd",
        r"secret",
        r"api.?key",
        r"access.?key",
        r"refresh",
        r"jwt",
        r"cookie",
        r"sid",
        r"ssid",
        r"credential",
    ]
]


def is_sensitive_key(key: str) -> bool:
    """Return True if *key* matches any sensitive name pattern."""
    return any(p.search(key) for p in _SENSITIVE_PATTERNS)


# ---------------------------------------------------------------------------
# Value redaction
# ---------------------------------------------------------------------------


def redact_value(raw: str) -> RedactedValue:
    """Create a ``RedactedValue`` from a raw string."""
    return RedactedValue.from_raw(raw)


def redact_dict(
    d: dict[str, str],
    *,
    sensitive_keys: set[str] | None = None,
    auto_detect: bool = True,
) -> dict[str, str | RedactedValue]:
    """
    Return a copy of *d* with sensitive values replaced by ``RedactedValue``.

    Parameters
    ----------
    d:
        The original dict (e.g. cookies, headers, storage).
    sensitive_keys:
        Explicit set of key names to redact.
    auto_detect:
        If True (default), also redact keys matching ``_SENSITIVE_PATTERNS``.
    """
    explicit = sensitive_keys or set()
    result: dict[str, str | RedactedValue] = {}

    for key, value in d.items():
        should_redact = key in explicit
        if auto_detect and not should_redact:
            should_redact = is_sensitive_key(key)

        if should_redact:
            result[key] = RedactedValue.from_raw(value)
        else:
            result[key] = value

    return result


def redact_cookies(cookies: dict[str, str]) -> dict[str, RedactedValue]:
    """Redact *all* cookie values — cookies are always sensitive."""
    return {name: RedactedValue.from_raw(value) for name, value in cookies.items()}


# ---------------------------------------------------------------------------
# Auth evidence extraction from browser state
# ---------------------------------------------------------------------------


def extract_auth_evidence(
    cookies: dict[str, str],
    headers: dict[str, str] | None = None,
    local_storage: dict[str, str] | None = None,
    session_storage: dict[str, str] | None = None,
) -> list[AuthEvidence]:
    """
    Scan browser state for authentication-related artefacts.

    Returns a list of ``AuthEvidence`` instances with redacted values.
    This is called by agents/prompt-builders, never by the executor.
    """
    evidence: list[AuthEvidence] = []

    # Cookies
    for name, value in cookies.items():
        if is_sensitive_key(name):
            evidence.append(
                AuthEvidence(
                    mechanism=AuthMechanism.COOKIE,
                    key_name=name,
                    value=RedactedValue.from_raw(value),
                    source="cookie",
                )
            )

    # Response headers
    if headers:
        auth_header = headers.get("authorization") or headers.get("Authorization")
        if auth_header:
            if auth_header.lower().startswith("bearer "):
                evidence.append(
                    AuthEvidence(
                        mechanism=AuthMechanism.BEARER_TOKEN,
                        key_name="Authorization",
                        value=RedactedValue.from_raw(auth_header),
                        source="response_header",
                    )
                )
            else:
                evidence.append(
                    AuthEvidence(
                        mechanism=AuthMechanism.BASIC_AUTH,
                        key_name="Authorization",
                        value=RedactedValue.from_raw(auth_header),
                        source="response_header",
                    )
                )

    # localStorage
    if local_storage:
        for key, value in local_storage.items():
            if is_sensitive_key(key):
                evidence.append(
                    AuthEvidence(
                        mechanism=AuthMechanism.LOCAL_STORAGE,
                        key_name=key,
                        value=RedactedValue.from_raw(value),
                        source="local_storage",
                    )
                )

    # sessionStorage
    if session_storage:
        for key, value in session_storage.items():
            if is_sensitive_key(key):
                evidence.append(
                    AuthEvidence(
                        mechanism=AuthMechanism.SESSION_STORAGE,
                        key_name=key,
                        value=RedactedValue.from_raw(value),
                        source="session_storage",
                    )
                )

    return evidence
