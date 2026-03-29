"""
ReportAssembler — deterministic campaign report construction.

Converts existing campaign outputs (``CampaignSummary``, ``RoleSurface``,
``RoleDiffResult``, risk signals) into a structured ``CampaignReport``
with ordered sections.

No LLM calls.  All content is derived from typed inputs.
"""

from __future__ import annotations

from carto.domain.campaign import CampaignSummary, RoleRunSummary
from carto.domain.diff_narrative import DiffNarrative
from carto.domain.models import AuthState
from carto.domain.report import (
    CampaignReport,
    ReportSection,
    ReportSectionKind,
)
from carto.domain.role_diff import (
    RoleDiffResult,
    VisibilityCategory,
)
from carto.domain.role_surface import RoleSurface


class ReportAssembler:
    """
    Deterministic report builder from campaign outputs.

    All sections are evidence-backed.  Observations are labelled as
    observations; inferred risk is labelled as potential.
    """

    def assemble(
        self,
        summary: CampaignSummary,
        surfaces: dict[str, RoleSurface],
        diffs: list[RoleDiffResult],
        narratives: list[DiffNarrative] | None = None,
    ) -> CampaignReport:
        """Build a complete CampaignReport from campaign outputs."""
        sections: list[ReportSection] = [
            self._executive_summary(summary, diffs),
            self._campaign_overview(summary),
            self._role_summaries(summary, surfaces),
            self._role_matrix(surfaces),
            self._role_diff_sections(diffs),
            self._auth_surface(summary, surfaces),
            self._coverage(summary, surfaces),
        ]

        # Optional LLM narratives
        if narratives:
            sections.append(self._llm_narratives(narratives))

        sections.append(self._limitations())

        return CampaignReport(
            campaign_id=summary.campaign_id,
            target_url=summary.target_url,
            role_names=[rs.role_name for rs in summary.role_summaries],
            sections=sections,
        )

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _executive_summary(
        self,
        summary: CampaignSummary,
        diffs: list[RoleDiffResult],
    ) -> ReportSection:
        roles = summary.role_summaries
        total_urls = sum(rs.unique_urls for rs in roles)
        total_actions = sum(rs.actions_discovered for rs in roles)
        total_diffs = sum(d.delta.total_differences for d in diffs)

        lines = [
            f"Campaign against **{summary.target_url}** completed with "
            f"**{len(roles)}** roles mapped.",
            "",
            f"- **{total_urls}** unique URLs discovered across all roles",
            f"- **{total_actions}** actions discovered",
            f"- **{total_diffs}** cross-role visibility differences detected",
        ]

        if total_diffs > 0:
            lines.append("")
            lines.append(
                "⚠ Role visibility differences detected — review the "
                "Role Diff section for access control boundary analysis."
            )

        return ReportSection(
            title="Executive Summary",
            kind=ReportSectionKind.EXECUTIVE_SUMMARY,
            content="\n".join(lines),
            evidence_refs=[summary.campaign_id],
        )

    def _campaign_overview(self, summary: CampaignSummary) -> ReportSection:
        lines = [
            f"| Property | Value |",
            f"|---|---|",
            f"| Target URL | `{summary.target_url}` |",
            f"| Campaign ID | `{summary.campaign_id}` |",
            f"| Status | {summary.status} |",
            f"| Roles | {', '.join(rs.role_name for rs in summary.role_summaries)} |",
            f"| Completed | {summary.completed_at or 'N/A'} |",
        ]
        return ReportSection(
            title="Campaign Overview",
            kind=ReportSectionKind.CAMPAIGN_OVERVIEW,
            content="\n".join(lines),
            evidence_refs=[summary.campaign_id],
        )

    def _role_summaries(
        self,
        summary: CampaignSummary,
        surfaces: dict[str, RoleSurface],
    ) -> ReportSection:
        subsections = []
        for rs in summary.role_summaries:
            surface = surfaces.get(rs.role_name)
            lines = [
                f"| Metric | Value |",
                f"|---|---|",
                f"| Status | {rs.status} |",
                f"| Steps | {rs.step_count} |",
                f"| Unique URLs | {rs.unique_urls} |",
                f"| Actions | {rs.actions_discovered} |",
                f"| Forms | {rs.forms_discovered} |",
                f"| Auth State | {rs.auth_state} |",
            ]
            if rs.error:
                lines.append(f"| Error | {rs.error} |")
            if surface and surface.form_urls:
                lines.append("")
                lines.append("**Form URLs:** " + ", ".join(f"`{u}`" for u in sorted(surface.form_urls)))

            subsections.append(ReportSection(
                title=f"Role: {rs.role_name}",
                kind=ReportSectionKind.ROLE_SUMMARY,
                content="\n".join(lines),
                evidence_refs=[rs.run_id],
            ))

        return ReportSection(
            title="Per-Role Summaries",
            kind=ReportSectionKind.ROLE_SUMMARY,
            subsections=subsections,
        )

    def _role_matrix(self, surfaces: dict[str, RoleSurface]) -> ReportSection:
        role_names = sorted(surfaces.keys())
        if not role_names:
            return ReportSection(
                title="Role Visibility Matrix",
                kind=ReportSectionKind.ROLE_MATRIX,
                content="No role surfaces available.",
            )

        # Build URL visibility matrix
        all_urls = set()
        for s in surfaces.values():
            all_urls.update(s.urls)

        header = "| URL | " + " | ".join(role_names) + " |"
        sep = "|---|" + "|".join("---" for _ in role_names) + "|"
        rows = []
        for url in sorted(all_urls):
            cells = []
            for rn in role_names:
                cells.append("✓" if url in surfaces[rn].urls else "✗")
            rows.append(f"| `{url}` | " + " | ".join(cells) + " |")

        content = "\n".join([header, sep] + rows)
        return ReportSection(
            title="Role Visibility Matrix",
            kind=ReportSectionKind.ROLE_MATRIX,
            content=content,
        )

    def _role_diff_sections(self, diffs: list[RoleDiffResult]) -> ReportSection:
        subsections = []
        for diff in diffs:
            delta = diff.delta
            lines = []

            # URL differences
            only_a = [d for d in delta.url_diff if d.category == VisibilityCategory.ONLY_A]
            only_b = [d for d in delta.url_diff if d.category == VisibilityCategory.ONLY_B]
            shared = [d for d in delta.url_diff if d.category == VisibilityCategory.SHARED]

            lines.append(f"**URLs:** {len(shared)} shared, "
                         f"{len(only_a)} only {diff.role_a_name}, "
                         f"{len(only_b)} only {diff.role_b_name}")

            if only_a:
                lines.append("")
                lines.append(f"*Only {diff.role_a_name}:*")
                for d in only_a:
                    lines.append(f"- `{d.item}`")

            if only_b:
                lines.append("")
                lines.append(f"*Only {diff.role_b_name}:*")
                for d in only_b:
                    lines.append(f"- `{d.item}`")

            # Action differences
            only_a_act = [d for d in delta.action_diff if d.category == VisibilityCategory.ONLY_A]
            only_b_act = [d for d in delta.action_diff if d.category == VisibilityCategory.ONLY_B]
            if only_a_act or only_b_act:
                lines.append("")
                lines.append("**Action Differences:**")
                for d in only_a_act:
                    lines.append(f"- `{d.item}` — only {diff.role_a_name}")
                for d in only_b_act:
                    lines.append(f"- `{d.item}` — only {diff.role_b_name}")

            # Auth boundary
            if delta.auth_boundary:
                lines.append("")
                lines.append(f"**Auth:** {diff.role_a_name}={delta.auth_boundary.get('role_a_auth', '?')}, "
                             f"{diff.role_b_name}={delta.auth_boundary.get('role_b_auth', '?')}")

            lines.append("")
            lines.append(f"**Total non-shared differences: {delta.total_differences}**")

            subsections.append(ReportSection(
                title=f"Diff: {diff.role_a_name} vs {diff.role_b_name}",
                kind=ReportSectionKind.ROLE_DIFF,
                content="\n".join(lines),
                evidence_refs=[diff.result_id],
            ))

        return ReportSection(
            title="Role Diffs",
            kind=ReportSectionKind.ROLE_DIFF,
            subsections=subsections,
        )

    def _auth_surface(
        self,
        summary: CampaignSummary,
        surfaces: dict[str, RoleSurface],
    ) -> ReportSection:
        lines = [
            "| Role | Auth State | Form URLs |",
            "|---|---|---|",
        ]
        for rs in summary.role_summaries:
            surface = surfaces.get(rs.role_name)
            form_count = len(surface.form_urls) if surface else 0
            lines.append(
                f"| {rs.role_name} | {rs.auth_state} | {form_count} |"
            )

        authed = [rs for rs in summary.role_summaries if rs.auth_state == AuthState.AUTHENTICATED]
        if authed:
            lines.append("")
            lines.append(f"**{len(authed)}/{len(summary.role_summaries)}** roles achieved authenticated state.")

        return ReportSection(
            title="Auth Surface Summary",
            kind=ReportSectionKind.AUTH_SURFACE,
            content="\n".join(lines),
        )

    def _coverage(
        self,
        summary: CampaignSummary,
        surfaces: dict[str, RoleSurface],
    ) -> ReportSection:
        lines = [
            "| Role | URLs | Actions | Forms | Steps |",
            "|---|---|---|---|---|",
        ]
        for rs in summary.role_summaries:
            lines.append(
                f"| {rs.role_name} | {rs.unique_urls} | {rs.actions_discovered} | "
                f"{rs.forms_discovered} | {rs.step_count} |"
            )

        # URL overlap
        all_urls: list[set[str]] = [s.urls for s in surfaces.values()]
        if len(all_urls) >= 2:
            shared = all_urls[0]
            for s in all_urls[1:]:
                shared = shared & s
            total = set()
            for s in all_urls:
                total.update(s)
            lines.append("")
            lines.append(f"**URL overlap:** {len(shared)}/{len(total)} URLs shared across all roles.")

        return ReportSection(
            title="Coverage Summary",
            kind=ReportSectionKind.COVERAGE,
            content="\n".join(lines),
        )


    def _llm_narratives(self, narratives: list[DiffNarrative]) -> ReportSection:
        subsections = []
        for narr in narratives:
            lines = [
                f"*Generated by `{narr.agent_name}` using `{narr.model_name}`*",
                "",
                "**⚠ The following is LLM-generated interpretive analysis, "
                "not confirmed factual findings.**",
                "",
                narr.executive_summary,
            ]
            if narr.insights:
                lines.append("")
                lines.append("**Insights:**")
                lines.append("")
                for insight in narr.insights:
                    conf = f" (confidence: {insight.confidence:.0%})" if insight.confidence else ""
                    lines.append(f"- **[{insight.severity.upper()}]** {insight.title}{conf}")
                    lines.append(f"  {insight.body}")

            subsections.append(ReportSection(
                title=f"Narrative: {narr.role_a_name} vs {narr.role_b_name}",
                kind=ReportSectionKind.LLM_NARRATIVE,
                content="\n".join(lines),
                evidence_refs=[narr.narrative_id],
            ))

        return ReportSection(
            title="LLM-Enhanced Analysis",
            kind=ReportSectionKind.LLM_NARRATIVE,
            content="The following sections contain LLM-generated interpretive "
                    "analysis enriching the deterministic diff results.",
            subsections=subsections,
        )

    def _limitations(self) -> ReportSection:
        lines = [
            "- Coverage is bounded by the configured `max_steps` per role",
            "- JavaScript-heavy SPAs may have incomplete state capture",
            "- Token refresh, MFA, and OAuth flows are detected but not automated",
            "- LLM narrative (if present) is interpretive analysis requiring human review",
            "- `shared_different` detection (same URL, different behaviour) requires "
            "manual verification",
            "- True parallel role execution is not yet supported",
        ]
        return ReportSection(
            title="Limitations & Caveats",
            kind=ReportSectionKind.LIMITATIONS,
            content="\n".join(lines),
        )
