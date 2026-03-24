"""
Role diff models for cross-role comparison in Carto.

These models describe the typed output of comparing two ``RoleSurface``
snapshots.  Every difference is classified into a ``VisibilityCategory``
so that security reviewers can quickly identify access control issues.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from carto.domain.role_surface import RoleSurface


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------


class VisibilityCategory(StrEnum):
    """How an item differs between two roles."""

    ONLY_A = "only_a"                    # visible to role A only
    ONLY_B = "only_b"                    # visible to role B only
    SHARED = "shared"                    # both roles see this
    SHARED_DIFFERENT = "shared_different"  # both see it, but behaviour differs


# ---------------------------------------------------------------------------
# Diff entry
# ---------------------------------------------------------------------------


class DiffEntry(BaseModel):
    """A single item in a role diff."""

    item: str                            # URL, action label, endpoint, etc.
    category: VisibilityCategory
    detail: str | None = None            # optional explanation


# ---------------------------------------------------------------------------
# Role diff input
# ---------------------------------------------------------------------------


class RoleDiffInput(BaseModel):
    """Input for comparing two role surfaces."""

    role_a: RoleSurface
    role_b: RoleSurface


# ---------------------------------------------------------------------------
# Role surface delta
# ---------------------------------------------------------------------------


class RoleSurfaceDelta(BaseModel):
    """
    The actual diff between two role surfaces.

    Each list contains ``DiffEntry`` items classified by
    visibility category.
    """

    url_diff: list[DiffEntry] = Field(default_factory=list)
    action_diff: list[DiffEntry] = Field(default_factory=list)
    form_diff: list[DiffEntry] = Field(default_factory=list)
    endpoint_diff: list[DiffEntry] = Field(default_factory=list)

    # Auth boundary comparison
    auth_boundary: dict[str, Any] = Field(default_factory=dict)

    # Coverage comparison
    coverage_comparison: dict[str, Any] = Field(default_factory=dict)

    # Page cluster comparison
    cluster_diff: list[DiffEntry] = Field(default_factory=list)

    @property
    def total_differences(self) -> int:
        return (
            len([d for d in self.url_diff if d.category != VisibilityCategory.SHARED])
            + len([d for d in self.action_diff if d.category != VisibilityCategory.SHARED])
            + len([d for d in self.form_diff if d.category != VisibilityCategory.SHARED])
            + len([d for d in self.endpoint_diff if d.category != VisibilityCategory.SHARED])
            + len([d for d in self.cluster_diff if d.category != VisibilityCategory.SHARED])
        )


# ---------------------------------------------------------------------------
# Role diff result
# ---------------------------------------------------------------------------


class RoleDiffResult(BaseModel):
    """
    Complete result of comparing two role surfaces.

    Wraps the delta with campaign-level metadata.
    """

    result_id: str = Field(default_factory=_uuid)
    campaign_id: str
    role_a_name: str
    role_b_name: str
    delta: RoleSurfaceDelta
    summary: str | None = None
    computed_at: datetime = Field(default_factory=_now)
