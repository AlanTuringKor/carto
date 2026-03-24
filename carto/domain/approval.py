"""
Approval gate models for Carto.

Provides typed request/result models and a policy protocol for
controlling whether sensitive actions require human approval before
the executor is allowed to perform them.

Design:
    - ``ApprovalPolicy`` is a protocol — implementations range from
      "auto-approve everything" to interactive CLI prompts to future
      web-based approval UIs.
    - The orchestrator calls ``requires_approval()`` before every
      command.  If it returns a reason, an ``ApprovalRequest`` is
      created and ``request_approval()`` is called.
    - ``ApprovalResult`` records the decision and who made it.
"""

from __future__ import annotations

import sys
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
# Enums
# ---------------------------------------------------------------------------


class ApprovalReason(StrEnum):
    """Why an action requires approval."""

    DESTRUCTIVE_ACTION = "destructive_action"
    LOGOUT_ACTION = "logout_action"
    CREDENTIAL_SUBMISSION = "credential_submission"
    MFA_STEP = "mfa_step"
    OAUTH_CONSENT = "oauth_consent"
    DANGEROUS_FORM_SUBMIT = "dangerous_form_submit"
    CUSTOM = "custom"


class ApprovalDecision(StrEnum):
    """The outcome of an approval request."""

    APPROVED = "approved"
    DENIED = "denied"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Request / Result models
# ---------------------------------------------------------------------------


class ApprovalRequest(BaseModel):
    """
    A typed request for human approval before executing an action.

    Created by the orchestrator when ``ApprovalPolicy.requires_approval``
    returns a reason.
    """

    request_id: str = Field(default_factory=_uuid)
    run_id: str
    step: int | None = None
    reason: ApprovalReason
    action_label: str | None = None
    action_kind: str | None = None
    css_selector: str | None = None
    target_url: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    requested_at: datetime = Field(default_factory=_now)


class ApprovalResult(BaseModel):
    """
    The outcome of an approval request.

    Records who made the decision and why.
    """

    request_id: str
    decision: ApprovalDecision
    decided_by: str = "unknown"  # "human", "policy", "auto"
    rationale: str | None = None
    decided_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Policy protocol
# ---------------------------------------------------------------------------


class ApprovalPolicy:
    """
    Base class / protocol for approval policies.

    Subclass and override ``requires_approval`` and ``request_approval``
    to implement custom approval logic.
    """

    def requires_approval(
        self,
        action_kind: str,
        action_label: str | None,
        is_login_form: bool = False,
        is_logout_action: bool = False,
        is_credential_submission: bool = False,
        **kwargs: object,
    ) -> ApprovalReason | None:
        """
        Check whether an action requires approval.

        Returns an ``ApprovalReason`` if approval is required,
        or ``None`` if the action can proceed.
        """
        return None

    def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        """
        Request approval for an action.

        Blocks until a decision is made.
        """
        return ApprovalResult(
            request_id=request.request_id,
            decision=ApprovalDecision.APPROVED,
            decided_by="auto",
        )


# ---------------------------------------------------------------------------
# AutoApprovePolicy — approves everything
# ---------------------------------------------------------------------------


class AutoApprovePolicy(ApprovalPolicy):
    """
    Approves all actions without prompting.

    Use for non-interactive / automated runs where human gates
    are not desired.
    """

    def requires_approval(self, **kwargs: object) -> ApprovalReason | None:
        return None

    def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        return ApprovalResult(
            request_id=request.request_id,
            decision=ApprovalDecision.APPROVED,
            decided_by="auto",
            rationale="Auto-approve policy: all actions approved.",
        )


# ---------------------------------------------------------------------------
# InteractiveApprovalPolicy — flags sensitive actions for approval
# ---------------------------------------------------------------------------


class InteractiveApprovalPolicy(ApprovalPolicy):
    """
    Flags sensitive actions and prompts for approval.

    Sensitive actions:
    - Logout actions
    - Credential submissions (login forms)
    - MFA-related steps
    - OAuth consent / redirect flows
    - Dangerous form submits (DELETE, destructive labels)
    """

    _DESTRUCTIVE_LABELS = frozenset({
        "delete", "remove", "destroy", "purge", "reset",
        "revoke", "terminate", "cancel", "drop",
    })

    def requires_approval(
        self,
        action_kind: str = "",
        action_label: str | None = None,
        is_login_form: bool = False,
        is_logout_action: bool = False,
        is_credential_submission: bool = False,
        **kwargs: object,
    ) -> ApprovalReason | None:
        if is_logout_action:
            return ApprovalReason.LOGOUT_ACTION
        if is_credential_submission:
            return ApprovalReason.CREDENTIAL_SUBMISSION
        if action_label:
            lower = action_label.lower()
            if any(d in lower for d in self._DESTRUCTIVE_LABELS):
                return ApprovalReason.DESTRUCTIVE_ACTION
            if "mfa" in lower or "2fa" in lower or "two-factor" in lower:
                return ApprovalReason.MFA_STEP
            if "oauth" in lower or "consent" in lower or "authorize" in lower:
                return ApprovalReason.OAUTH_CONSENT
        return None


# ---------------------------------------------------------------------------
# CLIApprovalPolicy — prompts on stdin
# ---------------------------------------------------------------------------


class CLIApprovalPolicy(InteractiveApprovalPolicy):
    """
    Interactive CLI approval gate.

    Prints the action summary to stderr and reads y/n from stdin.
    """

    def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        print(
            f"\n{'='*60}\n"
            f"⚠  APPROVAL REQUIRED\n"
            f"  Reason:  {request.reason}\n"
            f"  Action:  {request.action_label or '(unknown)'}\n"
            f"  Kind:    {request.action_kind or '(unknown)'}\n"
            f"  Step:    {request.step}\n"
            f"  Run:     {request.run_id}\n"
            f"{'='*60}",
            file=sys.stderr,
        )

        try:
            answer = input("  Approve? [y/N] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"

        if answer in ("y", "yes"):
            return ApprovalResult(
                request_id=request.request_id,
                decision=ApprovalDecision.APPROVED,
                decided_by="human",
                rationale="Approved via CLI prompt.",
            )
        else:
            return ApprovalResult(
                request_id=request.request_id,
                decision=ApprovalDecision.DENIED,
                decided_by="human",
                rationale=f"Denied via CLI prompt (answer: {answer!r}).",
            )
