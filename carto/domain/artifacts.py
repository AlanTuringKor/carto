"""
Artefact and coverage models for Carto.

These models represent durable outputs of a mapping run that are stored
for review, replay, and reporting.
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
# Artifact
# ---------------------------------------------------------------------------


class ArtifactKind(StrEnum):
    SCREENSHOT = "screenshot"
    HAR = "har"             # HTTP Archive format
    DOM_SNAPSHOT = "dom_snapshot"
    SESSION_EXPORT = "session_export"
    REPORT = "report"
    CUSTOM = "custom"


class Artifact(BaseModel):
    """
    A durable file produced during a mapping run.

    Artefacts are stored on disk and referenced by path.  They are
    immutable once created.
    """

    artifact_id: str = Field(default_factory=_uuid)
    run_id: str
    kind: ArtifactKind
    path: str                         # absolute on-disk path
    content_type: str | None = None   # MIME type
    created_at: datetime = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# RoleProfile
# ---------------------------------------------------------------------------


class RoleProfile(BaseModel):
    """
    Credentials and context for a specific user role.

    A Session may define multiple RoleProfiles to map authenticated
    areas visible to different roles.
    """

    role_profile_id: str = Field(default_factory=_uuid)
    session_id: str
    name: str                          # e.g. "admin", "viewer", "editor"
    username: str | None = None
    password: str | None = None        # NOTE: store in vault in production
    extra_headers: dict[str, str] = Field(default_factory=dict)
    cookies: dict[str, str] = Field(default_factory=dict)
    setup_script: str | None = None    # optional Python/JS to run before crawl
    description: str | None = None


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


class PageCoverageEntry(BaseModel):
    """Coverage record for a single page."""

    page_id: str
    url: str
    visit_count: int = 0
    action_count: int = 0
    form_count: int = 0
    last_visited: datetime | None = None


class Coverage(BaseModel):
    """
    Aggregate coverage record for a run.

    Updated incrementally as the orchestrator progresses.
    """

    coverage_id: str = Field(default_factory=_uuid)
    run_id: str
    pages: list[PageCoverageEntry] = Field(default_factory=list)
    total_actions_taken: int = 0
    total_forms_submitted: int = 0
    unique_urls_visited: int = 0
    computed_at: datetime = Field(default_factory=_now)

    @property
    def page_count(self) -> int:
        return len(self.pages)


# ---------------------------------------------------------------------------
# RiskSignal — stub, Phase 2
# ---------------------------------------------------------------------------


class RiskSeverity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskSignal(BaseModel):
    """
    A potential security finding flagged by the RiskAgent.

    Phase 2 implementation.  The model is defined here so other components
    can reference the type without changes later.
    """

    signal_id: str = Field(default_factory=_uuid)
    run_id: str
    page_id: str | None = None
    action_id: str | None = None
    inference_id: str | None = None
    severity: RiskSeverity = RiskSeverity.INFO
    title: str
    description: str
    evidence: str | None = None
    cwe: str | None = None              # e.g. "CWE-79"
    cvss_score: float | None = None
    flagged_at: datetime = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
