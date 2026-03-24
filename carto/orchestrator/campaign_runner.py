"""
CampaignRunner — orchestrates multi-role mapping campaigns.

Executes a ``Campaign`` by running one ``Orchestrator`` per role profile
in sequence, capturing ``RoleSurface`` snapshots, and computing
cross-role diffs via ``RoleDiffer``.

Design:
    - Sequential execution (no parallelism) — each role gets a fresh
      browser context to ensure auth isolation.
    - Reuses the existing ``Orchestrator`` as-is per role.
    - ``RoleSurface`` is built from event log data after each role run.
    - ``RoleDiffer`` produces pairwise diffs for all role combinations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import combinations

import structlog

from carto.analysis.role_differ import RoleDiffer
from carto.domain.approval import ApprovalPolicy, AutoApprovePolicy
from carto.domain.artifacts import RoleProfile
from carto.domain.campaign import (
    Campaign,
    CampaignStatus,
    CampaignSummary,
    RoleRunSummary,
)
from carto.domain.events import EventKind
from carto.domain.models import AuthState, Run, RunStatus, Session
from carto.domain.role_diff import RoleDiffInput, RoleDiffResult
from carto.domain.role_surface import RoleSurface
from carto.executor.browser import BrowserExecutor, BrowserExecutorConfig
from carto.export.har import HarBuilder
from carto.orchestrator.orchestrator import Orchestrator, OrchestratorConfig
from carto.storage.event_log import EventLog, InMemoryEventLog
from carto.storage.session_store import SessionStore

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# CampaignRunner
# ---------------------------------------------------------------------------


class CampaignRunner:
    """
    Coordinates multi-role mapping campaigns.

    Construction
    ------------
    store:
        Session/Run registry.
    executor_config:
        BrowserExecutor configuration (reused per role).
    orchestrator_config:
        Orchestrator tuning (reused per role).
    page_agent, planner_agent, form_filler_agent, state_diff_agent, risk_agent:
        LLM agents (shared across roles).
    approval_policy:
        Approval gate policy.
    """

    def __init__(
        self,
        store: SessionStore,
        executor_config: BrowserExecutorConfig | None = None,
        orchestrator_config: OrchestratorConfig | None = None,
        page_agent: object | None = None,
        planner_agent: object | None = None,
        form_filler_agent: object | None = None,
        state_diff_agent: object | None = None,
        risk_agent: object | None = None,
        approval_policy: ApprovalPolicy | None = None,
    ) -> None:
        self._store = store
        self._exec_config = executor_config or BrowserExecutorConfig()
        self._orch_config = orchestrator_config or OrchestratorConfig()
        self._page_agent = page_agent
        self._planner_agent = planner_agent
        self._form_filler_agent = form_filler_agent
        self._state_diff_agent = state_diff_agent
        self._risk_agent = risk_agent
        self._approval_policy = approval_policy or AutoApprovePolicy()
        self._differ = RoleDiffer()

        # Per-role outputs
        self._event_logs: dict[str, EventLog] = {}
        self._har_builders: dict[str, HarBuilder] = {}
        self._surfaces: dict[str, RoleSurface] = {}

    @property
    def event_logs(self) -> dict[str, EventLog]:
        """Access per-role event logs (role_name → EventLog)."""
        return self._event_logs

    @property
    def har_builders(self) -> dict[str, HarBuilder]:
        """Access per-role HAR builders (role_name → HarBuilder)."""
        return self._har_builders

    @property
    def surfaces(self) -> dict[str, RoleSurface]:
        """Access per-role surfaces (role_name → RoleSurface)."""
        return self._surfaces

    async def run(self, campaign: Campaign) -> tuple[CampaignSummary, list[RoleDiffResult]]:
        """
        Execute all roles in a campaign and compute cross-role diffs.

        Returns (CampaignSummary, list[RoleDiffResult]).
        """
        logger.info(
            "campaign.start",
            campaign_id=campaign.campaign_id,
            target=campaign.target_url,
            roles=[rp.name for rp in campaign.role_profiles],
        )

        # Ensure session exists
        session_id = campaign.session_id or campaign.campaign_id
        try:
            self._store.get_session(session_id)
        except Exception:
            self._store.create_session(Session(
                session_id=session_id,
                target_url=campaign.target_url,
                name=campaign.name,
            ))

        role_summaries: list[RoleRunSummary] = []

        # ── Execute each role sequentially ──────────────────────────
        for role_profile in campaign.role_profiles:
            logger.info("campaign.role.start", role=role_profile.name)

            summary = await self._run_role(
                campaign=campaign,
                role_profile=role_profile,
                session_id=session_id,
            )
            role_summaries.append(summary)

            logger.info(
                "campaign.role.complete",
                role=role_profile.name,
                status=summary.status,
                urls=summary.unique_urls,
            )

        # ── Compute pairwise diffs ──────────────────────────────────
        diff_results: list[RoleDiffResult] = []
        role_names = list(self._surfaces.keys())

        for name_a, name_b in combinations(role_names, 2):
            diff_input = RoleDiffInput(
                role_a=self._surfaces[name_a],
                role_b=self._surfaces[name_b],
            )
            result = self._differ.diff_with_result(
                diff_input, campaign.campaign_id,
            )
            diff_results.append(result)
            logger.info(
                "campaign.diff.complete",
                role_a=name_a,
                role_b=name_b,
                differences=result.delta.total_differences,
            )

        # ── Build campaign summary ──────────────────────────────────
        summary = CampaignSummary(
            campaign_id=campaign.campaign_id,
            target_url=campaign.target_url,
            status=CampaignStatus.COMPLETED,
            role_summaries=role_summaries,
            diff_result_ids=[r.result_id for r in diff_results],
            completed_at=datetime.now(tz=UTC),
        )

        logger.info(
            "campaign.complete",
            campaign_id=campaign.campaign_id,
            roles=len(role_summaries),
            diffs=len(diff_results),
        )

        return summary, diff_results

    # ------------------------------------------------------------------
    # Per-role execution
    # ------------------------------------------------------------------

    async def _run_role(
        self,
        campaign: Campaign,
        role_profile: RoleProfile,
        session_id: str,
    ) -> RoleRunSummary:
        """Execute a single role's mapping run."""
        # Create per-role run
        run_obj = self._store.create_run(Run(
            session_id=session_id,
            start_url=campaign.target_url,
            role_profile_id=role_profile.role_profile_id,
        ))

        # Per-role event log and HAR
        event_log = InMemoryEventLog()
        har_builder = HarBuilder()

        self._event_logs[role_profile.name] = event_log
        self._har_builders[role_profile.name] = har_builder

        # Execute with a fresh browser context
        async with BrowserExecutor(self._exec_config) as executor:
            orchestrator = Orchestrator(
                executor=executor,
                store=self._store,
                page_agent=self._page_agent,
                planner_agent=self._planner_agent,
                form_filler_agent=self._form_filler_agent,
                state_diff_agent=self._state_diff_agent,
                risk_agent=self._risk_agent,
                config=self._orch_config,
                event_log=event_log,
                approval_policy=self._approval_policy,
                har_builder=har_builder,
                role_name=role_profile.name,
                role_username=role_profile.username,
                role_password=role_profile.password,
            )
            finished_run = await orchestrator.run(run_obj)

        # Build role surface from event log
        surface = self._build_surface(role_profile.name, run_obj.run_id, event_log)
        surface = surface.model_copy(update={
            "step_count": finished_run.step_count,
            "auth_state": (
                AuthState.AUTHENTICATED
                if any(
                    e.data.get("after_authenticated")
                    for e in event_log.get_events(run_obj.run_id, EventKind.AUTH_TRANSITION)
                )
                else AuthState.UNKNOWN
            ),
        })
        self._surfaces[role_profile.name] = surface

        # Count risk signals
        risk_events = event_log.get_events(run_obj.run_id, EventKind.RISK_SIGNAL)

        return RoleRunSummary(
            role_name=role_profile.name,
            run_id=run_obj.run_id,
            status=finished_run.status,
            step_count=finished_run.step_count,
            unique_urls=len(surface.urls),
            actions_discovered=len(surface.action_labels),
            forms_discovered=len(surface.form_urls),
            auth_state=surface.auth_state,
            risk_signal_count=len(risk_events),
            error=finished_run.error,
        )

    # ------------------------------------------------------------------
    # Surface builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_surface(
        role_name: str,
        run_id: str,
        event_log: EventLog,
    ) -> RoleSurface:
        """
        Build a RoleSurface from event log data.

        Extracts URLs from page_observed events, action/form counts
        from inference_produced events.
        """
        urls: set[str] = set()
        action_labels: set[str] = set()
        form_urls: set[str] = set()
        page_clusters: set[str] = set()
        api_endpoints: set[str] = set()

        # Collect from page observations
        for event in event_log.get_events(run_id, EventKind.PAGE_OBSERVED):
            url = event.data.get("url")
            if url:
                urls.add(url)
            if event.data.get("form_count", 0) > 0 and url:
                form_urls.add(url)

        # Collect from inferences
        for event in event_log.get_events(run_id, EventKind.INFERENCE_PRODUCED):
            summary = event.data.get("summary", {})
            if isinstance(summary, dict):
                cluster = summary.get("page_cluster")
                if cluster:
                    page_clusters.add(cluster)

        # Collect from decisions (action labels)
        for event in event_log.get_events(run_id, EventKind.DECISION_MADE):
            label = event.data.get("action_label")
            if label:
                action_labels.add(label)

        return RoleSurface(
            role_name=role_name,
            run_id=run_id,
            urls=urls,
            action_labels=action_labels,
            form_urls=form_urls,
            api_endpoints=api_endpoints,
            page_clusters=page_clusters,
        )
