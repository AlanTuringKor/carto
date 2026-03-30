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

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("carto_session.log", mode="a", encoding="utf-8")
    ]
)

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(colors=True),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
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
    url: str = typer.Option(None, "--url", "-u", help="Target URL to map (overrides config)."),
    config_file: str = typer.Option(None, "--config", "-c", help="Path to JSON config file."),
    session_id: str = typer.Option(None, "--session-id", "-s", help="Session ID (auto-generated if omitted)."),
    max_steps: int = typer.Option(50, "--max-steps", help="Maximum orchestrator steps."),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Run headless browser."),
    screenshot_dir: str = typer.Option("/tmp/carto/screenshots", "--screenshot-dir", help="Screenshots directory."),
    output_dir: str = typer.Option("/tmp/carto/output", "--output-dir", help="Run output directory."),
    screenshot_each_step: bool = typer.Option(False, "--screenshot-each-step", help="Capture screenshot on every step."),
    model: str = typer.Option("gpt-4o", "--model", "-m", help="LLM model name."),
    llm_provider: str = typer.Option("openai", "--llm-provider", help="openai, anthropic, gemini"),
    llm_base_url: str = typer.Option(None, "--llm-base-url", help="Custom base URL for LLM"),
    api_key_env: str = typer.Option("OPENAI_API_KEY", "--api-key-env", help="Env var for API key."),
    debug_prompts: bool = typer.Option(False, "--debug-prompts", help="Store raw LLM prompts/responses."),
    role_name: str = typer.Option(None, "--role-name", help="Role name for auth."),
    role_username: str = typer.Option(None, "--role-username", help="Login username."),
    role_password: str = typer.Option(None, "--role-password", help="Login password."),
    approval_mode: str = typer.Option("auto", "--approval-mode", help="Approval mode: auto, cli."),
    har_output: str = typer.Option(None, "--har-output", help="Path for HAR export."),
    har_redaction: str = typer.Option("redact", "--har-redaction", help="HAR redaction: exclude, redact, fingerprint, include."),
    event_log_output: str = typer.Option(None, "--event-log-output", help="Path for event log JSON export."),
) -> None:
    """Run a mapping session against a target URL."""
    import json as _json
    from carto.domain.config import CartoConfig

    # Load config if specified
    config = CartoConfig()
    if config_file:
        try:
            raw = Path(config_file).read_text()
            config = CartoConfig.model_validate_json(raw)
        except Exception as e:
            typer.echo(f"Error loading config file: {e}", err=True)
            raise typer.Exit(1)

    # Merge CLI args over config (prefer CLI if explicitly passed, but since Typer doesn't tell us, we use simple heuristics)
    final_url = url or config.target_url
    if not final_url:
        typer.echo("Error: --url or target_url in config must be provided.", err=True)
        raise typer.Exit(1)

    final_model = config.llm.model if model == "gpt-4o" and config.llm.model else model
    final_provider = config.llm.provider if llm_provider == "openai" and config.llm.provider != "openai" else llm_provider
    final_base_url = config.llm.base_url if not llm_base_url else llm_base_url
    final_api_key_env = config.llm.api_key_env if api_key_env == "OPENAI_API_KEY" and config.llm.api_key_env != "OPENAI_API_KEY" else api_key_env

    final_role_name = role_name or config.auth.role_name
    final_role_username = role_username or config.auth.role_username
    final_role_password = role_password or config.auth.role_password

    final_max_steps = max_steps if max_steps != 50 else config.orchestra.max_steps
    final_headless = headless if headless is True else config.orchestra.headless
    final_approval = approval_mode if approval_mode != "auto" else config.orchestra.approval_mode

    asyncio.run(
        _run_async(
            url=final_url,
            session_id=session_id or str(uuid.uuid4()),
            max_steps=final_max_steps,
            headless=final_headless,
            screenshot_dir=screenshot_dir,
            output_dir=output_dir,
            screenshot_each_step=screenshot_each_step,
            model=final_model,
            provider=final_provider,
            base_url=final_base_url,
            api_key_env=final_api_key_env,
            api_key_explicit=config.llm.api_key,
            debug_prompts=debug_prompts,
            role_name=final_role_name,
            role_username=final_role_username,
            role_password=final_role_password,
            approval_mode=final_approval,
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
    provider: str,
    base_url: str | None,
    api_key_env: str,
    api_key_explicit: str | None,
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

    api_key = api_key_explicit or os.environ.get(api_key_env)
    if api_key:
        from carto.agents.action_planner import ActionPlannerAgent
        from carto.agents.form_filler import FormFillerAgent
        from carto.agents.page_understanding import PageUnderstandingAgent
        from carto.agents.state_diff import StateDiffAgent
        from carto.llm.client import create_llm_client

        try:
            llm = create_llm_client(provider=provider, model=model, api_key=api_key, base_url=base_url)
            page_agent = PageUnderstandingAgent(llm, debug=debug_prompts)
            planner_agent = ActionPlannerAgent(llm, debug=debug_prompts)
            form_filler_agent = FormFillerAgent(llm, debug=debug_prompts)
            state_diff_agent = StateDiffAgent(llm, debug=debug_prompts)
            logger.info("carto.agents.enabled", provider=provider, model=llm.model_name)
        except Exception as e:
            logger.error("carto.agents.init_failed", error=str(e))
            typer.echo(f"Error initializing LLM client: {e}", err=True)
            raise typer.Exit(1)
    else:
        logger.warning(
            "carto.agents.disabled",
            reason=f"No API key provided explicitly or via ${api_key_env}. "
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
    url: str = typer.Option(None, "--url", "-u", help="Target URL (overrides config)."),
    config_file: str = typer.Option(None, "--config", "-c", help="Path to JSON config file."),
    roles_file: str = typer.Option(..., "--roles", "-r", help="JSON file with role profiles."),
    max_steps: int = typer.Option(50, "--max-steps", help="Maximum steps per role."),
    headless: bool = typer.Option(True, "--headless/--no-headless"),
    output_dir: str = typer.Option("/tmp/carto/campaign", "--output-dir", help="Campaign output directory."),
    model: str = typer.Option("gpt-4o", "--model", "-m", help="LLM model name."),
    llm_provider: str = typer.Option("openai", "--llm-provider", help="openai, anthropic, gemini"),
    llm_base_url: str = typer.Option(None, "--llm-base-url", help="Custom base URL for LLM"),
    api_key_env: str = typer.Option("OPENAI_API_KEY", "--api-key-env", help="Env var for API key."),
    debug_prompts: bool = typer.Option(False, "--debug-prompts"),
    approval_mode: str = typer.Option("auto", "--approval-mode", help="Approval mode: auto, cli."),
    har_output_dir: str = typer.Option(None, "--har-output-dir", help="Directory for per-role HAR files."),
    event_log_dir: str = typer.Option(None, "--event-log-dir", help="Directory for per-role event log JSONs."),
) -> None:
    """Run a multi-role campaign against a target URL."""
    from carto.domain.config import CartoConfig

    # Load config if specified
    config = CartoConfig()
    if config_file:
        try:
            raw = Path(config_file).read_text()
            config = CartoConfig.model_validate_json(raw)
        except Exception as e:
            typer.echo(f"Error loading config file: {e}", err=True)
            raise typer.Exit(1)

    # Merge CLI args over config
    final_url = url or config.target_url
    if not final_url:
        typer.echo("Error: --url or target_url in config must be provided.", err=True)
        raise typer.Exit(1)

    final_model = config.llm.model if model == "gpt-4o" and config.llm.model else model
    final_provider = config.llm.provider if llm_provider == "openai" and config.llm.provider != "openai" else llm_provider
    final_base_url = config.llm.base_url if not llm_base_url else llm_base_url
    final_api_key_env = config.llm.api_key_env if api_key_env == "OPENAI_API_KEY" and config.llm.api_key_env != "OPENAI_API_KEY" else api_key_env

    final_max_steps = max_steps if max_steps != 50 else config.orchestra.max_steps
    final_headless = headless if headless is True else config.orchestra.headless
    final_approval = approval_mode if approval_mode != "auto" else config.orchestra.approval_mode

    asyncio.run(
        _campaign_async(
            url=final_url,
            roles_file=roles_file,
            max_steps=final_max_steps,
            headless=final_headless,
            output_dir=output_dir,
            model=final_model,
            provider=final_provider,
            base_url=final_base_url,
            api_key_env=final_api_key_env,
            api_key_explicit=config.llm.api_key,
            debug_prompts=debug_prompts,
            approval_mode=final_approval,
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
    provider: str,
    base_url: str | None,
    api_key_env: str,
    api_key_explicit: str | None,
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

    api_key = api_key_explicit or os.environ.get(api_key_env)
    if api_key:
        from carto.agents.action_planner import ActionPlannerAgent
        from carto.agents.form_filler import FormFillerAgent
        from carto.agents.page_understanding import PageUnderstandingAgent
        from carto.agents.state_diff import StateDiffAgent
        from carto.llm.client import create_llm_client

        try:
            llm = create_llm_client(provider=provider, model=model, api_key=api_key, base_url=base_url)
            page_agent = PageUnderstandingAgent(llm, debug=debug_prompts)
            planner_agent = ActionPlannerAgent(llm, debug=debug_prompts)
            form_filler_agent = FormFillerAgent(llm, debug=debug_prompts)
            state_diff_agent = StateDiffAgent(llm, debug=debug_prompts)
        except Exception as e:
            logger.error("carto.agents.init_failed", error=str(e))
            typer.echo(f"Error initializing LLM client: {e}", err=True)
            raise typer.Exit(1)

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
        approval_policy=approval_policy,
    )

    summary, diff_results = await runner.run(campaign_obj)

    # ── Output ───────────────────────────────────────────────────────
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Compile the canonical schema map
    from carto.analysis.map_assembler import MapAssembler
    assembler = MapAssembler()
    schema_map = assembler.assemble(
        summary=summary,
        event_logs=runner.event_logs,
        store=store,
    )
    schema_path = Path(output_dir) / "webapp_security_map.json"
    schema_path.write_text(schema_map.model_dump_json(indent=2))

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
    typer.echo(f"  Schema: {schema_path}")

    for rs in summary.role_summaries:
        typer.echo(f"  [{rs.role_name}] status={rs.status} urls={rs.unique_urls} actions={rs.actions_discovered}")

    for diff in diff_results:
        typer.echo(f"  [{diff.role_a_name} vs {diff.role_b_name}] differences={diff.delta.total_differences}")


@app.command()
def report(
    campaign_dir: str = typer.Option(..., "--campaign-dir", "-d", help="Directory with campaign output files."),
    config_file: str = typer.Option(None, "--config", "-c", help="Path to JSON config file."),
    output: str = typer.Option(None, "--output", "-o", help="Output file path (default: stdout)."),
    fmt: str = typer.Option("markdown", "--format", "-f", help="Output format: markdown, json, html."),
    with_llm_narrative: bool = typer.Option(False, "--with-llm-narrative", help="Enrich with LLM-generated narrative."),
    model: str = typer.Option("gpt-4o", "--model", "-m", help="LLM model name."),
    llm_provider: str = typer.Option("openai", "--llm-provider", help="openai, anthropic, gemini"),
    llm_base_url: str = typer.Option(None, "--llm-base-url", help="Custom base URL for LLM"),
    api_key_env: str = typer.Option("OPENAI_API_KEY", "--api-key-env", help="Env var for API key."),
) -> None:
    """Generate a report from a completed campaign."""
    import json as _json

    from carto.analysis.report_assembler import ReportAssembler
    from carto.domain.campaign import CampaignSummary
    from carto.domain.role_diff import RoleDiffResult
    from carto.domain.role_surface import RoleSurface
    from carto.export.renderers import HtmlRenderer, JsonRenderer, MarkdownRenderer

    campaign_path = Path(campaign_dir)
    if not campaign_path.exists():
        typer.echo(f"Error: campaign directory not found: {campaign_dir}", err=True)
        raise typer.Exit(1)

    # Load campaign summary
    summary_file = campaign_path / "campaign_summary.json"
    if not summary_file.exists():
        typer.echo("Error: campaign_summary.json not found.", err=True)
        raise typer.Exit(1)

    summary = CampaignSummary.model_validate_json(summary_file.read_text())

    # Load diff results
    diffs: list[RoleDiffResult] = []
    for f in sorted(campaign_path.glob("diff_*.json")):
        diffs.append(RoleDiffResult.model_validate_json(f.read_text()))

    # Build surfaces from summary (lightweight reconstruction)
    surfaces: dict[str, RoleSurface] = {}
    for rs in summary.role_summaries:
        surfaces[rs.role_name] = RoleSurface(
            role_name=rs.role_name,
            run_id=rs.run_id,
            auth_state=rs.auth_state,
            step_count=rs.step_count,
        )

    # Optional LLM narrative
    narratives = None
    if with_llm_narrative:
        from carto.domain.config import CartoConfig
        # Load config if specified
        config = CartoConfig()
        if config_file:
            try:
                raw = Path(config_file).read_text()
                config = CartoConfig.model_validate_json(raw)
            except Exception as e:
                typer.echo(f"Error loading config file: {e}", err=True)
                raise typer.Exit(1)
                
        final_model = config.llm.model if model == "gpt-4o" and config.llm.model else model
        final_provider = config.llm.provider if llm_provider == "openai" and config.llm.provider != "openai" else llm_provider
        final_base_url = config.llm.base_url if not llm_base_url else llm_base_url
        final_api_key_env = config.llm.api_key_env if api_key_env == "OPENAI_API_KEY" and config.llm.api_key_env != "OPENAI_API_KEY" else api_key_env

        api_key = config.llm.api_key or os.environ.get(final_api_key_env)
        if not api_key:
            typer.echo(f"Warning: neither config api_key nor {final_api_key_env} set, skipping LLM narrative.", err=True)
        elif diffs:
            from carto.agents.diff_narrative import DiffNarrativeAgent, DiffNarrativeInput
            from carto.contracts.envelope import MessageEnvelope
            from carto.domain.diff_narrative import DiffNarrative
            from carto.llm.client import create_llm_client

            try:
                llm = create_llm_client(provider=final_provider, model=final_model, api_key=api_key, base_url=final_base_url)
            except Exception as e:
                typer.echo(f"Error initializing LLM client: {e}", err=True)
                raise typer.Exit(1)
                
            agent = DiffNarrativeAgent(llm)
            narratives = []

            for diff in diffs:
                surface_a = surfaces.get(diff.role_a_name, RoleSurface(role_name=diff.role_a_name, run_id=""))
                surface_b = surfaces.get(diff.role_b_name, RoleSurface(role_name=diff.role_b_name, run_id=""))
                env = MessageEnvelope(
                    payload=DiffNarrativeInput(diff=diff, surface_a=surface_a, surface_b=surface_b),
                    source="cli",
                    target="diff_narrative_agent",
                    correlation_id=diff.campaign_id,
                )
                result = agent.run(env)
                narratives.append(result.payload)

    # Assemble report
    assembler = ReportAssembler()
    report_obj = assembler.assemble(
        summary=summary,
        surfaces=surfaces,
        diffs=diffs,
        narratives=narratives,
    )

    # Render
    renderers = {
        "markdown": MarkdownRenderer,
        "json": JsonRenderer,
        "html": HtmlRenderer,
    }
    renderer_cls = renderers.get(fmt.lower())
    if not renderer_cls:
        typer.echo(f"Error: unsupported format '{fmt}'. Use: markdown, json, html.", err=True)
        raise typer.Exit(1)

    rendered = renderer_cls().render(report_obj)

    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(rendered)
        typer.echo(f"✓ Report written to {output} ({fmt})")
    else:
        typer.echo(rendered)


@app.command()
def version() -> None:
    """Print the Carto version."""
    from carto import __version__
    typer.echo(f"carto {__version__}")


if __name__ == "__main__":
    app()
