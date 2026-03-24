"""
Prompt builder for PageUnderstandingAgent.

Constructs a structured prompt from a PageObservation that asks the LLM
to identify interactive elements, forms, auth signals, and page purpose.
"""

from __future__ import annotations

from carto.domain.observations import PageObservation

_MAX_TEXT_CHARS = 8000
_MAX_ELEMENTS = 100


def _truncate(text: str | None, limit: int = _MAX_TEXT_CHARS) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text)} total chars]"


def _format_elements(obs: PageObservation) -> str:
    elements = obs.interactive_elements[:_MAX_ELEMENTS]
    if not elements:
        return "No interactive elements found."
    lines: list[str] = []
    for i, el in enumerate(elements):
        parts = [f"[{i}] <{el.tag}>"]
        if el.text:
            parts.append(f'text="{el.text[:80]}"')
        if el.href:
            parts.append(f'href="{el.href}"')
        if el.aria_label:
            parts.append(f'aria="{el.aria_label}"')
        attrs = ", ".join(f"{k}={v}" for k, v in el.attributes.items())
        if attrs:
            parts.append(f"attrs=[{attrs}]")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _format_forms(obs: PageObservation) -> str:
    if not obs.forms_raw:
        return "No forms found."
    lines: list[str] = []
    for i, form in enumerate(obs.forms_raw):
        lines.append(f"Form[{i}]: action={form.action}, method={form.method}")
        for j, field in enumerate(form.fields_raw):
            tag = field.get("tag", "?")
            ftype = field.get("type", "?")
            name = field.get("name", "?")
            fid = field.get("id", "?")
            placeholder = field.get("placeholder", "")
            required = field.get("required", False)
            lines.append(
                f"  Field[{j}]: <{tag}> type={ftype} name={name} "
                f"id={fid} placeholder={placeholder} required={required}"
            )
    return "\n".join(lines)


def _format_auth_hints(obs: PageObservation) -> str:
    hints: list[str] = []
    if obs.cookies:
        cookie_names = list(obs.cookies.keys())
        hints.append(f"Cookies present: {cookie_names}")
    if obs.local_storage:
        hints.append(f"localStorage keys: {list(obs.local_storage.keys())}")
    if obs.session_storage:
        hints.append(f"sessionStorage keys: {list(obs.session_storage.keys())}")
    return "\n".join(hints) if hints else "No auth-related browser state observed."


def build_page_understanding_prompt(obs: PageObservation) -> str:
    """Build the full prompt for the PageUnderstandingAgent."""
    return f"""Analyse this web page and return a structured JSON interpretation.

## Page Information
- URL: {obs.url}
- Final URL: {obs.final_url}
- Title: {obs.title or "(none)"}
- Status Code: {obs.status_code or "(unknown)"}

## Accessible Text
{_truncate(obs.accessible_text)}

## Interactive Elements
{_format_elements(obs)}

## Forms
{_format_forms(obs)}

## Auth / Session Hints
{_format_auth_hints(obs)}

## Instructions

Analyse this page and return a JSON object with these fields:

1. **page_title**: The page title.
2. **page_summary**: One-sentence description of the page purpose.
3. **page_cluster**: Classify as one of: "login", "registration", "dashboard", "settings", "profile", "admin", "search", "listing", "detail", "error", "logout", "home", "other".
4. **auth_required**: Whether this page requires authentication to access.
5. **is_login_page**: Whether this is a login/authentication page.
6. **is_logout_page**: Whether this page is or triggers a logout.
7. **has_auth_forms**: Whether any form appears to be an auth form (login, registration, password reset).
8. **csrf_hints**: List of field names or patterns that look like CSRF/XSRF tokens.
9. **auth_mechanisms_detected**: List of detected auth mechanisms (e.g. "cookie_session", "bearer_token", "basic_auth").
10. **login_form_selector**: CSS selector for the login form, if present.
11. **username_field_selector**: CSS selector for the username/email field, if present.
12. **password_field_selector**: CSS selector for the password field, if present.
13. **discovered_actions**: List of interactive actions. For each:
    - label: human-readable label
    - kind: one of "navigate", "click", "fill", "select", "submit", "hover", "scroll"
    - css_selector: CSS selector (if applicable)
    - href: link target (if applicable)
    - description: brief note on what this action does
    - priority: 0.0 to 1.0 (higher = more interesting for exploration)
    - requires_auth: whether this action requires authentication
14. **discovered_forms**: List of forms. Each form is a list of fields:
    - css_selector, name, label, kind (text/password/email/etc.), semantic_meaning, required
15. **navigation_links**: List of href values for navigation links.
16. **api_endpoints_observed**: Any API endpoints visible in the page source or XHR URLs.
17. **interesting_patterns**: Security-relevant patterns (e.g. "no CSRF token on form", "admin link exposed").

Return ONLY the JSON object."""
