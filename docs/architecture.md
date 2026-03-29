# Carto — Architecture Overview

## Purpose

Carto is a modular-monolith system that autonomously maps authenticated web applications for penetration testing using LLM-driven agents and a real Playwright browser.

---

## Component Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                            Orchestrator                                  │
│   observe → page_understanding → action_planner → approve → exec │
│           → form_filler (login forms) → state_diff                       │
│   [EventLog]  [ApprovalPolicy]  [HarBuilder]                             │
└────┬──────────────────────┬────────────────────────┬────────────────────┘
     │                      │                        │
     ▼                      ▼                        ▼
┌──────────┐    ┌─────────────────────┐    ┌──────────────────┐
│ Browser  │    │  PageUnderstanding  │    │  ActionPlanner   │
│ Executor │    │      Agent          │    │     Agent        │
│(Playwright)   │  PageObservation    │    │  ActionInventory │
│ only I/O │    │  → ActionInventory  │    │ → NextActionDecision
└──────────┘    └─────────────────────┘    └──────────────────┘
     │
     ▼
┌──────────────────┐  ┌──────────────────┐
│  FormFiller      │  │  StateDiff       │
│  Agent           │  │  Agent           │
│  FormFillerInput │  │  StateDiffInput  │
│  → FormFillPlan  │  │  → StateDelta    │
└──────────────────┘  └──────────────────┘
     │
     ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  LLM Client      │  │  Redaction       │  │  Event Log       │
│  (OpenAI)        │  │  Utilities       │  │  (audit trail)   │
│  Protocol-based  │  │  Auth Evidence   │  │  Protocol-based  │
└──────────────────┘  └──────────────────┘  └──────────────────┘
                ┌──────────────────┐  ┌──────────────────┐
                │  Approval Gates  │  │  HAR Export      │
                │  Policy-based    │  │  Redaction-safe  │
                └──────────────────┘  └──────────────────┘
```

---

## Module Layout

```
carto/
├── domain/              Pure data — Pydantic V2, no I/O
│   ├── models.py        Session, Run, Page, Action, Form, Field, State, AuthState
│   ├── observations.py  Observation, PageObservation, NetworkRequest/Response
│   ├── inferences.py    Inference, ActionInventory, NextActionDecision,
│   │                    FormFillerInput, FormFillPlan, StateDiffInput, StateDelta
│   ├── artifacts.py     Artifact, RoleProfile, Coverage
│   ├── auth.py          RedactedValue, AuthMechanism, AuthEvidence, AuthContext,
│   │                    LoginFlowObservation, AuthTransition
│   ├── events.py        Event, EventKind (15 kinds), typed factory functions
│   ├── approval.py      ApprovalRequest, ApprovalResult, ApprovalPolicy,
│   │                    AutoApprovePolicy, InteractiveApprovalPolicy, CLIApprovalPolicy
│   ├── campaign.py      Campaign, RoleRunSummary, CampaignSummary
│   ├── role_surface.py  RoleSurface snapshot
│   ├── role_diff.py     RoleDiffInput, VisibilityCategory, RoleSurfaceDelta, RoleDiffResult
│   ├── config.py        CartoConfig, LLMConfig, AuthConfig, OrchestratorConfigOverrides
│   ├── diff_narrative.py DiffNarrative, ReportInsight, InsightSeverity
│   └── report.py        CampaignReport, ReportSection
│
├── contracts/           Inter-component message types
│   ├── envelope.py      MessageEnvelope[T] — typed, timestamped, correlated
│   └── commands.py      Command union (9 subtypes) — discriminator-dispatched
│
├── agents/              LLM reasoning only — zero side effects
│   ├── base.py          BaseAgent[InputT, OutputT] + AgentError
│   ├── page_understanding.py  PageObservation → ActionInventory (LLM-backed)
│   ├── action_planner.py      ActionInventory → NextActionDecision (LLM-backed)
│   ├── form_filler.py         FormFillerInput → FormFillPlan (LLM-backed)
│   ├── state_diff.py          StateDiffInput → StateDelta (LLM-backed)
│   ├── diff_narrative.py      RoleDiffResult → DiffNarrative (LLM-backed)
│   └── prompts/               Structured prompt builders
│       ├── page_understanding.py
│       ├── action_planner.py
│       ├── form_filler.py
│       ├── state_diff.py│
├── llm/                 LLM client abstraction
│   └── client.py        LLMClient protocol + OpenAI/Anthropic/Gemini implementations
│
├── utils/               Shared utilities
│   └── redaction.py     Redaction, sensitive key detection, auth evidence extraction
│
├── executor/            The ONLY side-effect boundary
│   ├── base.py          BaseExecutor (async context manager)
│   └── browser.py       BrowserExecutor — Playwright, network capture, DOM extraction
│
├── export/              Evidence export
│   └── har.py           HarBuilder — HAR 1.2 export with configurable redaction
│
├── analysis/            Cross-role comparison
│   └── role_differ.py   RoleDiffer — deterministic set-based surface comparison
│
├── orchestrator/
│   ├── orchestrator.py  Main loop + event log + approval gates + agent wiring
│   └── campaign_runner.py  Multi-role campaign execution + surface capture
│
├── storage/
│   ├── session_store.py In-memory Session/Run registry
│   └── event_log.py     EventLog protocol + InMemoryEventLog
│
└── main.py              Typer CLI with full Phase 3 wiring
```

---

## Core Principles

### 1. Observation ≠ Inference

Every fact captured by the browser lives in an `Observation` subclass. Every LLM-generated interpretation lives in an `Inference` subclass.

### 2. Typed Inter-Agent Communication

All agent messages are wrapped in `MessageEnvelope[T]`. No free-text strings or raw dicts.

### 3. The Executor Is the Only Side-Effect Boundary

Agents receive typed input, call an LLM, return typed output. Only `BrowserExecutor.execute(command)` performs I/O.

### 4. Typed Commands

Every action is a typed Command dispatched via `match command.kind`.

### 5. Auditability

Every `Inference` records `source_observation_id` and `agent_name`. Every `Observation` records `triggering_action_id`. The `EventLog` captures a structured audit trail of every step.

### 6. Redaction-Safe Auth Handling

All auth secrets are stored as `RedactedValue` objects. Raw values never appear in logs, prompts, exports, or reports.

### 7. Approval Gates (Phase 3)

The `ApprovalPolicy` protocol controls whether sensitive actions (destructive clicks, logout, credential submission, MFA, OAuth consent) require human approval before executor side effects.

### 8. Structured Event Log (Phase 3)

The `EventLog` records 14 event types across the full run lifecycle — from `run_started` to `error`. Events are redaction-safe and export to JSON.

### 9. HAR Export (Phase 3)

`HarBuilder` produces HAR 1.2 JSON from captured network data with configurable redaction policies (`exclude`/`redact`/`fingerprint`/`include`) for headers, cookies, and bodies.

---

## Data Flow (One Step)

```
BrowserExecutor.execute(NavigateCommand)
    → emit(command_issued_event)
    → PageObservation
    → emit(page_observed_event) + HarBuilder.add_observation()
    → PageUnderstandingAgent.run()
        → emit(inference_produced_event)
        → ActionInventory
    → [if login page] FormFillerAgent.run()
        → emit(form_fill_planned_event)
    → StateDiffAgent.run()
        → emit(state_diff_computed_event)
        → [if auth change] emit(auth_transition_event)
    → ActionPlannerAgent.run()
        → emit(decision_made_event)
    → ApprovalPolicy.requires_approval()
        → [if needed] emit(approval_requested_event + approval_resolved_event)
    → BrowserExecutor.execute(next command)
        → emit(command_issued_event + command_result_event)
