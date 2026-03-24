"""
Diff narrative models for LLM-enhanced role comparison.

These models capture interpretive analysis produced by the
``DiffNarrativeAgent``.  Unlike deterministic diff outputs,
narrative content is explicitly marked as LLM-generated
interpretation and must be treated accordingly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Insight severity
# ---------------------------------------------------------------------------


class InsightSeverity(StrEnum):
    """How significant an LLM-generated insight is."""

    INFO = "info"
    NOTABLE = "notable"
    SIGNIFICANT = "significant"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Report insight
# ---------------------------------------------------------------------------


class ReportInsight(BaseModel):
    """
    A single LLM-generated insight about a role diff.

    Always evidence-backed: ``evidence_refs`` links to deterministic
    diff entries or risk signals that support the interpretation.
    """

    title: str
    body: str
    severity: InsightSeverity = InsightSeverity.INFO
    confidence: float = 0.5  # 0.0–1.0
    evidence_refs: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Diff narrative
# ---------------------------------------------------------------------------


class DiffNarrative(BaseModel):
    """
    LLM-generated narrative enriching a deterministic role diff.

    Clearly marked as interpretive analysis — NOT confirmed findings.
    """

    narrative_id: str = Field(default_factory=_uuid)
    role_a_name: str
    role_b_name: str
    executive_summary: str = ""
    insights: list[ReportInsight] = Field(default_factory=list)
    agent_name: str = "diff_narrative_agent"
    model_name: str = ""
    generated_at: datetime = Field(default_factory=_now)

    @property
    def insight_count(self) -> int:
        return len(self.insights)
