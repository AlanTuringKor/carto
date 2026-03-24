# Carto

**LLM-driven web application mapper for penetration testing.**

Carto autonomously explores authenticated web applications, maps their surface area across multiple user roles, understands auth boundaries and state transitions, and produces structured, replayable artifacts for security teams.

---

## What Problem It Solves

Manual web app pentesting starts with tedious surface enumeration — clicking through pages, mapping forms, tracking auth state, comparing what different roles can see. Carto automates this with LLM-driven agents and a real browser, producing typed, auditable output suitable for security review.

---

## Architecture

```
Orchestrator
  observe → page_understanding → risk → action_planner → approve → execute
          → form_filler (login forms) → state_diff
  [EventLog]  [ApprovalPolicy]  [HarBuilder]

CampaignRunner
  for each role: create executor → run orchestrator → capture surface
  then: pairwise role diff → campaign summary
```

- **Modular monolith** — all components in one package, clean module boundaries
- **Typed everywhere** — Pydantic V2 for domain, contracts, and inter-agent messages
- **Observation ≠ Inference** — raw browser facts vs. LLM interpretations, strictly separated
- **Executor is the only I/O boundary** — agents reason and return typed output, only `BrowserExecutor` touches the browser
- **Redaction-safe** — secrets wrapped in `RedactedValue`, never leak to logs/prompts/exports

See [architecture.md](docs/architecture.md) and [auth.md](docs/auth.md) for full design details.

---

## Phase Status

| Phase | Focus | Status |
|---|---|---|
| **1** | Domain models, contracts, agent interfaces, browser executor, orchestrator | ✅ |
| **2** | LLM integration for all agents, form filling, state diffing, auth handling | ✅ |
| **3** | Structured event log, approval gates, HAR export, RiskAgent | ✅ |
| **4A** | Multi-role campaigns, coordinated role diffing foundations | ✅ |
| **4B** | Report generation, LLM-enhanced diff analysis | ✅ |
| **4C** | Multi-LLM providers, configuration file support | ✅ |
| **5**  | Persistent storage, UI / Dashboard (Future) | Planned |
---

## Module Layout

```
carto/
├── domain/              Pure Pydantic models — no I/O
│   ├── models.py        Session, Run, Page, Action, Form, State
│   ├── observations.py  PageObservation, NetworkRequest/Response
│   ├── inferences.py    ActionInventory, NextActionDecision, FormFillPlan, StateDelta
│   ├── artifacts.py     Artifact, RoleProfile, Coverage, RiskSignal
│   ├── auth.py          RedactedValue, AuthEvidence, AuthContext
│   ├── events.py        Event, EventKind (15 types), factory functions
│   ├── approval.py      ApprovalRequest/Result, Auto/Interactive/CLI policies
│   ├── risk_input.py    RiskInput, RiskAssessment
│   ├── campaign.py      Campaign, RoleRunSummary, CampaignSummary
│   ├── role_surface.py  RoleSurface snapshot
│   └── role_diff.py     RoleDiffInput, VisibilityCategory, RoleSurfaceDelta, RoleDiffResult
├── contracts/           MessageEnvelope[T], Command union (9 types)
├── agents/              LLM reasoning (zero side effects)
│   ├── page_understanding.py, action_planner.py, form_filler.py
│   ├── state_diff.py, risk.py
│   └── prompts/         Structured prompt builders
├── llm/                 LLMClient protocol + OpenAI implementation
├── executor/            BrowserExecutor (Playwright) — only I/O boundary
├── export/              HAR 1.2 export with configurable redaction
├── analysis/            RoleDiffer — deterministic cross-role comparison
├── orchestrator/        Orchestrator (single-role) + CampaignRunner (multi-role)
├── storage/             SessionStore, EventLog (protocol + in-memory)
└── main.py              CLI (Typer)
```

---

## Setup

```bash
# Install uv (if not already present)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtualenv and install
uv sync

# Install Playwright browsers
uv run playwright install chromium
```

---

## Usage

### Single-Role Mapping

