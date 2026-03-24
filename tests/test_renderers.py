"""Tests for report renderers."""

from carto.domain.report import (
    CampaignReport,
    ReportSection,
    ReportSectionKind,
)
from carto.export.renderers import HtmlRenderer, JsonRenderer, MarkdownRenderer


def _make_report() -> CampaignReport:
    return CampaignReport(
        campaign_id="c1",
        target_url="https://example.com",
        role_names=["admin", "viewer"],
        sections=[
            ReportSection(
                title="Executive Summary",
                kind=ReportSectionKind.EXECUTIVE_SUMMARY,
                content="Campaign completed with **2** roles.",
            ),
            ReportSection(
                title="Role Summaries",
                kind=ReportSectionKind.ROLE_SUMMARY,
                subsections=[
                    ReportSection(
                        title="Role: admin",
                        kind=ReportSectionKind.ROLE_SUMMARY,
                        content="| Metric | Value |\n|---|---|\n| URLs | 10 |",
                    ),
                ],
            ),
            ReportSection(
                title="Limitations",
                kind=ReportSectionKind.LIMITATIONS,
                content="- Coverage is bounded by max_steps",
            ),
        ],
    )


class TestMarkdownRenderer:
    def test_renders_heading(self):
        md = MarkdownRenderer().render(_make_report())
        assert "# Campaign Report: https://example.com" in md

    def test_renders_metadata(self):
        md = MarkdownRenderer().render(_make_report())
        assert "**Campaign ID:** `c1`" in md
        assert "admin, viewer" in md

    def test_renders_sections(self):
        md = MarkdownRenderer().render(_make_report())
        assert "## Executive Summary" in md
        assert "## Role Summaries" in md
        assert "### Role: admin" in md

    def test_renders_content(self):
        md = MarkdownRenderer().render(_make_report())
        assert "Campaign completed with **2** roles." in md

    def test_renders_limitations(self):
        md = MarkdownRenderer().render(_make_report())
        assert "max_steps" in md


class TestJsonRenderer:
    def test_valid_json(self):
        import json
        output = JsonRenderer().render(_make_report())
        data = json.loads(output)
        assert data["campaign_id"] == "c1"

    def test_sections_present(self):
        import json
        data = json.loads(JsonRenderer().render(_make_report()))
        assert len(data["sections"]) == 3

    def test_nested_sections(self):
        import json
        data = json.loads(JsonRenderer().render(_make_report()))
        role_section = data["sections"][1]
        assert len(role_section["subsections"]) == 1


class TestHtmlRenderer:
    def test_valid_html(self):
        html = HtmlRenderer().render(_make_report())
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html

    def test_contains_title(self):
        html = HtmlRenderer().render(_make_report())
        assert "Carto Report: https://example.com" in html

    def test_contains_content(self):
        html = HtmlRenderer().render(_make_report())
        assert "Executive Summary" in html

    def test_contains_styling(self):
        html = HtmlRenderer().render(_make_report())
        assert "<style>" in html
