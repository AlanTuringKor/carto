"""
Role surface snapshot for Carto.

A ``RoleSurface`` captures what a single role can see during its
mapping run — the set of URLs, actions, forms, endpoints, and
page clusters discovered.  This is the input for cross-role
comparison via ``RoleDiffer``.

Built from ``ActionInventory`` outputs and ``PageObservation`` data,
not from the LLM — this is a deterministic aggregation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from carto.domain.models import AuthState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# RoleSurface
# ---------------------------------------------------------------------------


class RoleSurface(BaseModel):
    """
    Snapshot of what a single role can see and do.

    Collected during or after a mapping run. Used as input
    for cross-role diffing.
    """

    surface_id: str = Field(default_factory=_uuid)
    role_name: str
    run_id: str

    # Discovery sets
    urls: set[str] = Field(default_factory=set)
    action_labels: set[str] = Field(default_factory=set)
    form_urls: set[str] = Field(default_factory=set)
    api_endpoints: set[str] = Field(default_factory=set)
    page_clusters: set[str] = Field(default_factory=set)

    # Auth posture
    auth_state: AuthState = AuthState.UNKNOWN

    # Counts
    risk_signal_count: int = 0
    step_count: int = 0

    # Metadata
    captured_at: datetime = Field(default_factory=_now)
