"""
Prompt builder for RiskAgent.

Constructs a structured prompt from a RiskInput that asks the LLM to
identify security-relevant patterns, map them to CWEs, and assign
severity levels — without fabricating confirmed vulnerabilities.
"""

from __future__ import annotations

from carto.domain.risk_input import RiskInput


def _format_actions(input: RiskInput) -> str:
    actions = input.inventory.discovered_actions
    if not actions:
        return "No actions discovered."
    lines: list[str] = []
    for i, action in enumerate(actions):
        parts = [f"[{i}] kind={action.kind} label=\"{action.label}\""]
        if action.requires_auth:
            parts.append("requires_auth=True")
        if action.description:
            parts.append(f"note=\"{action.description}\"")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _format_forms(input: RiskInput) -> str:
    forms = input.inventory.discovered_forms
    if not forms:
        return "No forms discovered."
    lines: list[str] = []
    for i, form in enumerate(forms):
        field_names = [f.name or f.kind for f in form]
        lines.append(f"Form[{i}]: fields={field_names}")
    return "\n".join(lines)


def _format_auth(input: RiskInput) -> str:
    parts: list[str] = []
    inv = input.inventory
    if inv.is_login_page:
        parts.append("This is a login page.")
    if inv.has_auth_forms:
        parts.append("Has authentication forms.")
    if inv.csrf_hints:
        parts.append(f"CSRF hints: {inv.csrf_hints}")
    if inv.auth_mechanisms_detected:
        parts.append(f"Auth mechanisms: {inv.auth_mechanisms_detected}")
    if input.auth_context:
        parts.append(f"Authenticated: {input.auth_context.is_authenticated}")
        parts.append(f"CSRF token present: {input.auth_context.csrf_token_present}")
    return "\n".join(parts) if parts else "No auth context."


def _format_state_delta(input: RiskInput) -> str:
    if not input.state_delta:
        return "No state delta available."
    d = input.state_delta
    lines = [
        f"Auth state changed: {d.auth_state_changed}",
        f"Login detected: {d.login_detected}",
        f"Logout detected: {d.logout_detected}",
        f"Cookies added: {d.cookies_added}",
        f"Cookies removed: {d.cookies_removed}",
    ]
    if d.security_observations:
        lines.append(f"Security observations: {d.security_observations}")
    return "\n".join(lines)


def build_risk_prompt(input: RiskInput) -> str:
    """Build the full prompt for the RiskAgent."""
    return f"""You are a security risk analyst for an autonomous web application mapper.
Analyse the following evidence and identify security-relevant patterns.

IMPORTANT:
- Do NOT fabricate confirmed vulnerabilities.
- Only report evidence-backed observations and potential risk indicators.
- Map findings to CWE identifiers where applicable.
- Assign severity: info, low, medium, high, critical.

## Page Context
- URL: {input.page_url}
- Cluster: {input.page_cluster or "(unknown)"}

## Actions Discovered
{_format_actions(input)}

## Forms
{_format_forms(input)}

## Auth Context
{_format_auth(input)}

## State Changes
{_format_state_delta(input)}

## Interesting Patterns (from page understanding)
{chr(10).join(input.inventory.interesting_patterns) if input.inventory.interesting_patterns else "None noted."}

## Additional Security Observations
{chr(10).join(input.security_observations) if input.security_observations else "None."}

## What to look for:
1. **Missing CSRF tokens** on state-changing forms
2. **Sensitive data in GET parameters** (passwords, tokens in URLs)
3. **File upload forms** without apparent validation
4. **Admin/settings/integration pages** that may be improperly protected
5. **IDOR indicators** (sequential IDs in URLs, direct object references)
6. **Session fixation** risk (no new session on login)
7. **Insecure token storage** (tokens in localStorage instead of httpOnly cookies)
8. **Open redirect** potential (URL parameters that control redirects)
9. **Mixed content** issues
10. **Hidden actions** (actions gated behind auth that should be but are not)
11. **Import/export functionality** that may leak data
12. **Role boundary issues** (admin actions reachable by lower-privilege paths)

## Response Format

Return a JSON object with:
- **signals**: List of risk signals, each with:
  - **title**: Short title for the finding
  - **description**: Detailed description with evidence
  - **severity**: "info", "low", "medium", "high", or "critical"
  - **evidence**: The specific evidence backing this finding
  - **cwe**: CWE identifier if applicable (e.g. "CWE-352")
- **summary**: One-sentence summary of overall risk posture for this page.
- **highest_severity**: The highest severity among all signals.

Return ONLY the JSON object."""
