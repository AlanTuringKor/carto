"""
Observation models for Carto.

Observations represent *facts actually seen* by the browser executor.
They contain no LLM-generated content.  Every field must be directly
derivable from raw browser data.

Contrast with inferences.py, which holds LLM-generated interpretations.
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
# Network observations
# ---------------------------------------------------------------------------


class NetworkRequest(BaseModel):
    """An outgoing HTTP request captured during a browser action."""

    request_id: str = Field(default_factory=_uuid)
    observation_id: str  # foreign key → PageObservation
    url: str
    method: str
    headers: dict[str, str] = Field(default_factory=dict)
    post_data: str | None = None
    resource_type: str | None = None  # e.g. "document", "xhr", "fetch"
    timestamp: datetime = Field(default_factory=_now)


class NetworkResponse(BaseModel):
    """An HTTP response captured during a browser action."""

    response_id: str = Field(default_factory=_uuid)
    request_id: str  # foreign key → NetworkRequest
    observation_id: str  # foreign key → PageObservation
    url: str
    status: int
    headers: dict[str, str] = Field(default_factory=dict)
    body_preview: str | None = None  # first N bytes only — do not store full bodies
    timestamp: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Base observation
# ---------------------------------------------------------------------------


class ObservationKind(StrEnum):
    PAGE = "page"
    ERROR = "error"
    REDIRECT = "redirect"


class Observation(BaseModel):
    """
    Base class for all observations.

    Every observation is tied to a run and records the action that triggered
    it (if any).  Subclasses add domain-specific fields.
    """

    observation_id: str = Field(default_factory=_uuid)
    kind: ObservationKind
    run_id: str
    triggering_action_id: str | None = None  # None for the initial navigation
    observed_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# DOM / page element snapshots
# ---------------------------------------------------------------------------


class ElementSnapshot(BaseModel):
    """A lightweight representation of a DOM element."""

    tag: str
    text: str | None = None
    css_selector: str | None = None
    href: str | None = None
    aria_label: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)


class FormSnapshot(BaseModel):
    """A raw DOM form snapshot before field-level parsing."""

    action: str | None = None
    method: str = "get"
    fields_raw: list[dict[str, Any]] = Field(default_factory=list)
    raw_html: str | None = None


# ---------------------------------------------------------------------------
# PageObservation — the primary observation produced by BrowserExecutor
# ---------------------------------------------------------------------------


class PageObservation(Observation):
    """
    A full snapshot of a page after navigation or interaction.

    This is the primary input to the PageUnderstandingAgent.

    Fields are raw browser facts only:
    - DOM content / accessible text
    - URL (final, after redirects)
    - Screenshot path (on-disk artefact)
    - Network traffic captured since the last action
    - Interactive elements found in the DOM
    """

    kind: ObservationKind = ObservationKind.PAGE

    # Page identity
    url: str
    final_url: str  # after redirects — may differ from requested URL
    title: str | None = None
    status_code: int | None = None

    # DOM content
    html_content: str | None = None          # full page HTML (may be large)
    accessible_text: str | None = None       # extracted readable text
    interactive_elements: list[ElementSnapshot] = Field(default_factory=list)
    forms_raw: list[FormSnapshot] = Field(default_factory=list)

    # Artefacts
    screenshot_path: str | None = None       # path to saved screenshot

    # Network (captured since previous action)
    requests: list[NetworkRequest] = Field(default_factory=list)
    responses: list[NetworkResponse] = Field(default_factory=list)

    # Browser state
    cookies: dict[str, str] = Field(default_factory=dict)
    local_storage: dict[str, str] = Field(default_factory=dict)
    session_storage: dict[str, str] = Field(default_factory=dict)

    # Error reporting
    load_error: str | None = None


# ---------------------------------------------------------------------------
# Error observation
# ---------------------------------------------------------------------------


class ErrorObservation(Observation):
    """Recorded when an executor action raises an unrecoverable error."""

    kind: ObservationKind = ObservationKind.ERROR
    error_type: str
    message: str
    traceback: str | None = None
