"""
Risk assessment domain models for Carto.

Defines the input and output types for the RiskAgent:
- ``RiskInput``: evidence bundle consumed by the agent
- ``RiskAssessment``: inference containing structured risk signals
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from carto.domain.artifacts import RiskSeverity, RiskSignal
from carto.domain.auth import AuthContext
from carto.domain.inferences import ActionInventory, Inference, InferenceKind, StateDelta


# ---------------------------------------------------------------------------
# RiskInput — what the RiskAgent receives
# ---------------------------------------------------------------------------


class RiskInput(BaseModel):
    """
    Evidence bundle for the RiskAgent.

    Aggregates observations, inferences, and auth context so the agent
    can assess risk from a single input object.
    """

    inventory: ActionInventory
    state_delta: StateDelta | None = None
    auth_context: AuthContext | None = None
    page_url: str
    page_cluster: str | None = None
    security_observations: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# RiskAssessment — what the RiskAgent produces
# ---------------------------------------------------------------------------


class RiskAssessment(Inference):
    """
    The RiskAgent's analysis of a page/step.

    Contains a list of ``RiskSignal`` findings, each backed by evidence
    and mapped to a CWE where applicable.

    Never contains confirmed vulnerability assertions — only
    evidence-backed observations and potential risk indicators.
    """

    kind: InferenceKind = InferenceKind.RISK_SIGNAL

    signals: list[RiskSignal] = Field(default_factory=list)
    summary: str | None = None
    highest_severity: RiskSeverity = RiskSeverity.INFO
