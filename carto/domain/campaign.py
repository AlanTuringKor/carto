"""
Campaign models for multi-role mapping in Carto.

A Campaign groups multiple RoleProfiles under one target URL and
coordinates their execution and comparison.

Hierarchy:
    Campaign
    ├── RoleProfile (admin)  →  Run (admin's mapping run)
    ├── RoleProfile (viewer) →  Run (viewer's mapping run)
    └── RoleProfile (editor) →  Run (editor's mapping run)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from carto.domain.artifacts import RoleProfile
from carto.domain.models import AuthState, RunStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Campaign status
# ---------------------------------------------------------------------------


class CampaignStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------


class Campaign(BaseModel):
    """
    A multi-role mapping engagement against a single target.

    Groups N RoleProfiles and their corresponding Runs.
    The ``role_run_ids`` dict maps role names to run IDs for
    cross-role linking.
    """

    campaign_id: str = Field(default_factory=_uuid)
    target_url: str
    name: str | None = None
    status: CampaignStatus = CampaignStatus.PENDING
    role_profiles: list[RoleProfile] = Field(default_factory=list)
    role_run_ids: dict[str, str] = Field(default_factory=dict)  # role_name → run_id
    session_id: str | None = None  # parent session
    created_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def role_names(self) -> list[str]:
        return [rp.name for rp in self.role_profiles]


# ---------------------------------------------------------------------------
# Per-role run summary
# ---------------------------------------------------------------------------


class RoleRunSummary(BaseModel):
    """
    Compact summary of a single role's mapping run.

    Used in CampaignSummary for quick comparison.
    """

    role_name: str
    run_id: str
    status: RunStatus = RunStatus.PENDING
    step_count: int = 0
    unique_urls: int = 0
    actions_discovered: int = 0
    forms_discovered: int = 0
    auth_state: AuthState = AuthState.UNKNOWN
    error: str | None = None


# ---------------------------------------------------------------------------
# Campaign summary
# ---------------------------------------------------------------------------


class CampaignSummary(BaseModel):
    """
    Aggregate summary of a completed campaign.

    Contains per-role summaries for quick review.
    """

    campaign_id: str
    target_url: str
    status: CampaignStatus = CampaignStatus.PENDING
    role_summaries: list[RoleRunSummary] = Field(default_factory=list)
    diff_result_ids: list[str] = Field(default_factory=list)
    completed_at: datetime | None = None
