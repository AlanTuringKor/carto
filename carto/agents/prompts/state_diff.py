"""
Prompt builder for StateDiffAgent.

Constructs a prompt from a StateDiffInput (before/after State) that asks
the LLM to identify meaningful state changes, especially auth transitions.
"""

from __future__ import annotations

from carto.domain.inferences import StateDiffInput


def _diff_dicts(before: dict[str, str], after: dict[str, str]) -> dict[str, str]:
    """Return a human-readable diff summary of two dicts."""
    added = {k: v for k, v in after.items() if k not in before}
    removed = {k: v for k, v in before.items() if k not in after}
    modified = {
        k: f"{before[k][:20]}... → {after[k][:20]}..."
        for k in before
        if k in after and before[k] != after[k]
    }
    parts: dict[str, str] = {}
    if added:
        parts["added"] = str(list(added.keys()))
    if removed:
        parts["removed"] = str(list(removed.keys()))
    if modified:
        parts["modified"] = str(list(modified.keys()))
    return parts


def _format_state_snapshot(label: str, state_url: str | None, cookies: dict[str, str], 
                           local_storage: dict[str, str], session_storage: dict[str, str],
                           auth_state: str) -> str:
    lines = [
        f"### {label}",
        f"- URL: {state_url or '(unknown)'}",
        f"- Auth state: {auth_state}",
        f"- Cookie names: {list(cookies.keys())}",
        f"- localStorage keys: {list(local_storage.keys())}",
        f"- sessionStorage keys: {list(session_storage.keys())}",
    ]
    return "\n".join(lines)


def build_state_diff_prompt(input: StateDiffInput) -> str:
    """Build the full prompt for the StateDiffAgent."""
    cookie_diff = _diff_dicts(input.before.cookies, input.after.cookies)
    ls_diff = _diff_dicts(input.before.local_storage, input.after.local_storage)
    ss_diff = _diff_dicts(input.before.session_storage, input.after.session_storage)

    return f"""You are a state diff agent for an autonomous web mapper.
Compare two browser state snapshots and identify meaningful changes.

## Triggering Action
- Label: {input.triggering_action_label or "(unknown)"}
- Kind: {input.triggering_action_kind or "(unknown)"}

{_format_state_snapshot("Before", input.page_url_before, input.before.cookies, input.before.local_storage, input.before.session_storage, str(input.before.auth_state))}

{_format_state_snapshot("After", input.page_url_after, input.after.cookies, input.after.local_storage, input.after.session_storage, str(input.after.auth_state))}

## Diffs
- Cookie changes: {cookie_diff or "none"}
- localStorage changes: {ls_diff or "none"}
- sessionStorage changes: {ss_diff or "none"}
- URL changed: {input.page_url_before != input.page_url_after}

## Instructions

Analyse the state transition and return a JSON object with:
- **url_changed**: Whether the URL changed.
- **auth_state_changed**: Whether the authentication state changed.
- **login_detected**: Whether this transition represents a successful login.
- **logout_detected**: Whether this transition represents a logout.
- **session_refresh_detected**: Whether session tokens were refreshed without re-auth.
- **cookies_added**: List of new cookie names.
- **cookies_removed**: List of removed cookie names.
- **cookies_modified**: List of modified cookie names.
- **storage_keys_added**: List of new storage keys (localStorage + sessionStorage).
- **storage_keys_removed**: List of removed storage keys.
- **role_changed**: Whether the user role appears to have changed.
- **security_observations**: List of security-relevant observations (e.g. "session cookie set without Secure flag", "token stored in localStorage").
- **summary**: One-sentence summary of the state change.

Return ONLY the JSON object."""
