# Carto

**LLM-driven web application mapper for penetration testing.**

Carto autonomously explores authenticated web applications, maps their authenticated surface area, understands role and state differences, dissects forms and workflows, and produces structured, replayable artefacts for security teams.

---

## Architecture (Phase 1)

```
Observation layer      →  BrowserExecutor (Playwright, only side-effect boundary)
                       ↓
Domain models          →  PageObservation, NetworkRequest/Response, Action, Form, State
                       ↓
Agent layer (LLM)      →  PageUnderstandingAgent → ActionInventory
                          ActionPlannerAgent      → NextActionDecision
                          FormFillerAgent         → FieldValues          (Phase 2)
                          StateDiffAgent          → StateDelta           (Phase 2)
                          RiskAgent               → RiskSignal           (Phase 2)
                       ↓
Orchestrator           →  observe → infer → decide → execute loop
```

All agent communication is wrapped in a typed `MessageEnvelope`. Agents only return structured Pydantic objects — no free-text channel between components.

---

## Quick Start

```bash
# Install uv (if not already present)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtualenv and install
uv sync

# Install Playwright browsers
uv run playwright install chromium

# Run
uv run carto run --url https://example.com --session-id my-session
```

---

## Project Layout

```
carto/
├── domain/          Pure Pydantic models — no I/O
├── contracts/       MessageEnvelope, Command union
├── agents/          LLM reasoning components (no side effects)
├── executor/        BrowserExecutor — the only I/O boundary
├── orchestrator/    Main observe → decide → act loop
├── storage/         Session/Run registry
└── main.py          CLI entry point (Typer)
tests/
docs/
```

---

## Design Principles

- **Observation ≠ Inference** — facts observed by the browser are strictly separated from LLM-generated interpretations.
- **No free-text agent communication** — every message is a typed, versioned `MessageEnvelope[T]`.
- **Only the executor causes side effects** — agents reason and return structured output only.
- **Auditability first** — every decision includes the input that generated it, making runs fully replayable.
- **Phase-gated complexity** — Form Filler, State Diff, and Risk Agent are interface-ready but not implemented until Phase 2.

---

## Development

```bash
# Lint
uv run ruff check carto/

# Type-check
uv run mypy carto/

# Test
uv run pytest tests/ -v
```
