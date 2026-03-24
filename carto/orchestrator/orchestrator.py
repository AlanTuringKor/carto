"""
Orchestrator — the top-level observe → infer → decide → execute loop.

The orchestrator coordinates all components without containing business
logic itself.  It:
1. Drives the run lifecycle (start, step, stop).
2. Issues commands to the executor.
3. Routes observations to agents.
4. Records state snapshots.
5. Decides when to stop based on agent signals.

Phase 1 notes:
- The LLM agents are stubs; the loop structure is correct and ready for
  Phase 2 agent integration.
- State is tracked in memory only; Phase 2 will persist to disk/DB.
- No concurrency — steps are sequential.
"""

from __future__ import annotations

from datetime import UTC

import structlog
from pydantic import BaseModel

from carto.contracts.commands import NavigateCommand, ScreenshotCommand
from carto.contracts.envelope import MessageEnvelope
from carto.domain.inferences import ActionInventory, NextActionDecision
from carto.domain.models import Run, RunStatus, State
from carto.domain.observations import ErrorObservation, PageObservation
from carto.executor.base import BaseExecutor
from carto.storage.session_store import SessionStore

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class OrchestratorConfig(BaseModel):
    """Tunable parameters for the orchestrator."""

    max_steps: int = 50
    screenshot_each_step: bool = False
    stop_on_agent_error: bool = False


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """
    Controls a single Run from initial navigation to completion.

    Construction
    ------------
    executor:
        A started BrowserExecutor (or any BaseExecutor implementation).
    store:
        Session/Run registry for persisting live state.
    page_agent:
        PageUnderstandingAgent instance (may be None during Phase 1 testing).
    planner_agent:
        ActionPlannerAgent instance (may be None during Phase 1 testing).
    config:
        Orchestrator tuning parameters.
    """

    def __init__(
        self,
        executor: BaseExecutor,
        store: SessionStore,
        page_agent: object | None = None,
        planner_agent: object | None = None,
        config: OrchestratorConfig | None = None,
    ) -> None:
        self._executor = executor
        self._store = store
        self._page_agent = page_agent
        self._planner_agent = planner_agent
        self._config = config or OrchestratorConfig()

    async def run(self, run: Run) -> Run:
        """
        Execute a full mapping run from start to stop.

        Returns the updated Run with final status and step count.
        """
        logger.info("orchestrator.run.start", run_id=run.run_id, url=run.start_url)

        self._store.update_run(run.model_copy(update={"status": RunStatus.RUNNING}))
        self._executor.set_run_id(run.run_id)  # type: ignore[attr-defined]

        state = State(
            run_id=run.run_id,
            current_url=run.start_url,
        )

        step = 0
        try:
            # ── Initial navigation ──────────────────────────────────────
            observation = await self._executor.execute(
                NavigateCommand(url=run.start_url)
            )
            step += 1

            if isinstance(observation, ErrorObservation):
                logger.error(
                    "orchestrator.initial_nav_failed",
                    run_id=run.run_id,
                    error=observation.message,
                )
                return self._finish_run(run, RunStatus.FAILED, step, observation.message)

            assert isinstance(observation, PageObservation)
            state = self._update_state(state, observation)

            # ── Main observe → infer → decide → execute loop ─────────────
            while step < self._config.max_steps:
                logger.info(
                    "orchestrator.step",
                    run_id=run.run_id,
                    step=step,
                    url=observation.url,
                )

                if self._config.screenshot_each_step:
                    await self._executor.execute(ScreenshotCommand())

                # ── Observe: page understanding agent ─────────────────
                inventory = await self._observe(observation, run)
                if inventory is None:
                    # Agent not wired yet (Phase 1) — stop gracefully
                    logger.info(
                        "orchestrator.no_agent", run_id=run.run_id, step=step
                    )
                    break

                # ── Decide: action planner agent ──────────────────────
                decision = await self._decide(inventory, state, run)
                if decision is None or decision.should_stop:
                    logger.info(
                        "orchestrator.stopping",
                        run_id=run.run_id,
                        reason=getattr(decision, "stop_reason", "no_decision"),
                    )
                    break

                # ── Execute ────────────────────────────────────────────
                command = self._decision_to_command(decision)
                if command is None:
                    logger.warning("orchestrator.unresolvable_decision", step=step)
                    break

                observation = await self._executor.execute(command)
                step += 1

                if isinstance(observation, ErrorObservation):
                    logger.error(
                        "orchestrator.step_error",
                        step=step,
                        error=observation.message,
                    )
                    if self._config.stop_on_agent_error:
                        break
                    continue

                assert isinstance(observation, PageObservation)
                state = self._update_state(state, observation)

        except Exception as exc:
            logger.exception("orchestrator.unhandled_error", run_id=run.run_id)
            return self._finish_run(run, RunStatus.FAILED, step, str(exc))

        return self._finish_run(run, RunStatus.COMPLETED, step)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _observe(
        self,
        observation: PageObservation,
        run: Run,
    ) -> ActionInventory | None:
        """Call the PageUnderstandingAgent if wired, else return None."""
        if self._page_agent is None:
            return None

        try:
            envelope: MessageEnvelope[PageObservation] = MessageEnvelope(
                source="orchestrator",
                target="page_understanding_agent",
                correlation_id=run.run_id,
                payload=observation,
            )
            result: MessageEnvelope[ActionInventory] = self._page_agent.run(envelope)  # type: ignore[union-attr]
            return result.payload
        except Exception as exc:
            logger.warning("orchestrator.page_agent_error", error=str(exc))
            return None

    async def _decide(
        self,
        inventory: ActionInventory,
        state: State,
        run: Run,
    ) -> NextActionDecision | None:
        """Call the ActionPlannerAgent if wired, else return None."""
        if self._planner_agent is None:
            return None

        try:
            envelope: MessageEnvelope[ActionInventory] = MessageEnvelope(
                source="orchestrator",
                target="action_planner_agent",
                correlation_id=run.run_id,
                payload=inventory,
            )
            result: MessageEnvelope[NextActionDecision] = self._planner_agent.run(  # type: ignore[union-attr]
                envelope
            )
            return result.payload
        except Exception as exc:
            logger.warning("orchestrator.planner_agent_error", error=str(exc))
            return None

    def _decision_to_command(
        self, decision: NextActionDecision
    ) -> NavigateCommand | None:
        """
        Convert a NextActionDecision into an executable Command.

        Phase 1: Only NavigateCommand is implemented.
        Phase 2: Expand to ClickCommand, FillCommand, etc.
        """
        from carto.contracts.commands import ClickCommand
        from carto.domain.models import ActionKind

        if decision.chosen_href:
            return NavigateCommand(url=decision.chosen_href)
        if decision.chosen_css_selector and decision.chosen_action_kind == ActionKind.CLICK:
            return ClickCommand(css_selector=decision.chosen_css_selector)  # type: ignore[return-value]
        return None

    @staticmethod
    def _update_state(state: State, observation: PageObservation) -> State:
        """Return a new State snapshot incorporating the latest observation."""
        return state.model_copy(
            update={
                "current_url": observation.final_url,
                "cookies": observation.cookies,
                "local_storage": observation.local_storage,
                "session_storage": observation.session_storage,
            }
        )

    def _finish_run(
        self,
        run: Run,
        status: RunStatus,
        step_count: int,
        error: str | None = None,
    ) -> Run:
        from datetime import datetime

        finished = run.model_copy(
            update={
                "status": status,
                "step_count": step_count,
                "finished_at": datetime.now(tz=UTC),
                "error": error,
            }
        )
        self._store.update_run(finished)
        logger.info(
            "orchestrator.run.complete",
            run_id=run.run_id,
            status=status,
            steps=step_count,
        )
        return finished
