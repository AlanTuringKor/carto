"""
Core domain models for Carto.

These are the fundamental entities tracked across a mapping session.
All models are pure Pydantic V2 data containers — no I/O, no LLM calls.
"""

from __future__ import annotations

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
# Enumerations
# ---------------------------------------------------------------------------


class SessionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ActionKind(StrEnum):
    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    SUBMIT = "submit"
    HOVER = "hover"
    SCROLL = "scroll"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    BACK = "back"
    UNKNOWN = "unknown"


class FieldKind(StrEnum):
    TEXT = "text"
    PASSWORD = "password"
    EMAIL = "email"
    NUMBER = "number"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    SELECT = "select"
    TEXTAREA = "textarea"
    FILE = "file"
    HIDDEN = "hidden"
    SUBMIT = "submit"
    BUTTON = "button"
    UNKNOWN = "unknown"


class AuthState(StrEnum):
    UNAUTHENTICATED = "unauthenticated"
    AUTHENTICATED = "authenticated"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Field
# ---------------------------------------------------------------------------


class FormField(BaseModel):
    """A single HTML form field."""

    field_id: str = Field(default_factory=_uuid)
    name: str | None = None
    label: str | None = None
    kind: FieldKind = FieldKind.UNKNOWN
    placeholder: str | None = None
    required: bool = False
    options: list[str] = Field(default_factory=list)
    css_selector: str | None = None
    aria_label: str | None = None


# ---------------------------------------------------------------------------
# Form
# ---------------------------------------------------------------------------


class Form(BaseModel):
    """An HTML form with its fields."""

    form_id: str = Field(default_factory=_uuid)
    page_id: str
    action: str | None = None
    method: str = "get"
    fields: list[FormField] = Field(default_factory=list)
    submit_selector: str | None = None
    raw_html: str | None = None


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------


class Action(BaseModel):
    """
    A single interactive element or navigation opportunity on a page.

    Actions are discovered by the PageUnderstandingAgent from observations.
    They represent *what can be done*, not *what was done*.
    """

    action_id: str = Field(default_factory=_uuid)
    page_id: str
    kind: ActionKind
    label: str | None = None
    css_selector: str | None = None
    href: str | None = None
    method: str | None = None
    form_id: str | None = None
    priority: float = 0.0  # 0.0 = lowest, 1.0 = highest
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


class Page(BaseModel):
    """
    A unique page encountered during a mapping run.

    A page is identified by its normalised URL.  Two fetches of the same URL
    share the same Page object; observations are separate.
    """

    page_id: str = Field(default_factory=_uuid)
    run_id: str
    url: str
    normalised_url: str
    title: str | None = None
    discovered_at: datetime = Field(default_factory=_now)
    auth_state: AuthState = AuthState.UNKNOWN
    visit_count: int = 0
    forms: list[str] = Field(default_factory=list)  # form_ids
    actions: list[str] = Field(default_factory=list)  # action_ids


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class State(BaseModel):
    """
    A snapshot of the session state at a point in time.

    State captures what the session currently knows: which pages have been
    visited, what role is active, which actions have been performed.
    """

    state_id: str = Field(default_factory=_uuid)
    run_id: str
    captured_at: datetime = Field(default_factory=_now)
    current_url: str
    auth_state: AuthState = AuthState.UNKNOWN
    active_role: str | None = None
    visited_page_ids: list[str] = Field(default_factory=list)
    performed_action_ids: list[str] = Field(default_factory=list)
    cookies: dict[str, str] = Field(default_factory=dict)
    local_storage: dict[str, str] = Field(default_factory=dict)
    session_storage: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


class Run(BaseModel):
    """
    A single mapping execution scoped to a session and a start URL.

    A Session may contain multiple Runs (e.g. one per role).
    """

    run_id: str = Field(default_factory=_uuid)
    session_id: str
    start_url: str
    role_profile_id: str | None = None
    status: RunStatus = RunStatus.PENDING
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
    page_ids: list[str] = Field(default_factory=list)
    step_count: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class Session(BaseModel):
    """
    Top-level container for a complete mapping engagement.

    A Session groups all Runs, observations, and artefacts for a single
    target application.
    """

    session_id: str = Field(default_factory=_uuid)
    target_url: str
    name: str | None = None
    status: SessionStatus = SessionStatus.PENDING
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    run_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
