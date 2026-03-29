# Carto — Authentication Handling Design

## Overview

Authentication handling is a first-class concern in Carto because mapping quality depends heavily on correct login-state understanding. This document describes how auth-related observations, artefacts, and decisions are structured.

## Principles

1. **Secrets never stored raw** — All tokens, session IDs, and passwords are wrapped in `RedactedValue` (SHA-256 fingerprint + masked preview).
2. **Auth is observed, not assumed** — Auth state is derived from browser evidence (cookies, headers, storage), not from config alone.
3. **Explicit, not implicit** — Auth context is passed as typed data through the agent pipeline, never inferred from ambient state.
4. **Auditable** — Every auth transition is recorded as a `StateDelta` with before/after evidence, and as an `auth_transition` event in the event log.

## Auth Domain Models (`carto/domain/auth.py`)

| Model | Purpose |
|---|---|
| `RedactedValue` | Wraps a secret: fingerprint for comparison, masked preview for debugging |
| `AuthMechanism` | Enum: cookie, bearer_token, session_storage, local_storage, basic_auth, form_post |
| `AuthEvidence` | A single observed auth signal (e.g. session cookie, bearer header) |
| `AuthContext` | Aggregated auth posture for a page (mechanism, evidence, CSRF, tokens) |
| `LoginFlowObservation` | Structured capture of a login form (fields, selectors, CSRF presence) |
| `AuthTransition` | Records an auth state change (login/logout, new/lost evidence) |

## Redaction (`carto/utils/redaction.py`)

Sensitive key detection uses regex patterns matching: `token`, `session`, `auth`, `csrf`, `xsrf`, `bearer`, `password`, `secret`, `api_key`, `jwt`, `credential`, etc.

```python
# Cookies are always fully redacted
redacted = redact_cookies({"sessionid": "abc123"})
# → {"sessionid": RedactedValue(preview="abc***123", fingerprint="sha256...")}

# Dicts are selectively redacted based on key patterns
redacted = redact_dict({"csrf_token": "tok", "theme": "dark"})
# → {"csrf_token": RedactedValue(...), "theme": "dark"}
```

## Auth-Aware Agents

### PageUnderstandingAgent
Detects: login pages, auth forms, CSRF tokens, logout links, OAuth buttons. Populates `ActionInventory.is_login_page`, `has_auth_forms`, `csrf_hints`, `auth_mechanisms_detected`.

### FormFillerAgent
When `is_login_form=True`, uses provided role credentials. Preserves CSRF hidden fields. Tracks which selectors contain auth credentials (`auth_field_selectors`).

### StateDiffAgent
Detects: login events, logout events, session refreshes. Reports cookie/storage changes. Flags security observations (e.g. "session cookie without Secure flag").

## Auth Flow

```
1. Initial navigation → PageObservation
2. PageUnderstandingAgent detects login page
3. Orchestrator checks: is_login_page + has forms + not authenticated
4. FormFillerAgent generates fill plan with role credentials
5. Orchestrator executes Fill commands + submit
6. New PageObservation after submit
7. StateDiffAgent compares before/after states
8. If login_detected → AuthState.AUTHENTICATED
9. Mapping continues with authenticated session
```

## Approval Gates for Auth Actions (Phase 3)

Sensitive auth-related actions trigger approval gates:

| Action | Approval Reason |
|---|---|
| Login form submission | `credential_submission` |
| Logout click | `logout_action` |
| MFA-related steps | `mfa_step` |
| OAuth consent / authorize | `oauth_consent` |
| Destructive actions (delete, revoke) | `destructive_action` |

Approval policies:
- **`AutoApprovePolicy`** — approves everything (for automated runs)
- **`InteractiveApprovalPolicy`** — flags sensitive actions, base for UI implementations
- **`CLIApprovalPolicy`** — prompts on stdin for y/n

## HAR Export Auth Safety (Phase 3)

HAR exports apply configurable redaction to auth-sensitive data:

| Data Type | Default Policy |
|---|---|
| `Authorization` header | `redact` |
| `Cookie` header | `redact` |
| `Set-Cookie` header | `redact` |
| CSRF token headers | `redact` |
| POST body (may contain passwords) | `exclude` |

Available policies: `exclude`, `redact` (replace with `[REDACTED]`), `fingerprint` (SHA-256 hash), `include` (raw — use only when explicitly allowed).

## What Is Deferred

- **Token refresh automation** — detected but not automated (Phase 4)
- **Multi-factor auth automation** — approval gates prepared, full automation deferred
- **OAuth redirect flows** — OAuth buttons detected, approval gates flag consent steps
- **Certificate-based auth** — out of scope
- **Multi-role runs** — Phase 4
