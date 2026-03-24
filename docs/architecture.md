# Carto — Architecture Overview

## Purpose

Carto is a modular-monolith system that autonomously maps authenticated web applications for penetration testing using LLM-driven agents and a real Playwright browser.

---

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         Orchestrator                            │
│   observe → page_understanding → action_planner → execute       │
│           → form_filler (login forms) → state_diff              │
└────┬──────────────────────┬────────────────────────┬───────────┘
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
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  FormFiller      │     │  StateDiff       │     │  Risk            │
│  Agent           │     │  Agent           │     │  Agent           │
│  FormFillerInput │     │  StateDiffInput  │     │  (Phase 3)       │
│  → FormFillPlan  │     │  → StateDelta    │     │                  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
     │
     ▼
┌──────────────────┐     ┌──────────────────┐
│  LLM Client      │     │  Redaction       │
│  (OpenAI)        │     │  Utilities       │
│  Protocol-based  │     │  Auth Evidence   │
└──────────────────┘     └──────────────────┘
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
│   ├── artifacts.py     Artifact, RoleProfile, Coverage, RiskSignal
│   └── auth.py          RedactedValue, AuthMechanism, AuthEvidence, AuthContext,
│                        LoginFlowObservation, AuthTransition
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
│   ├── risk.py                (Phase 3 interface)
│   └── prompts/               Structured prompt builders
│       ├── page_understanding.py
│       ├── action_planner.py
│       ├── form_filler.py
│       └── state_diff.py
│
├── llm/                 LLM client abstraction
│   └── client.py        LLMClient protocol + OpenAIClient implementation
│
├── utils/               Shared utilities
│   └── redaction.py     Redaction, sensitive key detection, auth evidence extraction
│
├── executor/            The ONLY side-effect boundary
│   ├── base.py          BaseExecutor (async context manager)
│   └── browser.py       BrowserExecutor — Playwright, network capture, DOM extraction
│
├── orchestrator/
│   └── orchestrator.py  Main loop + run lifecycle + agent wiring
│
├── storage/
│   └── session_store.py In-memory Session/Run registry
│
└── main.py              Typer CLI with LLM agent wiring
```

---

## Core Principles

### 1. Observation ≠ Inference

Every fact captured by the browser lives in an `Observation` subclass. Every LLM-generated interpretation lives in an `Inference` subclass. This is enforced at the type level — they are distinct Pydantic models that cannot be confused.

```
PageObservation.html_content   ← fact: raw HTML
ActionInventory.page_summary   ← inference: LLM one-sentence description
```

### 2. Typed Inter-Agent Communication

All agent messages are wrapped in `MessageEnvelope[T]`. No agent communicates via free-text strings or raw dicts. The generic type parameter constrains the payload at the call site.

```python
env = MessageEnvelope[PageObservation](
    source="orchestrator",
    target="page_understanding_agent",
    correlation_id=run.run_id,
    payload=observation,
)
```

### 3. The Executor Is the Only Side-Effect Boundary

Agents receive typed input, call an LLM, return typed output. They never:
- Control a browser
- Write to disk
- Make HTTP requests
- Mutate shared state

Only `BrowserExecutor.execute(command)` does any of these things.

### 4. Typed Commands

The orchestrator never sends raw strings to the executor. Every action is a typed Command:

```python
Command = Union[
    NavigateCommand, ClickCommand, FillCommand, SelectCommand,
    ScreenshotCommand, WaitCommand, ScrollCommand, BackCommand, EvaluateCommand
]
```

The executor dispatches via `match command.kind`.

### 5. Auditability

Every `Inference` records `source_observation_id` and `agent_name`. Every `Observation` records `triggering_action_id`. This forms an unbroken chain from every decision back to the raw browser fact that triggered it.

### 6. Redaction-Safe Auth Handling (Phase 2)

All authentication secrets (tokens, session IDs, passwords, CSRF tokens) are stored as `RedactedValue` objects containing a SHA-256 fingerprint and masked preview. Raw values never appear in:
- Structured logs
- LLM prompts (only key names and redacted previews)
- Serialised inference objects

The `extract_auth_evidence()` utility scans cookies, headers, and web storage for auth-related artefacts, returning `AuthEvidence` objects with redacted values.

---

## Data Flow (One Step)

```
BrowserExecutor.execute(NavigateCommand)
    → PageObservation (url, html, elements, forms, network, cookies)
    → MessageEnvelope[PageObservation] → PageUnderstandingAgent.run()
        → LLM call (structured prompt with page content + auth hints)
        → MessageEnvelope[ActionInventory] (actions, forms, auth detection)
    → [if login page + forms] → FormFillerAgent.run()
        → LLM call (structured prompt with fields + role credentials)
        → MessageEnvelope[FormFillPlan] → Fill/Click commands
    → MessageEnvelope[ActionInventory] → ActionPlannerAgent.run()
        → LLM call (structured prompt with actions + exploration state)
        → MessageEnvelope[NextActionDecision] (chosen action, rationale)
    → Orchestrator._decision_to_command()
        → ClickCommand / NavigateCommand / FillCommand / SelectCommand
    → BrowserExecutor.execute(next command)
    → StateDiffAgent.run(before_state, after_state)
        → LLM call (structured prompt with state diffs)
        → MessageEnvelope[StateDelta] (auth changes, cookie diffs)
    → ...
```

---

## Phase Roadmap

| Phase | Focus | Status |
|---|---|---|
| **1** | Domain models, contracts, agent interfaces, browser executor, orchestrator skeleton | ✅ Complete |
| **2 (current)** | LLM integration for all agents; FormFillerAgent; StateDiffAgent; auth handling | ✅ Complete |
| **3** | RiskAgent; human approval gates; structured event log; HAR export | Planned |
| **4** | Multi-role runs; parallel role diffing; report generation | Planned |

---

## Running Locally

```bash
# Install
pip install -e ".[dev]"
playwright install chromium

# Run with LLM agents (requires OPENAI_API_KEY)
OPENAI_API_KEY=sk-... carto run --url https://example.com --model gpt-4o

# Run with credentials for login
OPENAI_API_KEY=sk-... carto run --url https://example.com \
    --role-name admin --role-username admin@test.com --role-password TestPass123

# Run without agents (Phase 1 mode — navigate + screenshot only)
carto run --url https://example.com

# Run tests
pytest tests/ -v

# Debug: store raw LLM prompts/responses
OPENAI_API_KEY=sk-... carto run --url https://example.com --debug-prompts
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