```bash
# With LLM agents
OPENAI_API_KEY=sk-... carto run \
    --url https://target-app.example.com \
    --model gpt-4o

# With credentials for login
OPENAI_API_KEY=sk-... carto run \
    --url https://target-app.example.com \
    --role-name admin \
    --role-username admin@example.com \
    --role-password '<password>' \
    --har-output /tmp/carto/run.har \
    --event-log-output /tmp/carto/events.json

# Without LLM agents (Phase 1 mode — navigate and capture only)
carto run --url https://target-app.example.com
```

### Multi-Role Campaign

Create a `roles.json` file:

```json
[
    {"name": "admin", "username": "admin@example.com", "password": "<admin-password>"},
    {"name": "viewer", "username": "viewer@example.com", "password": "<viewer-password>"},
    {"name": "editor", "username": "editor@example.com", "password": "<editor-password>"}
]
```

Run the campaign:

```bash
OPENAI_API_KEY=sk-... carto campaign \
    --url https://target-app.example.com \
    --roles roles.json \
    --model gpt-4o \
    --output-dir /tmp/carto/campaign \
    --har-output-dir /tmp/carto/campaign/har \
    --event-log-dir /tmp/carto/campaign/events
```

Output:
- `campaign_summary.json` — per-role summaries
- `diff_admin_vs_viewer.json` — cross-role surface diffs
- Per-role HAR and event log files

### Report Generation

Generate formatted reports from your campaign diffs:

```bash
carto report \
    --campaign-dir /tmp/carto/campaign \
    --format markdown \
    --output /tmp/carto/campaign/report.md \
    --with-llm-narrative
```

### Configuration & Multi-LLM Support

Instead of passing dozen of CLI flags, you can provide a JSON configuration file. Carto supports `openai` (and OpenAI-compatible endpoints like Qwen/vLLM/Ollama via `base_url`), `anthropic` (Claude), and `gemini` natively.

**carto_config.json**
```json
{
  "target_url": "https://target-app.example.com",
  "llm": {
    "provider": "anthropic",
    "model": "claude-3-5-sonnet-20241022",
    "api_key_env": "ANTHROPIC_API_KEY",
    "base_url": null
  },
  "orchestra": {
    "max_steps": 100,
    "headless": false
  }
}
```

```bash
# Run with config file (CLI args act as overrides)
carto run --config carto_config.json --role-name admin
```

*(Note: To use Anthropic or Gemini, install the optional dependencies: `uv pip install "carto[llms]"`. OpenRouter or Qwen only require the standard `openai` package and a custom `--llm-base-url`.)*

### Approval Gates

```bash
# CLI approval gate — prompts before sensitive actions
carto run --url https://target-app.example.com --approval-mode cli
```

Flags: logout clicks, credential submissions, destructive actions (delete/revoke), MFA steps, OAuth consent.

### HAR Export Redaction

```bash
# Redaction modes: exclude, redact, fingerprint, include
carto run --url https://example.com \
    --har-output /tmp/run.har \
    --har-redaction redact   # [REDACTED] replaces sensitive values
```

---

## Auth Safety

- All secrets stored as `RedactedValue` (SHA-256 fingerprint + masked preview)
- Sensitive keys auto-detected: tokens, sessions, passwords, CSRF, API keys
- HAR export applies configurable redaction to headers, cookies, and POST bodies
- Event log data payloads are redaction-safe
- Raw secrets never appear in LLM prompts, logs, or exported artifacts

See [auth.md](docs/auth.md) for full details.

---

## Testing

```bash
# Run all tests
uv run pytest tests/ -v

# Lint
uv run ruff check carto/

# Type-check
uv run mypy carto/
```

Current: **189 tests**, covering domain models, agents, event log, approval gates, HAR export, RiskAgent, campaign models, role surfaces, role diffing, report generation, and multi-LLM configuration.

---

## Current Limitations / Deferred

- **Token refresh automation** — detected but not automated
- **MFA / OAuth automation** — approval gates prepared, full automation deferred
- **Report generation** — typed diff data available, polished reports are Phase 4B
- **LLM-enhanced diff analysis** — foundation ready, LLM comparison deferred
- **True parallel role execution** — sequential only (safe auth isolation)
- **Persistent storage** — in-memory + JSON export; DB-backed is swappable via protocol
