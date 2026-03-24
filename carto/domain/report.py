"""
Report domain models for Carto.

Structured, composable report types that can be assembled from
campaign outputs and rendered to Markdown, JSON, or HTML.
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
# Report section kinds
# ---------------------------------------------------------------------------


class ReportSectionKind(StrEnum):
    EXECUTIVE_SUMMARY = "executive_summary"
    CAMPAIGN_OVERVIEW = "campaign_overview"
    ROLE_SUMMARY = "role_summary"
    ROLE_MATRIX = "role_matrix"
    ROLE_DIFF = "role_diff"
    AUTH_SURFACE = "auth_surface"
    COVERAGE = "coverage"
    HOTSPOTS = "hotspots"
    LIMITATIONS = "limitations"
    LLM_NARRATIVE = "llm_narrative"


# ---------------------------------------------------------------------------
# Report section
# ---------------------------------------------------------------------------


class ReportSection(BaseModel):
    """
    A single section of a campaign report.

    Recursive: sections can contain subsections for nested structure.
    ``evidence_refs`` links to source IDs (run_id, event_id, etc.)
    for traceability.
    """

    title: str
    kind: ReportSectionKind
    content: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    subsections: list[ReportSection] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Campaign report
# ---------------------------------------------------------------------------


class CampaignReport(BaseModel):
    """
    Top-level report for a completed campaign.

    Contains ordered sections assembled from campaign outputs.
    """

    report_id: str = Field(default_factory=_uuid)
    campaign_id: str
    target_url: str
    role_names: list[str] = Field(default_factory=list)
    sections: list[ReportSection] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def section_count(self) -> int:
        return len(self.sections)