```

---

## Phase Roadmap

| Phase | Focus | Status |
|---|---|---|
| **1** | Domain models, contracts, agent interfaces, browser executor, orchestrator skeleton | ✅ Complete |
| **2** | LLM integration for all agents; FormFillerAgent; StateDiffAgent; auth handling | ✅ Complete |
| **3** | Structured event log; approval gates; HAR export | ✅ Complete |
| **4A** | Multi-role campaigns; coordinated role diffing foundations | ✅ Complete |
| **4B** | Report generation; LLM-enhanced diff analysis | ✅ Substantially Complete |

---

## Multi-Role Campaign Flow (Phase 4A/4B)

```
CampaignRunner.run(campaign)
  for each RoleProfile:
    → create fresh BrowserExecutor (auth isolation)
    → create per-role EventLog + HarBuilder
    → Orchestrator.run(role_run)
    → build RoleSurface from event log
  after all roles:
    → RoleDiffer.diff() for each role pair
    → DiffNarrativeAgent.run(diff_result) (LLM interpretation)
    → CampaignReport assembled
```

---

## Running Locally

```bash
# Install
pip install -e ".[dev]"
playwright install chromium

# Single-role mapping
OPENAI_API_KEY=sk-... carto run --url https://example.com --model gpt-4o

# With credentials + approval gates + HAR export
OPENAI_API_KEY=sk-... carto run --url https://example.com \
    --role-name admin --role-username admin@test.com --role-password '<password>' \
    --approval-mode cli \
    --har-output /tmp/carto/run.har --har-redaction redact \
    --event-log-output /tmp/carto/events.json

# Multi-role campaign
OPENAI_API_KEY=sk-... carto campaign \
    --url https://example.com \
    --roles roles.json \
    --output-dir /tmp/carto/campaign

# Run without agents (Phase 1 mode)
carto run --url https://example.com

# Run tests
pytest tests/ -v
```

---

## Adding an LLM Agent

1. Create a response schema (`Pydantic BaseModel`) for the LLM output
2. Create a prompt builder in `carto/agents/prompts/`
3. Subclass `BaseAgent[InputT, OutputT]`
4. Accept `LLMClient` at `__init__`
5. Implement `run(envelope)`:
   - Build prompt via the prompt builder
   - Call `self._llm.complete(prompt, ResponseSchema)`
   - Map response fields into the output type
   - Return `MessageEnvelope[OutputT](...)`
6. Wire into `Orchestrator.__init__`
7. Add tests with `MockLLM` under `tests/`
