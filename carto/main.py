"""
Carto CLI — entry point.

Usage:
    carto run --url https://example.com --session-id my-session
    carto run --url https://example.com  # auto-generates session id

The CLI wires together all Phase 1 components and runs a single mapping
session.  LLM agents are not wired yet; the run will navigate to the
target URL, capture a full PageObservation and screenshot, then stop.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import structlog
import typer

from carto.domain.models import Run, Session, SessionStatus
from carto.executor.browser import BrowserExecutor, BrowserExecutorConfig
from carto.orchestrator.orchestrator import Orchestrator, OrchestratorConfig
from carto.storage.session_store import SessionStore

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)

app = typer.Typer(
    name="carto",
    help="LLM-driven web application mapper for penetration testing.",
    no_args_is_help=True,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def run(
    url: str = typer.Option(..., "--url", "-u", help="Target URL to map."),
    session_id: str = typer.Option(
        None,
        "--session-id",
        "-s",
        help="Session ID (auto-generated if omitted).",
    ),
    max_steps: int = typer.Option(50, "--max-steps", help="Maximum orchestrator steps."),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Run headless browser."),
    screenshot_dir: str = typer.Option(
        "/tmp/carto/screenshots",
        "--screenshot-dir",
        help="Directory for storing screenshots.",
    ),
    output_dir: str = typer.Option(
        "/tmp/carto/output",
        "--output-dir",
        help="Directory for run output JSON.",
    ),
    screenshot_each_step: bool = typer.Option(
        False, "--screenshot-each-step", help="Capture screenshot on every step."
    ),
) -> None:
    """Run a mapping session against a target URL."""
    asyncio.run(
        _run_async(
            url=url,
            session_id=session_id or str(uuid.uuid4()),
            max_steps=max_steps,
            headless=headless,
            screenshot_dir=screenshot_dir,
            output_dir=output_dir,
            screenshot_each_step=screenshot_each_step,
        )
    )


async def _run_async(
    url: str,
    session_id: str,
    max_steps: int,
    headless: bool,
    screenshot_dir: str,
    output_dir: str,
    screenshot_each_step: bool,
) -> None:
    structlog.contextvars.bind_contextvars(session_id=session_id)

    # ── Store ────────────────────────────────────────────────────────────
    store = SessionStore()
    session = store.create_session(Session(session_id=session_id, target_url=url))

    run_obj = store.create_run(Run(session_id=session_id, start_url=url))
    structlog.contextvars.bind_contextvars(run_id=run_obj.run_id)

    logger.info("carto.run.start", url=url, run_id=run_obj.run_id)

    # ── Executor config ──────────────────────────────────────────────────
    exec_config = BrowserExecutorConfig(
        headless=headless,
        screenshot_dir=screenshot_dir,
    )

    # ── Orchestrator config ──────────────────────────────────────────────
    orch_config = OrchestratorConfig(
        max_steps=max_steps,
        screenshot_each_step=screenshot_each_step,
    )

    # ── Run ──────────────────────────────────────────────────────────────
    async with BrowserExecutor(exec_config) as executor:
        orchestrator = Orchestrator(
            executor=executor,
            store=store,
            # Agents not wired yet — Phase 2
            page_agent=None,
            planner_agent=None,
            config=orch_config,
        )
        finished_run = await orchestrator.run(run_obj)

    # ── Output ───────────────────────────────────────────────────────────
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_path = Path(output_dir) / f"{finished_run.run_id}.json"
    output_path.write_text(finished_run.model_dump_json(indent=2))

    # Mark session completed
    store.update_session(
        session.model_copy(update={"status": SessionStatus.COMPLETED})
    )

    logger.info(
        "carto.run.done",
        status=finished_run.status,
        steps=finished_run.step_count,
        output=str(output_path),
    )
    typer.echo(f"\n✓ Run complete. Status: {finished_run.status}  Steps: {finished_run.step_count}")
    typer.echo(f"  Output: {output_path}")


@app.command()
def version() -> None:
    """Print the Carto version."""
    from carto import __version__
    typer.echo(f"carto {__version__}")


if __name__ == "__main__":
    app()
