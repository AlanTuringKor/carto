# Carto — Architecture Overview

## Purpose

Carto is a modular-monolith system that autonomously maps authenticated web applications for penetration testing using LLM-driven agents and a real Playwright browser.

---

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         Orchestrator                            │
│   observe → page_understanding → action_planner → execute       │
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
│  (Phase 2)       │     │  (Phase 2)       │     │  (Phase 2)       │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

---

## Module Layout

```
carto/
├── domain/              Pure data — Pydantic V2, no I/O
│   ├── models.py        Session, Run, Page, Action, Form, Field, State
│   ├── observations.py  Observation, PageObservation, NetworkRequest/Response
│   ├── inferences.py    Inference, ActionInventory, NextActionDecision, stubs
│   └── artifacts.py     Artifact, RoleProfile, Coverage, RiskSignal
│
├── contracts/           Inter-component message types
│   ├── envelope.py      MessageEnvelope[T] — typed, timestamped, correlated
│   └── commands.py      Command union (9 subtypes) — discriminator-dispatched
│
├── agents/              LLM reasoning only — zero side effects
│   ├── base.py          BaseAgent[InputT, OutputT] + AgentError
│   ├── page_understanding.py  PageObservation → ActionInventory
│   ├── action_planner.py      ActionInventory → NextActionDecision
│   ├── form_filler.py         (Phase 2 interface)
│   ├── state_diff.py          (Phase 2 interface)
│   └── risk.py                (Phase 2 interface)
│
├── executor/            The ONLY side-effect boundary
│   ├── base.py          BaseExecutor (async context manager)
│   └── browser.py       BrowserExecutor — Playwright, network capture, DOM extraction
│
├── orchestrator/
│   └── orchestrator.py  Main loop + run lifecycle
│
├── storage/
│   └── session_store.py  In-memory Session/Run registry
│
└── main.py              Typer CLI
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

---

## Data Flow (One Step)

```
BrowserExecutor.execute(NavigateCommand)
    → PageObservation (url, html, elements, forms, network, cookies)
    → MessageEnvelope[PageObservation] → PageUnderstandingAgent.run()
        → LLM call
        → MessageEnvelope[ActionInventory] (discovered actions, forms, page summary)
    → MessageEnvelope[ActionInventory] → ActionPlannerAgent.run()
        → LLM call
        → MessageEnvelope[NextActionDecision] (chosen action, rationale)
    → Orchestrator._decision_to_command()
        → ClickCommand / NavigateCommand / FillCommand
    → BrowserExecutor.execute(next command)
    → ...
```

---

## Phase Roadmap

| Phase | Focus |
|---|---|
| **1 (current)** | Domain models, contracts, agent interfaces, browser executor, orchestrator skeleton |
| **2** | LLM integration for PageUnderstanding + ActionPlanner; FormFillerAgent; StateDiffAgent |
| **3** | RiskAgent; human approval gates; structured event log; HAR export |
| **4** | Multi-role runs; parallel role diffing; report generation |

---

## Running Locally

```bash
# Install
uv sync
uv run playwright install chromium

# Run (Phase 1 — no agents, 1 navigation + screenshot)
uv run carto run --url https://example.com

# Run tests
uv run pytest tests/ -v

# Type-check
uv run mypy carto/

# Lint
uv run ruff check carto/
```

---

## Adding an LLM Agent (Phase 2 Guide)

1. Subclass `BaseAgent[InputT, OutputT]`
2. Inject an LLM client at `__init__`
3. Implement `run(envelope)`:
   - Deserialise `envelope.payload`
   - Build a structured prompt
   - Call `self._llm.complete(prompt)`
   - Parse the JSON response into `OutputT`
   - Return `MessageEnvelope[OutputT](...)`
4. Wire into `Orchestrator.__init__` as a named parameter
5. Add tests under `tests/`

No other files need to change.
