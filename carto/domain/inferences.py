"""
Inference models for Carto.

Inferences represent *LLM-generated interpretations* of observations.
Every inference records the observation that produced it, so the reasoning
chain is fully auditable and replayable.

Contrast with observations.py, which holds raw browser facts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from carto.domain.models import ActionKind, FieldKind

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Base inference
# ---------------------------------------------------------------------------


class InferenceKind(StrEnum):
    ACTION_INVENTORY = "action_inventory"
    NEXT_ACTION_DECISION = "next_action_decision"
    FORM_FILL_PLAN = "form_fill_plan"
    STATE_DELTA = "state_delta"
    RISK_SIGNAL = "risk_signal"
    PAGE_CLUSTER = "page_cluster"


class Inference(BaseModel):
    """
    Base class for all LLM-generated inferences.

    All inferences record:
    - which observation triggered them (source evidence)
    - which agent produced them
    - the model used (for auditability)
    - the raw LLM prompt/response (optional, for debugging)
    """

    inference_id: str = Field(default_factory=_uuid)
    kind: InferenceKind
    run_id: str
    source_observation_id: str
    agent_name: str
    model_name: str | None = None
    inferred_at: datetime = Field(default_factory=_now)
    confidence: float | None = None  # 0.0–1.0 when available
    raw_prompt: str | None = None    # optional — enable for debugging
    raw_response: str | None = None  # optional — enable for debugging


# ---------------------------------------------------------------------------
# Discovered action (LLM-interpreted from DOM element)
# ---------------------------------------------------------------------------


class DiscoveredAction(BaseModel):
    """
    A single action discovered and interpreted by the PageUnderstandingAgent.

    This is the agent's typed representation of a DOM interaction point.
    A DiscoveredAction maps 1-to-1 with an Action domain object after
    the orchestrator promotes it.
    """

    label: str
    kind: ActionKind
    css_selector: str | None = None
    href: str | None = None
    description: str | None = None   # LLM natural-language note
    priority: float = 0.5            # estimated exploration priority
    requires_auth: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Discovered form field (LLM-interpreted)
# ---------------------------------------------------------------------------


class DiscoveredField(BaseModel):
    """LLM interpretation of a single form field."""

    css_selector: str | None = None
    name: str | None = None
    label: str | None = None
    kind: FieldKind = FieldKind.UNKNOWN
    semantic_meaning: str | None = None   # e.g. "username", "search query"
    suggested_value: str | None = None    # Phase 2: FormFillerAgent uses this
    required: bool = False
    options: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# ActionInventory — output of PageUnderstandingAgent
# ---------------------------------------------------------------------------


class ActionInventory(Inference):
    """
    The PageUnderstandingAgent's interpretation of a page.

    Produced from a PageObservation; consumed by ActionPlannerAgent.
    """

    kind: InferenceKind = InferenceKind.ACTION_INVENTORY

    page_title: str | None = None
    page_summary: str | None = None           # LLM one-sentence summary
    page_cluster: str | None = None           # e.g. "login", "dashboard", "settings"
    auth_required: bool = False
    discovered_actions: list[DiscoveredAction] = Field(default_factory=list)
    discovered_forms: list[list[DiscoveredField]] = Field(default_factory=list)
    navigation_links: list[str] = Field(default_factory=list)  # href values
    api_endpoints_observed: list[str] = Field(default_factory=list)
    interesting_patterns: list[str] = Field(default_factory=list)  # security notes


# ---------------------------------------------------------------------------
# NextActionDecision — output of ActionPlannerAgent
# ---------------------------------------------------------------------------


class NextActionDecision(Inference):
    """
    The ActionPlannerAgent's decision on which action to execute next.

    Every field must be derivable from the ActionInventory + current State
    so that the decision is fully replayable.
    """

    kind: InferenceKind = InferenceKind.NEXT_ACTION_DECISION

    # The chosen action — must correspond to a DiscoveredAction
    chosen_action_kind: ActionKind
    chosen_css_selector: str | None = None
    chosen_href: str | None = None
    chosen_label: str | None = None

    # Reasoning (required — agents must explain their choice)
    rationale: str

    # Exploration metadata
    expected_outcome: str | None = None
    estimated_coverage_gain: float | None = None  # 0.0–1.0
    should_stop: bool = False                     # True → orchestrator terminates run
    stop_reason: str | None = None


# ---------------------------------------------------------------------------
# FormFillPlan — stub for Phase 2
# ---------------------------------------------------------------------------


class FieldFillInstruction(BaseModel):
    """A single field fill instruction from FormFillerAgent."""

    css_selector: str
    value: str
    rationale: str | None = None


class FormFillPlan(Inference):
    """
    The FormFillerAgent's plan for filling a form.

    Phase 2 implementation.  Interface defined here so the orchestrator
    can reference the type without breaking changes later.
    """

    kind: InferenceKind = InferenceKind.FORM_FILL_PLAN

    form_css_selector: str | None = None
    field_instructions: list[FieldFillInstruction] = Field(default_factory=list)
    should_submit: bool = True


# ---------------------------------------------------------------------------
# StateDelta — stub for Phase 2
# ---------------------------------------------------------------------------


class StateDelta(Inference):
    """
    The StateDiffAgent's comparison between two State snapshots.

    Phase 2 implementation.
    """

    kind: InferenceKind = InferenceKind.STATE_DELTA

    before_state_id: str
    after_state_id: str
    new_page_ids: list[str] = Field(default_factory=list)
    removed_page_ids: list[str] = Field(default_factory=list)
    auth_state_changed: bool = False
    role_changed: bool = False
    summary: str | None = None
