"""
Authentication domain models for Carto.

These models capture auth-related observations and context that are
critical for mapping quality.  All secret/token values are stored as
``RedactedValue`` instances — never as raw strings — so they cannot
accidentally leak into logs, JSON exports, or LLM prompts.

Design:
    - ``RedactedValue`` wraps a secret with a SHA-256 fingerprint and
      a masked preview (first 3 + last 3 chars).
    - ``AuthEvidence`` represents a single observed authentication signal.
    - ``AuthContext`` aggregates evidence for a page/request.
    - ``LoginFlowObservation`` captures a login form structure.
    - ``AuthTransition`` records an auth state change.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# RedactedValue — never exposes raw secrets
# ---------------------------------------------------------------------------


class RedactedValue(BaseModel):
    """
    A secret value stored in redacted form.

    The raw value is *not* stored.  Instead we keep:
    - ``fingerprint``: SHA-256 hex digest for identity comparison.
    - ``preview``: masked preview like ``"abc***xyz"`` for debugging.
    - ``length``: original value length.

    This ensures secrets are never accidentally serialised, logged,
    or sent to an LLM prompt.
    """

    fingerprint: str
    preview: str
    length: int

    @classmethod
    def from_raw(cls, raw: str) -> RedactedValue:
        """Create a RedactedValue from a raw secret string."""
        fingerprint = hashlib.sha256(raw.encode()).hexdigest()
        if len(raw) <= 6:
            preview = "***"
        else:
            preview = f"{raw[:3]}***{raw[-3:]}"
        return cls(fingerprint=fingerprint, preview=preview, length=len(raw))

    def __str__(self) -> str:
        return f"[REDACTED {self.preview}]"

    def __repr__(self) -> str:
        return f"RedactedValue(preview={self.preview!r}, len={self.length})"


# ---------------------------------------------------------------------------
# Auth mechanism classification
# ---------------------------------------------------------------------------


class AuthMechanism(StrEnum):
    """How authentication is conveyed in requests."""

    COOKIE = "cookie"
    BEARER_TOKEN = "bearer_token"
    SESSION_STORAGE = "session_storage"
    LOCAL_STORAGE = "local_storage"
    BASIC_AUTH = "basic_auth"
    FORM_POST = "form_post"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# AuthEvidence — a single observed auth signal
# ---------------------------------------------------------------------------


class AuthEvidence(BaseModel):
    """
    A single piece of observed authentication evidence.

    Examples:
    - A ``Set-Cookie`` header with name ``sessionid``
    - A ``localStorage`` key containing ``token``
    - An ``Authorization: Bearer …`` header
    """

    evidence_id: str = Field(default_factory=_uuid)
    mechanism: AuthMechanism
    key_name: str                    # e.g. "sessionid", "Authorization"
    value: RedactedValue             # never the raw secret
    source: str                      # e.g. "cookie", "response_header", "local_storage"
    observed_at: datetime = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# AuthContext — aggregated auth state for a page/request scope
# ---------------------------------------------------------------------------


class AuthContext(BaseModel):
    """
    Aggregated auth context for a page or step.

    Built from observed cookies, headers, storage values, and form
    structures.  Used to inform agents about the current auth posture.
    """

    is_authenticated: bool = False
    primary_mechanism: AuthMechanism = AuthMechanism.UNKNOWN
    evidence: list[AuthEvidence] = Field(default_factory=list)
    csrf_token_present: bool = False
    csrf_token_name: str | None = None
    session_cookie_names: list[str] = Field(default_factory=list)
    bearer_token_present: bool = False
    refresh_token_present: bool = False


# ---------------------------------------------------------------------------
# LoginFlowObservation — structured capture of a login form
# ---------------------------------------------------------------------------


class LoginFlowObservation(BaseModel):
    """
    Structured observation of a login form or auth flow.

    Captured when the PageUnderstandingAgent identifies a page as a
    login / authentication page.
    """

    observation_id: str = Field(default_factory=_uuid)
    page_url: str
    form_action: str | None = None
    form_method: str = "post"
    username_field_selector: str | None = None
    password_field_selector: str | None = None
    csrf_field_selector: str | None = None
    csrf_field_name: str | None = None
    additional_fields: list[str] = Field(default_factory=list)
    has_remember_me: bool = False
    has_oauth_buttons: bool = False
    oauth_providers: list[str] = Field(default_factory=list)
    observed_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# AuthTransition — records a change in auth state
# ---------------------------------------------------------------------------


class AuthTransition(BaseModel):
    """
    Records an observed change in authentication state.

    Created by the StateDiffAgent when it detects login/logout events,
    new session tokens, or other auth-related state changes.
    """

    transition_id: str = Field(default_factory=_uuid)
    before_authenticated: bool
    after_authenticated: bool
    trigger_action_id: str | None = None
    trigger_label: str | None = None
    new_evidence: list[AuthEvidence] = Field(default_factory=list)
    lost_evidence: list[AuthEvidence] = Field(default_factory=list)
    transitioned_at: datetime = Field(default_factory=_now)
    summary: str | None = None
