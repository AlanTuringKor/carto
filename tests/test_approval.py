"""Tests for approval gate models and policies."""

from carto.domain.approval import (
    ApprovalDecision,
    ApprovalPolicy,
    ApprovalReason,
    ApprovalRequest,
    ApprovalResult,
    AutoApprovePolicy,
    CLIApprovalPolicy,
    InteractiveApprovalPolicy,
)


class TestApprovalModels:
    def test_request_has_id(self):
        req = ApprovalRequest(run_id="r1", reason=ApprovalReason.DESTRUCTIVE_ACTION)
        assert req.request_id
        assert req.reason == ApprovalReason.DESTRUCTIVE_ACTION

    def test_result(self):
        result = ApprovalResult(
            request_id="req1",
            decision=ApprovalDecision.APPROVED,
            decided_by="human",
        )
        assert result.decision == ApprovalDecision.APPROVED


class TestAutoApprovePolicy:
    def test_never_requires_approval(self):
        policy = AutoApprovePolicy()
        assert policy.requires_approval() is None

    def test_always_approves(self):
        policy = AutoApprovePolicy()
        req = ApprovalRequest(run_id="r1", reason=ApprovalReason.DESTRUCTIVE_ACTION)
        result = policy.request_approval(req)
        assert result.decision == ApprovalDecision.APPROVED
        assert result.decided_by == "auto"


class TestInteractiveApprovalPolicy:
    def test_flags_destructive_action(self):
        policy = InteractiveApprovalPolicy()
        reason = policy.requires_approval(
            action_kind="click", action_label="Delete Account",
        )
        assert reason == ApprovalReason.DESTRUCTIVE_ACTION

    def test_flags_logout(self):
        policy = InteractiveApprovalPolicy()
        reason = policy.requires_approval(
            action_kind="click", is_logout_action=True,
        )
        assert reason == ApprovalReason.LOGOUT_ACTION

    def test_flags_credential_submission(self):
        policy = InteractiveApprovalPolicy()
        reason = policy.requires_approval(
            action_kind="submit", is_credential_submission=True,
        )
        assert reason == ApprovalReason.CREDENTIAL_SUBMISSION

    def test_flags_mfa(self):
        policy = InteractiveApprovalPolicy()
        reason = policy.requires_approval(
            action_kind="click", action_label="Enter MFA Code",
        )
        assert reason == ApprovalReason.MFA_STEP

    def test_flags_oauth(self):
        policy = InteractiveApprovalPolicy()
        reason = policy.requires_approval(
            action_kind="click", action_label="Authorize Application",
        )
        assert reason == ApprovalReason.OAUTH_CONSENT

    def test_no_approval_for_safe_action(self):
        policy = InteractiveApprovalPolicy()
        reason = policy.requires_approval(
            action_kind="click", action_label="View Profile",
        )
        assert reason is None


class TestCLIApprovalPolicy:
    def test_inherits_interactive_detection(self):
        policy = CLIApprovalPolicy()
        reason = policy.requires_approval(
            action_kind="click", action_label="Remove User",
        )
        assert reason == ApprovalReason.DESTRUCTIVE_ACTION

    def test_denial_on_non_yes(self, monkeypatch):
        policy = CLIApprovalPolicy()
        req = ApprovalRequest(run_id="r1", reason=ApprovalReason.DESTRUCTIVE_ACTION)
        monkeypatch.setattr("builtins.input", lambda _: "n")
        result = policy.request_approval(req)
        assert result.decision == ApprovalDecision.DENIED
        assert result.decided_by == "human"

    def test_approval_on_yes(self, monkeypatch):
        policy = CLIApprovalPolicy()
        req = ApprovalRequest(run_id="r1", reason=ApprovalReason.DESTRUCTIVE_ACTION)
        monkeypatch.setattr("builtins.input", lambda _: "y")
        result = policy.request_approval(req)
        assert result.decision == ApprovalDecision.APPROVED
        assert result.decided_by == "human"

    def test_denial_on_eof(self, monkeypatch):
        policy = CLIApprovalPolicy()
        req = ApprovalRequest(run_id="r1", reason=ApprovalReason.DESTRUCTIVE_ACTION)
        monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError))
        result = policy.request_approval(req)
        assert result.decision == ApprovalDecision.DENIED
