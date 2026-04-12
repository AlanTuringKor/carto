"""
Prompt builder for ActionPlannerAgent.

Constructs a prompt from an ActionInventory + State that asks the LLM
which action to execute next and why.
"""

from __future__ import annotations

from carto.domain.inferences import ActionInventory
from carto.domain.models import State


def _format_actions(inventory: ActionInventory) -> str:
    if not inventory.discovered_actions:
        return "No actions available."
    lines: list[str] = []
    for i, action in enumerate(inventory.discovered_actions):
        parts = [f"[{i}] kind={action.kind} label=\"{action.label}\""]
        if action.css_selector:
            parts.append(f"selector=\"{action.css_selector}\"")
        if action.href:
            parts.append(f"href=\"{action.href}\"")
        parts.append(f"priority={action.priority}")
        if action.requires_auth:
            parts.append("requires_auth=True")
        if action.description:
            parts.append(f"note=\"{action.description}\"")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def _format_state(state: State) -> str:
    lines: list[str] = [
        f"Current URL: {state.current_url}",
        f"Auth state: {state.auth_state}",
        f"Active role: {state.active_role or '(none)'}",
        f"Visited pages ({len(state.visited_page_ids)}): "
        + (", ".join(state.visited_page_ids) if state.visited_page_ids else "(none)"),
        f"Actions performed ({len(state.performed_action_ids)}): "
        + (", ".join(state.performed_action_ids) if state.performed_action_ids else "(none)"),
    ]
    if state.cookies:
        lines.append(f"Cookie names: {list(state.cookies.keys())}")
    return "\n".join(lines)


def build_action_planner_prompt(
    inventory: ActionInventory,
    state: State,
    skip_login_fill: bool = False,
) -> str:
    """Build the full prompt for the ActionPlannerAgent."""

    # Build the login-page-specific instruction block.
    if inventory.is_login_page and skip_login_fill:
        login_instruction = (
            "⚠️  NO CREDENTIALS AVAILABLE: You are on a login page but no "
            "credentials have been configured. You MUST NOT choose any fill, "
            "submit, or form-related action (e.g. fill Email, fill Password, "
            "submit Log in). Instead, choose a NAVIGATE action to visit an "
            "unexplored page (e.g. Forgot your password, Register, About Us, "
            "Customer Feedback)."
        )
    elif inventory.is_login_page:
        login_instruction = (
            "You are on a login page and credentials are available. "
            "Prioritise filling the login form and submitting it."
        )
    else:
        login_instruction = (
            "Prefer unexplored areas over revisiting known pages."
        )

    return f"""You are an action planner for an autonomous web application mapper.
Given the available actions and current exploration state, decide which action to take next.

## Page Context
- URL: {inventory.page_title or "(unknown)"}
- Summary: {inventory.page_summary or "(no summary)"}
- Cluster: {inventory.page_cluster or "(unknown)"}
- Auth required: {inventory.auth_required}
- Is login page: {inventory.is_login_page}

## Current State
{_format_state(state)}

## Available Actions
{_format_actions(inventory)}

## Forms Available
{len(inventory.discovered_forms)} form(s) detected.
Auth forms present: {inventory.has_auth_forms}

## Decision Guidelines
- {login_instruction}
- Prefer high-priority actions as scored by page understanding.
- Avoid cycles: do not repeat actions that lead to already-visited stable states.
- Do NOT repeat an action whose label already appears in "Actions performed" above.
- If all paths are explored, set should_stop=true.
- Always provide a rationale for your choice.

## Response Format

Return a JSON object with:
- **chosen_action_kind**: "navigate", "click", "fill", "select", "submit", "scroll", "back", etc.
- **chosen_css_selector**: CSS selector of the target element (if applicable).
- **chosen_href**: URL to navigate to (if applicable).
- **chosen_label**: Label of the chosen action.
- **fill_value**: Value to fill (if action is "fill" or "select").
- **rationale**: Why this action was chosen (required).
- **expected_outcome**: What you expect to happen.
- **estimated_coverage_gain**: 0.0 to 1.0 estimate of new coverage this will add.
- **should_stop**: true if the run should terminate.
- **stop_reason**: Reason for stopping (if should_stop is true).

Return ONLY the JSON object."""
