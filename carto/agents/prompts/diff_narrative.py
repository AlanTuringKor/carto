"""
Prompt builder for the DiffNarrativeAgent.

Constructs a structured prompt from typed diff/surface data
for LLM-based interpretive analysis.
"""

from __future__ import annotations

from carto.domain.role_diff import RoleDiffResult, VisibilityCategory
from carto.domain.role_surface import RoleSurface


def build_diff_narrative_prompt(
    diff: RoleDiffResult,
    surface_a: RoleSurface,
    surface_b: RoleSurface,
) -> str:
    """
    Build a prompt for the DiffNarrativeAgent.

    The prompt provides the deterministic diff data and asks the LLM
    to interpret it, never fabricating confirmed vulnerabilities.
    """
    delta = diff.delta

    only_a_urls = [d.item for d in delta.url_diff if d.category == VisibilityCategory.ONLY_A]
    only_b_urls = [d.item for d in delta.url_diff if d.category == VisibilityCategory.ONLY_B]
    shared_urls = [d.item for d in delta.url_diff if d.category == VisibilityCategory.SHARED]

    only_a_actions = [d.item for d in delta.action_diff if d.category == VisibilityCategory.ONLY_A]
    only_b_actions = [d.item for d in delta.action_diff if d.category == VisibilityCategory.ONLY_B]

    only_a_forms = [d.item for d in delta.form_diff if d.category == VisibilityCategory.ONLY_A]
    only_b_forms = [d.item for d in delta.form_diff if d.category == VisibilityCategory.ONLY_B]

    sections = [
        "You are a security analyst reviewing cross-role surface differences.",
        "",
        "## RULES",
        "- Provide evidence-backed interpretation of the differences below.",
        "- NEVER claim a confirmed vulnerability. Only flag potential indicators.",
        "- Keep your analysis conservative and traceable to the data provided.",
        "- Focus on access control boundaries and privilege escalation risk.",
        "- Output valid JSON matching the requested schema.",
        "",
        f"## COMPARISON: {diff.role_a_name} vs {diff.role_b_name}",
        "",
        f"### Role A: {diff.role_a_name}",
        f"- Auth state: {surface_a.auth_state}",
        f"- URLs discovered: {len(surface_a.urls)}",
        f"- Actions: {len(surface_a.action_labels)}",
        f"- Forms: {len(surface_a.form_urls)}",
        "",
        f"### Role B: {diff.role_b_name}",
        f"- Auth state: {surface_b.auth_state}",
        f"- URLs discovered: {len(surface_b.urls)}",
        f"- Actions: {len(surface_b.action_labels)}",
        f"- Forms: {len(surface_b.form_urls)}",
        "",
        "### URL Differences",
        f"Shared: {len(shared_urls)}",
    ]

    if only_a_urls:
        sections.append(f"Only {diff.role_a_name}: {', '.join(only_a_urls[:20])}")
    if only_b_urls:
        sections.append(f"Only {diff.role_b_name}: {', '.join(only_b_urls[:20])}")

    if only_a_actions or only_b_actions:
        sections.append("")
        sections.append("### Action Differences")
        if only_a_actions:
            sections.append(f"Only {diff.role_a_name}: {', '.join(only_a_actions[:20])}")
        if only_b_actions:
            sections.append(f"Only {diff.role_b_name}: {', '.join(only_b_actions[:20])}")

    if only_a_forms or only_b_forms:
        sections.append("")
        sections.append("### Form Differences")
        if only_a_forms:
            sections.append(f"Only {diff.role_a_name}: {', '.join(only_a_forms[:20])}")
        if only_b_forms:
            sections.append(f"Only {diff.role_b_name}: {', '.join(only_b_forms[:20])}")

    sections.append("")
    sections.append(f"### Auth Boundary")
    sections.append(f"Auth match: {delta.auth_boundary.get('auth_states_match', 'unknown')}")

    sections.append("")
    sections.append(f"### Summary")
    sections.append(f"Total non-shared differences: {delta.total_differences}")

    sections.append("")
    sections.append("## TASK")
    sections.append("Analyse the differences and produce:")
    sections.append("1. An executive_summary (2-3 sentences)")
    sections.append("2. A list of insights, each with:")
    sections.append("   - title: short headline")
    sections.append("   - body: explanation (1-3 sentences)")
    sections.append("   - severity: info | notable | significant | critical")
    sections.append("   - confidence: 0.0-1.0")
    sections.append("   - evidence_refs: list of items from the diff that support this insight")

    return "\n".join(sections)
