"""
Structured event models for Carto's audit trail.

Every significant action in a mapping run produces a typed ``Event``
that is recorded in the ``EventLog``.  Events form an immutable,
replay-friendly audit trail.

Design:
    - ``EventKind`` enum classifies events
    - ``Event`` is the base model — every event has a kind, run_id,
      step index, and a typed ``data`` payload
    - Factory functions produce properly typed events at each call site
    - Auth-sensitive fields are redacted before event emission
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from carto.domain.auth import RedactedValue
from carto.utils.redaction import is_sensitive_key

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Event kinds
# ---------------------------------------------------------------------------


class EventKind(StrEnum):
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    STEP_STARTED = "step_started"
    PAGE_OBSERVED = "page_observed"
    INFERENCE_PRODUCED = "inference_produced"
    DECISION_MADE = "decision_made"
    COMMAND_ISSUED = "command_issued"
    COMMAND_RESULT = "command_result"
    FORM_FILL_PLANNED = "form_fill_planned"
    STATE_DIFF_COMPUTED = "state_diff_computed"
    AUTH_TRANSITION = "auth_transition"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------


class Event(BaseModel):
    """
    A single audit-trail event.

    Immutable once created.  Contains a ``data`` dict with event-specific
    fields — always redaction-safe.
    """

    event_id: str = Field(default_factory=_uuid)
    kind: EventKind
    run_id: str
    session_id: str | None = None
    step: int | None = None
    timestamp: datetime = Field(default_factory=_now)
    data: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Redaction helper for event data
# ---------------------------------------------------------------------------


def _redact_data(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact sensitive values in event data."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, RedactedValue):
            result[key] = str(value)
        elif isinstance(value, dict):
            result[key] = _redact_data(value)
        elif isinstance(value, str) and is_sensitive_key(key):
            result[key] = str(RedactedValue.from_raw(value))
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Factory functions — typed event constructors
# ---------------------------------------------------------------------------


def run_started_event(
    run_id: str,
    session_id: str,
    start_url: str,
) -> Event:
    return Event(
        kind=EventKind.RUN_STARTED,
        run_id=run_id,
        session_id=session_id,
        step=0,
        data={"start_url": start_url},
    )


def run_completed_event(
    run_id: str,
    session_id: str,
    status: str,
    step_count: int,
    error: str | None = None,
) -> Event:
    return Event(
        kind=EventKind.RUN_COMPLETED,
        run_id=run_id,
        session_id=session_id,
        step=step_count,
        data={"status": status, "step_count": step_count, "error": error},
    )


def step_started_event(
    run_id: str,
    step: int,
    url: str,
) -> Event:
    return Event(
        kind=EventKind.STEP_STARTED,
        run_id=run_id,
        step=step,
        data={"url": url},
    )


def page_observed_event(
    run_id: str,
    step: int,
    observation_id: str,
    url: str,
    title: str | None,
    status_code: int | None,
    element_count: int,
    form_count: int,
    cookies: dict[str, str] | None = None,
) -> Event:
    data: dict[str, Any] = {
        "observation_id": observation_id,
        "url": url,
        "title": title,
        "status_code": status_code,
        "element_count": element_count,
        "form_count": form_count,
    }
    if cookies:
        data["cookie_names"] = list(cookies.keys())
    return Event(
        kind=EventKind.PAGE_OBSERVED,
        run_id=run_id,
        step=step,
        data=data,
    )


def inference_produced_event(
    run_id: str,
    step: int,
    inference_kind: str,
    agent_name: str,
    inference_id: str,
    summary: dict[str, Any] | None = None,
) -> Event:
    data: dict[str, Any] = {
        "inference_kind": inference_kind,
        "agent_name": agent_name,
        "inference_id": inference_id,
    }
    if summary:
        data["summary"] = _redact_data(summary)
    return Event(
        kind=EventKind.INFERENCE_PRODUCED,
        run_id=run_id,
        step=step,
        data=data,
    )


def decision_made_event(
    run_id: str,
    step: int,
    action_kind: str,
    action_label: str | None,
    rationale: str,
    should_stop: bool = False,
) -> Event:
    return Event(
        kind=EventKind.DECISION_MADE,
        run_id=run_id,
        step=step,
        data={
            "action_kind": action_kind,
            "action_label": action_label,
            "rationale": rationale,
            "should_stop": should_stop,
        },
    )


def command_issued_event(
    run_id: str,
    step: int,
    command_kind: str,
    command_id: str,
    target: str | None = None,
) -> Event:
    return Event(
        kind=EventKind.COMMAND_ISSUED,
        run_id=run_id,
        step=step,
        data={
            "command_kind": command_kind,
            "command_id": command_id,
            "target": target,
        },
    )


def command_result_event(
    run_id: str,
    step: int,
    command_id: str,
    success: bool,
    result_url: str | None = None,
    error: str | None = None,
) -> Event:
    return Event(
        kind=EventKind.COMMAND_RESULT,
        run_id=run_id,
        step=step,
        data={
            "command_id": command_id,
            "success": success,
            "result_url": result_url,
            "error": error,
        },
    )


def form_fill_planned_event(
    run_id: str,
    step: int,
    field_count: int,
    is_login_form: bool,
    should_submit: bool,
) -> Event:
    return Event(
        kind=EventKind.FORM_FILL_PLANNED,
        run_id=run_id,
        step=step,
        data={
            "field_count": field_count,
            "is_login_form": is_login_form,
            "should_submit": should_submit,
        },
    )


def state_diff_computed_event(
    run_id: str,
    step: int,
    auth_state_changed: bool,
    login_detected: bool,
    logout_detected: bool,
    summary: str | None,
) -> Event:
    return Event(
        kind=EventKind.STATE_DIFF_COMPUTED,
        run_id=run_id,
        step=step,
        data={
            "auth_state_changed": auth_state_changed,
            "login_detected": login_detected,
            "logout_detected": logout_detected,
            "summary": summary,
        },
    )


def auth_transition_event(
    run_id: str,
    step: int,
    before_authenticated: bool,
    after_authenticated: bool,
    trigger: str | None,
) -> Event:
    return Event(
        kind=EventKind.AUTH_TRANSITION,
        run_id=run_id,
        step=step,
        data={
            "before_authenticated": before_authenticated,
            "after_authenticated": after_authenticated,
            "trigger": trigger,
        },
    )


def approval_requested_event(
    run_id: str,
    step: int,
    request_id: str,
    reason: str,
    action_label: str | None,
) -> Event:
    return Event(
        kind=EventKind.APPROVAL_REQUESTED,
        run_id=run_id,
        step=step,
        data={
            "request_id": request_id,
            "reason": reason,
            "action_label": action_label,
        },
    )


def approval_resolved_event(
    run_id: str,
    step: int,
    request_id: str,
    decision: str,
    decided_by: str,
) -> Event:
    return Event(
        kind=EventKind.APPROVAL_RESOLVED,
        run_id=run_id,
        step=step,
        data={
            "request_id": request_id,
            "decision": decision,
            "decided_by": decided_by,
        },
    )


def error_event(
    run_id: str,
    step: int | None,
    error_type: str,
    message: str,
) -> Event:
    return Event(
        kind=EventKind.ERROR,
        run_id=run_id,
        step=step,
        data={"error_type": error_type, "message": message},
    )
