"""
Carto CLI — entry point.

Usage:
    carto run --url https://example.com --session-id my-session
    carto run --url https://example.com  # auto-generates session id
    carto run --url https://example.com --model gpt-4o  # with LLM agents

The CLI wires together all components and runs a single mapping session.
When an API key is available (via --api-key-env or OPENAI_API_KEY), LLM
agents are enabled for full autonomous mapping.
"""

from __future__ import annotations

import asyncio
import os
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
    model: str = typer.Option(
        "gpt-4o", "--model", "-m", help="LLM model name."
    ),
    api_key_env: str = typer.Option(
        "OPENAI_API_KEY",
        "--api-key-env",
        help="Environment variable containing the API key.",
    ),
    debug_prompts: bool = typer.Option(
        False, "--debug-prompts", help="Store raw LLM prompts/responses on inferences."
    ),
    role_name: str = typer.Option(None, "--role-name", help="Role name for auth context."),
    role_username: str = typer.Option(None, "--role-username", help="Username for login forms."),
    role_password: str = typer.Option(None, "--role-password", help="Password for login forms."),
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
            model=model,
            api_key_env=api_key_env,
            debug_prompts=debug_prompts,
            role_name=role_name,
            role_username=role_username,
            role_password=role_password,
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
    model: str,
    api_key_env: str,
    debug_prompts: bool,
    role_name: str | None,
    role_username: str | None,
    role_password: str | None,
) -> None:
    structlog.contextvars.bind_contextvars(session_id=session_id)

    # ── Store ────────────────────────────────────────────────────────────
    store = SessionStore()
    session = store.create_session(Session(session_id=session_id, target_url=url))

    run_obj = store.create_run(Run(session_id=session_id, start_url=url))
    structlog.contextvars.bind_contextvars(run_id=run_obj.run_id)

    logger.info("carto.run.start", url=url, run_id=run_obj.run_id)

    # ── LLM client + agents ─────────────────────────────────────────────
    page_agent = None
    planner_agent = None
    form_filler_agent = None
    state_diff_agent = None

    api_key = os.environ.get(api_key_env)
    if api_key:
        from carto.agents.action_planner import ActionPlannerAgent
        from carto.agents.form_filler import FormFillerAgent
        from carto.agents.page_understanding import PageUnderstandingAgent
        from carto.agents.state_diff import StateDiffAgent
        from carto.llm.client import OpenAIClient

        llm = OpenAIClient(model=model, api_key=api_key)
        page_agent = PageUnderstandingAgent(llm, debug=debug_prompts)
        planner_agent = ActionPlannerAgent(llm, debug=debug_prompts)
        form_filler_agent = FormFillerAgent(llm, debug=debug_prompts)
        state_diff_agent = StateDiffAgent(llm, debug=debug_prompts)

        logger.info("carto.agents.enabled", model=model)
    else:
        logger.warning(
            "carto.agents.disabled",
            reason=f"No API key found in ${api_key_env}. "
            "Run will navigate and capture observations only.",
        )

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
            page_agent=page_agent,
            planner_agent=planner_agent,
            form_filler_agent=form_filler_agent,
            state_diff_agent=state_diff_agent,
            config=orch_config,
            role_name=role_name,
            role_username=role_username,
            role_password=role_password,
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
