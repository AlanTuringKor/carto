"""Tests for report domain models."""

from carto.domain.report import (
    CampaignReport,
    ReportSection,
    ReportSectionKind,
)


class TestReportSectionKind:
    def test_all_kinds(self):
        assert len(ReportSectionKind) == 10

    def test_values(self):
        assert ReportSectionKind.EXECUTIVE_SUMMARY == "executive_summary"
        assert ReportSectionKind.LLM_NARRATIVE == "llm_narrative"


class TestReportSection:
    def test_basic(self):
        s = ReportSection(
            title="Test",
            kind=ReportSectionKind.EXECUTIVE_SUMMARY,
            content="Hello",
        )
        assert s.title == "Test"
        assert s.content == "Hello"
        assert s.evidence_refs == []

    def test_with_subsections(self):
        sub = ReportSection(
            title="Sub",
            kind=ReportSectionKind.ROLE_SUMMARY,
            content="Role info",
        )
        parent = ReportSection(
            title="Roles",
            kind=ReportSectionKind.ROLE_SUMMARY,
            subsections=[sub],
        )
        assert len(parent.subsections) == 1
        assert parent.subsections[0].title == "Sub"

    def test_evidence_refs(self):
        s = ReportSection(
            title="Hotspots",
            kind=ReportSectionKind.HOTSPOTS,
            evidence_refs=["sig-1", "sig-2"],
        )
        assert len(s.evidence_refs) == 2


class TestCampaignReport:
    def test_basic(self):
        r = CampaignReport(
            campaign_id="c1",
            target_url="https://example.com",
        )
        assert r.report_id
        assert r.section_count == 0

    def test_with_sections(self):
        r = CampaignReport(
            campaign_id="c1",
            target_url="https://example.com",
            role_names=["admin", "viewer"],
            sections=[
                ReportSection(title="Summary", kind=ReportSectionKind.EXECUTIVE_SUMMARY),
                ReportSection(title="Overview", kind=ReportSectionKind.CAMPAIGN_OVERVIEW),
            ],
        )
        assert r.section_count == 2
        assert r.role_names == ["admin", "viewer"]

    def test_serialization(self):
        r = CampaignReport(
            campaign_id="c1",
            target_url="https://example.com",
            sections=[
                ReportSection(
                    title="Summary",
                    kind=ReportSectionKind.EXECUTIVE_SUMMARY,
                    content="Test content",
                ),
            ],
        )
        data = r.model_dump(mode="json")
        assert data["campaign_id"] == "c1"
        assert len(data["sections"]) == 1
