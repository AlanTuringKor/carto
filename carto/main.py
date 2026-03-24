"""
Carto CLI — entry point.

Usage:
    carto run --url https://example.com --session-id my-session
    carto run --url https://example.com  # auto-generates session id
    carto run --url https://example.com --model gpt-4o  # with LLM agents
    carto run --url https://example.com --approval-mode cli  # with approval gates
    carto run --url https://example.com --har-output run.har  # with HAR export
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
        None, "--session-id", "-s", help="Session ID (auto-generated if omitted).",
    ),
    max_steps: int = typer.Option(50, "--max-steps", help="Maximum orchestrator steps."),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Run headless browser."),
    screenshot_dir: str = typer.Option(
        "/tmp/carto/screenshots", "--screenshot-dir", help="Screenshots directory.",
    ),
    output_dir: str = typer.Option(
        "/tmp/carto/output", "--output-dir", help="Run output directory.",
    ),
    screenshot_each_step: bool = typer.Option(
        False, "--screenshot-each-step", help="Capture screenshot on every step.",
    ),
    model: str = typer.Option("gpt-4o", "--model", "-m", help="LLM model name."),
    api_key_env: str = typer.Option(
        "OPENAI_API_KEY", "--api-key-env", help="Env var for API key.",
    ),
    debug_prompts: bool = typer.Option(
        False, "--debug-prompts", help="Store raw LLM prompts/responses.",
    ),
    role_name: str = typer.Option(None, "--role-name", help="Role name for auth."),
    role_username: str = typer.Option(None, "--role-username", help="Login username."),
    role_password: str = typer.Option(None, "--role-password", help="Login password."),
    approval_mode: str = typer.Option(
        "auto", "--approval-mode", help="Approval mode: auto, cli.",
    ),
    har_output: str = typer.Option(
        None, "--har-output", help="Path for HAR export.",
    ),
    har_redaction: str = typer.Option(
        "redact", "--har-redaction", help="HAR redaction: exclude, redact, fingerprint, include.",
    ),
    event_log_output: str = typer.Option(
        None, "--event-log-output", help="Path for event log JSON export.",
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
            model=model,
            api_key_env=api_key_env,
            debug_prompts=debug_prompts,
            role_name=role_name,
            role_username=role_username,
            role_password=role_password,
            approval_mode=approval_mode,
            har_output=har_output,
            har_redaction=har_redaction,
            event_log_output=event_log_output,
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
    approval_mode: str,
    har_output: str | None,
    har_redaction: str,
    event_log_output: str | None,
) -> None:
    structlog.contextvars.bind_contextvars(session_id=session_id)

    # ── Store ────────────────────────────────────────────────────────────
    store = SessionStore()
    session = store.create_session(Session(session_id=session_id, target_url=url))

    run_obj = store.create_run(Run(session_id=session_id, start_url=url))
    structlog.contextvars.bind_contextvars(run_id=run_obj.run_id)

    logger.info("carto.run.start", url=url, run_id=run_obj.run_id)

    # ── Event log ────────────────────────────────────────────────────────
    from carto.storage.event_log import InMemoryEventLog
    event_log = InMemoryEventLog()

    # ── Approval policy ──────────────────────────────────────────────────
    from carto.domain.approval import AutoApprovePolicy, CLIApprovalPolicy
    if approval_mode == "cli":
        approval_policy = CLIApprovalPolicy()
    else:
        approval_policy = AutoApprovePolicy()

    # ── HAR builder ──────────────────────────────────────────────────────
    har_builder = None
    if har_output:
        from carto.export.har import HarBuilder, HarExportConfig, HarRedactionPolicy
        try:
            policy = HarRedactionPolicy(har_redaction)
        except ValueError:
            policy = HarRedactionPolicy.REDACT
        har_config = HarExportConfig(
            header_policy=policy,
            cookie_policy=policy,
            body_policy=policy,
        )
        har_builder = HarBuilder(config=har_config)

    # ── LLM client + agents ─────────────────────────────────────────────
    page_agent = None
    planner_agent = None
    form_filler_agent = None
    state_diff_agent = None
    risk_agent = None

    api_key = os.environ.get(api_key_env)
    if api_key:
        from carto.agents.action_planner import ActionPlannerAgent
        from carto.agents.form_filler import FormFillerAgent
        from carto.agents.page_understanding import PageUnderstandingAgent
        from carto.agents.risk import RiskAgent
        from carto.agents.state_diff import StateDiffAgent
        from carto.llm.client import OpenAIClient

        llm = OpenAIClient(model=model, api_key=api_key)
        page_agent = PageUnderstandingAgent(llm, debug=debug_prompts)
        planner_agent = ActionPlannerAgent(llm, debug=debug_prompts)
        form_filler_agent = FormFillerAgent(llm, debug=debug_prompts)
        state_diff_agent = StateDiffAgent(llm, debug=debug_prompts)
        risk_agent = RiskAgent(llm, debug=debug_prompts)

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
        enable_approval_gates=(approval_mode != "auto"),
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
            risk_agent=risk_agent,
            config=orch_config,
            event_log=event_log,
            approval_policy=approval_policy,
            har_builder=har_builder,
            role_name=role_name,
            role_username=role_username,
            role_password=role_password,
        )
        finished_run = await orchestrator.run(run_obj)

    # ── Output ───────────────────────────────────────────────────────────
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_path = Path(output_dir) / f"{finished_run.run_id}.json"
    output_path.write_text(finished_run.model_dump_json(indent=2))

    # Export event log
    if event_log_output:
        event_log.export_json(run_obj.run_id, event_log_output)
        typer.echo(f"  Event log: {event_log_output}")

    # Export HAR
    if har_builder and har_output:
        har_builder.export_json(har_output)
        typer.echo(f"  HAR export: {har_output}")

    # Mark session completed
    store.update_session(
        session.model_copy(update={"status": SessionStatus.COMPLETED})
    )

    logger.info(
        "carto.run.done",
        status=finished_run.status,
        steps=finished_run.step_count,
        output=str(output_path),
        events=event_log.count,
    )
    typer.echo(f"\n✓ Run complete. Status: {finished_run.status}  Steps: {finished_run.step_count}")
    typer.echo(f"  Output: {output_path}")
    typer.echo(f"  Events: {event_log.count}")


@app.command()
def campaign(
    url: str = typer.Option(..., "--url", "-u", help="Target URL."),
    roles_file: str = typer.Option(
        ..., "--roles", "-r", help="JSON file with role profiles.",
    ),
    max_steps: int = typer.Option(50, "--max-steps", help="Maximum steps per role."),
    headless: bool = typer.Option(True, "--headless/--no-headless"),
    output_dir: str = typer.Option(
        "/tmp/carto/campaign", "--output-dir", help="Campaign output directory.",
    ),
    model: str = typer.Option("gpt-4o", "--model", "-m", help="LLM model name."),
    api_key_env: str = typer.Option(
        "OPENAI_API_KEY", "--api-key-env", help="Env var for API key.",
    ),
    debug_prompts: bool = typer.Option(False, "--debug-prompts"),
    approval_mode: str = typer.Option(
        "auto", "--approval-mode", help="Approval mode: auto, cli.",
    ),
    har_output_dir: str = typer.Option(
        None, "--har-output-dir", help="Directory for per-role HAR files.",
    ),
    event_log_dir: str = typer.Option(
        None, "--event-log-dir", help="Directory for per-role event log JSONs.",
    ),
) -> None:
    """Run a multi-role campaign against a target URL."""
    asyncio.run(
        _campaign_async(
            url=url,
            roles_file=roles_file,
            max_steps=max_steps,
            headless=headless,
            output_dir=output_dir,
            model=model,
            api_key_env=api_key_env,
            debug_prompts=debug_prompts,
            approval_mode=approval_mode,
            har_output_dir=har_output_dir,
            event_log_dir=event_log_dir,
        )
    )


async def _campaign_async(
    url: str,
    roles_file: str,
    max_steps: int,
    headless: bool,
    output_dir: str,
    model: str,
    api_key_env: str,
    debug_prompts: bool,
    approval_mode: str,
    har_output_dir: str | None,
    event_log_dir: str | None,
) -> None:
    import json as _json

    from carto.domain.approval import AutoApprovePolicy, CLIApprovalPolicy
    from carto.domain.artifacts import RoleProfile
    from carto.domain.campaign import Campaign
    from carto.executor.browser import BrowserExecutorConfig
    from carto.orchestrator.campaign_runner import CampaignRunner
    from carto.orchestrator.orchestrator import OrchestratorConfig

    # ── Load role profiles ───────────────────────────────────────────
    roles_data = _json.loads(Path(roles_file).read_text())
    role_profiles: list[RoleProfile] = []
    for rd in roles_data:
        rp = RoleProfile(
            session_id="campaign",
            name=rd["name"],
            username=rd.get("username"),
            password=rd.get("password"),
            description=rd.get("description"),
        )
        role_profiles.append(rp)

    if not role_profiles:
        typer.echo("Error: No role profiles found in roles file.", err=True)
        raise typer.Exit(1)

    campaign_obj = Campaign(
        target_url=url,
        name=f"campaign-{url}",
        role_profiles=role_profiles,
    )

    logger.info(
        "carto.campaign.start",
        campaign_id=campaign_obj.campaign_id,
        roles=[rp.name for rp in role_profiles],
    )

    # ── Config ───────────────────────────────────────────────────────
    exec_config = BrowserExecutorConfig(headless=headless)
    orch_config = OrchestratorConfig(
        max_steps=max_steps,
        enable_approval_gates=(approval_mode != "auto"),
    )

    if approval_mode == "cli":
        approval_policy = CLIApprovalPolicy()
    else:
        approval_policy = AutoApprovePolicy()

    # ── LLM agents ───────────────────────────────────────────────────
    page_agent = None
    planner_agent = None
    form_filler_agent = None
    state_diff_agent = None
    risk_agent = None

    api_key = os.environ.get(api_key_env)
    if api_key:
        from carto.agents.action_planner import ActionPlannerAgent
        from carto.agents.form_filler import FormFillerAgent
        from carto.agents.page_understanding import PageUnderstandingAgent
        from carto.agents.risk import RiskAgent
        from carto.agents.state_diff import StateDiffAgent
        from carto.llm.client import OpenAIClient

        llm = OpenAIClient(model=model, api_key=api_key)
        page_agent = PageUnderstandingAgent(llm, debug=debug_prompts)
        planner_agent = ActionPlannerAgent(llm, debug=debug_prompts)
        form_filler_agent = FormFillerAgent(llm, debug=debug_prompts)
        state_diff_agent = StateDiffAgent(llm, debug=debug_prompts)
        risk_agent = RiskAgent(llm, debug=debug_prompts)

    # ── Run campaign ─────────────────────────────────────────────────
    store = SessionStore()
    runner = CampaignRunner(
        store=store,
        executor_config=exec_config,
        orchestrator_config=orch_config,
        page_agent=page_agent,
        planner_agent=planner_agent,
        form_filler_agent=form_filler_agent,
        state_diff_agent=state_diff_agent,
        risk_agent=risk_agent,
        approval_policy=approval_policy,
    )

    summary, diff_results = await runner.run(campaign_obj)

    # ── Output ───────────────────────────────────────────────────────
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Campaign summary
    summary_path = Path(output_dir) / "campaign_summary.json"
    summary_path.write_text(summary.model_dump_json(indent=2))

    # Diff results
    for diff in diff_results:
        diff_path = Path(output_dir) / f"diff_{diff.role_a_name}_vs_{diff.role_b_name}.json"
        diff_path.write_text(diff.model_dump_json(indent=2))

    # Per-role event logs
    if event_log_dir:
        Path(event_log_dir).mkdir(parents=True, exist_ok=True)
        for role_name, log in runner.event_logs.items():
            run_id = campaign_obj.role_run_ids.get(role_name)
            if hasattr(log, "export_json") and run_id:
                log.export_json(run_id, str(Path(event_log_dir) / f"{role_name}.json"))

    # Per-role HAR
    if har_output_dir:
        Path(har_output_dir).mkdir(parents=True, exist_ok=True)
        for role_name, builder in runner.har_builders.items():
            builder.export_json(str(Path(har_output_dir) / f"{role_name}.har"))

    typer.echo(f"\n✓ Campaign complete.")
    typer.echo(f"  Roles: {len(summary.role_summaries)}")
    typer.echo(f"  Diffs: {len(diff_results)}")
    typer.echo(f"  Output: {output_dir}")

    for rs in summary.role_summaries:
        typer.echo(f"  [{rs.role_name}] status={rs.status} urls={rs.unique_urls} actions={rs.actions_discovered}")

    for diff in diff_results:
        typer.echo(f"  [{diff.role_a_name} vs {diff.role_b_name}] differences={diff.delta.total_differences}")


@app.command()
def version() -> None:
    """Print the Carto version."""
    from carto import __version__
    typer.echo(f"carto {__version__}")


if __name__ == "__main__":
    app()
