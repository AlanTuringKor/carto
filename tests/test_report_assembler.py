"""Tests for ReportAssembler."""

from carto.analysis.report_assembler import ReportAssembler
from carto.domain.campaign import CampaignStatus, CampaignSummary, RoleRunSummary
from carto.domain.diff_narrative import DiffNarrative, InsightSeverity, ReportInsight
from carto.domain.models import AuthState, RunStatus
from carto.domain.report import ReportSectionKind
from carto.domain.role_diff import (
    DiffEntry,
    RoleDiffResult,
    RoleSurfaceDelta,
    VisibilityCategory,
)
from carto.domain.role_surface import RoleSurface


def _make_summary() -> CampaignSummary:
    return CampaignSummary(
        campaign_id="c1",
        target_url="https://example.com",
        status=CampaignStatus.COMPLETED,
        role_summaries=[
            RoleRunSummary(
                role_name="admin", run_id="r1",
                status=RunStatus.COMPLETED, step_count=20,
                unique_urls=10, actions_discovered=15,
                forms_discovered=3, auth_state=AuthState.AUTHENTICATED,
            ),
            RoleRunSummary(
                role_name="viewer", run_id="r2",
                status=RunStatus.COMPLETED, step_count=15,
                unique_urls=5, actions_discovered=8,
                forms_discovered=1, auth_state=AuthState.AUTHENTICATED,
            ),
        ],
    )


def _make_surfaces() -> dict[str, RoleSurface]:
    return {
        "admin": RoleSurface(
            role_name="admin", run_id="r1",
            urls={"https://example.com", "https://example.com/admin", "https://example.com/settings"},
            action_labels={"Dashboard", "Users", "Settings"},
            form_urls={"https://example.com/login", "https://example.com/admin/create"},
            auth_state=AuthState.AUTHENTICATED,
        ),
        "viewer": RoleSurface(
            role_name="viewer", run_id="r2",
            urls={"https://example.com", "https://example.com/dashboard"},
            action_labels={"Dashboard", "Profile"},
            form_urls={"https://example.com/login"},
            auth_state=AuthState.AUTHENTICATED,
        ),
    }


def _make_diffs() -> list[RoleDiffResult]:
    return [RoleDiffResult(
        campaign_id="c1",
        role_a_name="admin",
        role_b_name="viewer",
        delta=RoleSurfaceDelta(
            url_diff=[
                DiffEntry(item="https://example.com", category=VisibilityCategory.SHARED),
                DiffEntry(item="https://example.com/admin", category=VisibilityCategory.ONLY_A),
                DiffEntry(item="https://example.com/settings", category=VisibilityCategory.ONLY_A),
                DiffEntry(item="https://example.com/dashboard", category=VisibilityCategory.ONLY_B),
            ],
            action_diff=[
                DiffEntry(item="Dashboard", category=VisibilityCategory.SHARED),
                DiffEntry(item="Users", category=VisibilityCategory.ONLY_A),
                DiffEntry(item="Settings", category=VisibilityCategory.ONLY_A),
                DiffEntry(item="Profile", category=VisibilityCategory.ONLY_B),
            ],
            auth_boundary={"role_a_auth": "authenticated", "role_b_auth": "authenticated", "auth_states_match": "True"},
            coverage_comparison={"role_a_urls": 3, "role_b_urls": 2},
        ),
    )]


class TestReportAssembler:
    def test_basic_assembly(self):
        assembler = ReportAssembler()
        report = assembler.assemble(
            _make_summary(), _make_surfaces(), _make_diffs(),
        )
        assert report.campaign_id == "c1"
        assert report.target_url == "https://example.com"
        assert report.role_names == ["admin", "viewer"]
        # Should have: exec summary, overview, roles, matrix, diffs,
        # auth, coverage, limitations = 8 sections
        assert report.section_count == 8

    def test_executive_summary_content(self):
        report = ReportAssembler().assemble(
            _make_summary(), _make_surfaces(), _make_diffs(),
        )
        exec_section = report.sections[0]
        assert exec_section.kind == ReportSectionKind.EXECUTIVE_SUMMARY
        assert "2" in exec_section.content  # 2 roles
        assert "example.com" in exec_section.content

    def test_role_matrix(self):
        report = ReportAssembler().assemble(
            _make_summary(), _make_surfaces(), _make_diffs(),
        )
        matrix = [s for s in report.sections if s.kind == ReportSectionKind.ROLE_MATRIX][0]
        assert "admin" in matrix.content
        assert "viewer" in matrix.content
        assert "✓" in matrix.content
        assert "✗" in matrix.content

    def test_role_diff_section(self):
        report = ReportAssembler().assemble(
            _make_summary(), _make_surfaces(), _make_diffs(),
        )
        diff_section = [s for s in report.sections if s.kind == ReportSectionKind.ROLE_DIFF][0]
        assert len(diff_section.subsections) == 1
        assert "admin vs viewer" in diff_section.subsections[0].title

    def test_with_narratives(self):
        narrative = DiffNarrative(
            role_a_name="admin",
            role_b_name="viewer",
            executive_summary="Admin has broader access.",
            insights=[
                ReportInsight(
                    title="Privilege gap",
                    body="Admin-only URLs suggest privilege boundary.",
                    severity=InsightSeverity.SIGNIFICANT,
                    confidence=0.8,
                ),
            ],
            model_name="gpt-4o",
        )
        report = ReportAssembler().assemble(
            _make_summary(), _make_surfaces(), _make_diffs(),
            narratives=[narrative],
        )
        # Should have 9 sections (8 + LLM narrative)
        assert report.section_count == 9
        llm_section = [s for s in report.sections if s.kind == ReportSectionKind.LLM_NARRATIVE][0]
        assert "interpretive analysis" in llm_section.content.lower()

    def test_limitations_always_present(self):
        report = ReportAssembler().assemble(
            _make_summary(), _make_surfaces(), _make_diffs(),
        )
        limitations = [s for s in report.sections if s.kind == ReportSectionKind.LIMITATIONS]
        assert len(limitations) == 1
        assert "max_steps" in limitations[0].content
