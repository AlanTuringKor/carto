"""Tests for Campaign, RoleRunSummary, CampaignSummary models."""

from carto.domain.artifacts import RoleProfile
from carto.domain.campaign import (
    Campaign,
    CampaignStatus,
    CampaignSummary,
    RoleRunSummary,
)
from carto.domain.models import AuthState, RunStatus


class TestCampaign:
    def test_basic_construction(self):
        c = Campaign(target_url="https://example.com")
        assert c.campaign_id
        assert c.target_url == "https://example.com"
        assert c.status == CampaignStatus.PENDING
        assert c.role_profiles == []
        assert c.role_run_ids == {}

    def test_with_roles(self):
        roles = [
            RoleProfile(session_id="s1", name="admin", username="admin@test.com"),
            RoleProfile(session_id="s1", name="viewer", username="viewer@test.com"),
        ]
        c = Campaign(
            target_url="https://example.com",
            name="test-campaign",
            role_profiles=roles,
        )
        assert len(c.role_profiles) == 2
        assert c.role_names == ["admin", "viewer"]

    def test_role_run_ids(self):
        c = Campaign(
            target_url="https://example.com",
            role_run_ids={"admin": "run-1", "viewer": "run-2"},
        )
        assert c.role_run_ids["admin"] == "run-1"

    def test_status_transitions(self):
        c = Campaign(target_url="https://example.com")
        assert c.status == CampaignStatus.PENDING
        c2 = c.model_copy(update={"status": CampaignStatus.RUNNING})
        assert c2.status == CampaignStatus.RUNNING
        c3 = c2.model_copy(update={"status": CampaignStatus.COMPLETED})
        assert c3.status == CampaignStatus.COMPLETED


class TestRoleRunSummary:
    def test_basic(self):
        s = RoleRunSummary(role_name="admin", run_id="r1")
        assert s.status == RunStatus.PENDING
        assert s.unique_urls == 0

    def test_completed(self):
        s = RoleRunSummary(
            role_name="admin",
            run_id="r1",
            status=RunStatus.COMPLETED,
            step_count=25,
            unique_urls=10,
            actions_discovered=15,
            forms_discovered=3,
            auth_state=AuthState.AUTHENTICATED,
        )
        assert s.step_count == 25


class TestCampaignSummary:
    def test_basic(self):
        cs = CampaignSummary(
            campaign_id="c1",
            target_url="https://example.com",
        )
        assert cs.role_summaries == []
        assert cs.diff_result_ids == []

    def test_with_roles(self):
        cs = CampaignSummary(
            campaign_id="c1",
            target_url="https://example.com",
            status=CampaignStatus.COMPLETED,
            role_summaries=[
                RoleRunSummary(role_name="admin", run_id="r1", unique_urls=10),
                RoleRunSummary(role_name="viewer", run_id="r2", unique_urls=5),
            ],
            diff_result_ids=["diff-1"],
        )
        assert len(cs.role_summaries) == 2
        assert cs.role_summaries[0].unique_urls == 10
