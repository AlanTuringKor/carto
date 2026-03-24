"""
Orchestrator — the top-level observe → infer → decide → execute loop.

The orchestrator coordinates all components without containing business
logic itself.  It:
1. Drives the run lifecycle (start, step, stop).
2. Issues commands to the executor.
3. Routes observations to agents (page understanding, action planner,
   form filler, state diff).
4. Records state snapshots and detects auth transitions.
5. Decides when to stop based on agent signals.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from carto.agents.action_planner import ActionPlannerAgent
from carto.agents.form_filler import FormFillerAgent
from carto.agents.page_understanding import PageUnderstandingAgent
from carto.agents.state_diff import StateDiffAgent
from carto.contracts.commands import (
    ClickCommand,
    FillCommand,
    NavigateCommand,
    ScreenshotCommand,
    SelectCommand,
)
from carto.contracts.envelope import MessageEnvelope
from carto.domain.inferences import (
    ActionInventory,
    DiscoveredField,
    FormFillerInput,
    FormFillPlan,
    NextActionDecision,
    StateDelta,
    StateDiffInput,
)
from carto.domain.models import ActionKind, AuthState, Run, RunStatus, State
from carto.domain.observations import ErrorObservation, PageObservation
from carto.executor.base import BaseExecutor
from carto.storage.session_store import SessionStore
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class OrchestratorConfig(BaseModel):
    """Tunable parameters for the orchestrator."""

    max_steps: int = 50
    screenshot_each_step: bool = False
    stop_on_agent_error: bool = False
    enable_form_filling: bool = True
    enable_state_diff: bool = True


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
        PageUnderstandingAgent instance.
    planner_agent:
        ActionPlannerAgent instance.
    form_filler_agent:
        FormFillerAgent instance (optional — form filling disabled if None).
    state_diff_agent:
        StateDiffAgent instance (optional — state diffing disabled if None).
    config:
        Orchestrator tuning parameters.
    role_name:
        Active role name for form filling context.
    role_username:
        Credentials for login forms.
    role_password:
        Credentials for login forms.
    """

    def __init__(
        self,
        executor: BaseExecutor,
        store: SessionStore,
        page_agent: PageUnderstandingAgent | None = None,
        planner_agent: ActionPlannerAgent | None = None,
        form_filler_agent: FormFillerAgent | None = None,
        state_diff_agent: StateDiffAgent | None = None,
        config: OrchestratorConfig | None = None,
        role_name: str | None = None,
        role_username: str | None = None,
        role_password: str | None = None,
    ) -> None:
        self._executor = executor
        self._store = store
        self._page_agent = page_agent
        self._planner_agent = planner_agent
        self._form_filler_agent = form_filler_agent
        self._state_diff_agent = state_diff_agent
        self._config = config or OrchestratorConfig()
        self._role_name = role_name
        self._role_username = role_username
        self._role_password = role_password

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
            prev_state = state
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
                    logger.info(
                        "orchestrator.no_agent", run_id=run.run_id, step=step
                    )
                    break

                # ── State diff (if enabled) ───────────────────────────
                if self._config.enable_state_diff and self._state_diff_agent:
                    delta = await self._diff_state(
                        prev_state, state, observation, run
                    )
                    if delta and delta.login_detected:
                        state = state.model_copy(
                            update={"auth_state": AuthState.AUTHENTICATED}
                        )
                    elif delta and delta.logout_detected:
                        state = state.model_copy(
                            update={"auth_state": AuthState.UNAUTHENTICATED}
                        )

                # ── Form filling (if login page detected) ─────────────
                if (
                    self._config.enable_form_filling
                    and self._form_filler_agent
                    and inventory.is_login_page
                    and inventory.discovered_forms
                    and state.auth_state != AuthState.AUTHENTICATED
                ):
                    fill_result = await self._fill_form(
                        inventory, observation, run
                    )
                    if fill_result:
                        observation, state, step = fill_result
                        prev_state = state
                        continue

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

                prev_state = state
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
            result: MessageEnvelope[ActionInventory] = self._page_agent.run(envelope)
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
            # Inject current state into the planner
            if hasattr(self._planner_agent, "set_state"):
                self._planner_agent.set_state(state)

            envelope: MessageEnvelope[ActionInventory] = MessageEnvelope(
                source="orchestrator",
                target="action_planner_agent",
                correlation_id=run.run_id,
                payload=inventory,
            )
            result: MessageEnvelope[NextActionDecision] = self._planner_agent.run(
                envelope
            )
            return result.payload
        except Exception as exc:
            logger.warning("orchestrator.planner_agent_error", error=str(exc))
            return None

    async def _fill_form(
        self,
        inventory: ActionInventory,
        observation: PageObservation,
        run: Run,
    ) -> tuple[PageObservation, State, int] | None:
        """
        Attempt to fill and submit a login form.

        Returns (new_observation, new_state, new_step_count) if successful,
        or None if form filling failed or was skipped.
        """
        if not self._form_filler_agent or not inventory.discovered_forms:
            return None

        # Use the first form (usually the login form on a login page)
        form_fields = inventory.discovered_forms[0]

        # Detect CSRF field
        csrf_name = None
        csrf_value = None
        for field in form_fields:
            if field.name and any(
                hint in field.name.lower()
                for hint in ["csrf", "xsrf", "_token", "authenticity"]
            ):
                csrf_name = field.name
                # Try to find the CSRF value from raw form data
                for form_raw in observation.forms_raw:
                    for raw_field in form_raw.fields_raw:
                        if raw_field.get("name") == csrf_name:
                            csrf_value = raw_field.get("value", "")
                            break

        form_input = FormFillerInput(
            form_fields=form_fields,
            form_selector=inventory.login_form_selector,
            page_url=observation.url,
            page_summary=inventory.page_summary,
            is_login_form=inventory.is_login_page,
            role_name=self._role_name,
            role_username=self._role_username,
            role_password=self._role_password,
            csrf_field_name=csrf_name,
            csrf_field_value=csrf_value,
        )

        try:
            envelope: MessageEnvelope[FormFillerInput] = MessageEnvelope(
                source="orchestrator",
                target="form_filler_agent",
                correlation_id=run.run_id,
                payload=form_input,
            )
            result = self._form_filler_agent.run(envelope)
            plan = result.payload
        except Exception as exc:
            logger.warning("orchestrator.form_filler_error", error=str(exc))
            return None

        return await self._execute_form_fill(plan, run)

    async def _execute_form_fill(
        self,
        plan: FormFillPlan,
        run: Run,
    ) -> tuple[PageObservation, State, int] | None:
        """Execute a FormFillPlan by issuing Fill commands to the executor."""
        step_increment = 0

        for instruction in plan.field_instructions:
            if not instruction.css_selector or not instruction.value:
                continue

            cmd = FillCommand(
                css_selector=instruction.css_selector,
                value=instruction.value,
            )
            obs = await self._executor.execute(cmd)
            step_increment += 1

            if isinstance(obs, ErrorObservation):
                logger.warning(
                    "orchestrator.fill_error",
                    selector=instruction.css_selector,
                    error=obs.message,
                )

        # Submit if requested
        if plan.should_submit and plan.form_css_selector:
            submit_selector = f"{plan.form_css_selector} [type='submit'], {plan.form_css_selector} button[type='submit'], {plan.form_css_selector} input[type='submit']"
            submit_cmd = ClickCommand(
                css_selector=submit_selector,
                wait_for_navigation=True,
            )
            obs = await self._executor.execute(submit_cmd)
            step_increment += 1

            if isinstance(obs, PageObservation):
                new_state = State(
                    run_id=run.run_id,
                    current_url=obs.final_url,
                    cookies=obs.cookies,
                    local_storage=obs.local_storage,
                    session_storage=obs.session_storage,
                )
                return obs, new_state, step_increment

        return None

    async def _diff_state(
        self,
        before: State,
        after: State,
        observation: PageObservation,
        run: Run,
    ) -> StateDelta | None:
        """Call the StateDiffAgent if wired."""
        if not self._state_diff_agent:
            return None

        diff_input = StateDiffInput(
            before=before,
            after=after,
            page_url_before=before.current_url,
            page_url_after=after.current_url,
        )

        try:
            envelope: MessageEnvelope[StateDiffInput] = MessageEnvelope(
                source="orchestrator",
                target="state_diff_agent",
                correlation_id=run.run_id,
                payload=diff_input,
            )
            result = self._state_diff_agent.run(envelope)
            delta = result.payload

            if delta.auth_state_changed:
                logger.info(
                    "orchestrator.auth_transition",
                    login=delta.login_detected,
                    logout=delta.logout_detected,
                )
            if delta.security_observations:
                logger.info(
                    "orchestrator.security_observations",
                    observations=delta.security_observations,
                )

            return delta
        except Exception as exc:
            logger.warning("orchestrator.state_diff_error", error=str(exc))
            return None

    def _decision_to_command(
        self, decision: NextActionDecision
    ) -> NavigateCommand | ClickCommand | FillCommand | SelectCommand | None:
        """
        Convert a NextActionDecision into an executable Command.

        Handles Navigate, Click, Fill, and Select action kinds.
        """
        if decision.chosen_href and decision.chosen_action_kind == ActionKind.NAVIGATE:
            return NavigateCommand(url=decision.chosen_href)

        if decision.chosen_css_selector:
            match decision.chosen_action_kind:
                case ActionKind.CLICK | ActionKind.SUBMIT:
                    return ClickCommand(
                        css_selector=decision.chosen_css_selector,
                        wait_for_navigation=(
                            decision.chosen_action_kind == ActionKind.SUBMIT
                        ),
                    )
                case ActionKind.FILL:
                    if decision.fill_value is not None:
                        return FillCommand(
                            css_selector=decision.chosen_css_selector,
                            value=decision.fill_value,
                        )
                case ActionKind.SELECT:
                    if decision.fill_value is not None:
                        return SelectCommand(
                            css_selector=decision.chosen_css_selector,
                            value=decision.fill_value,
                        )

        # Fallback: if href is provided but kind isn't navigate
        if decision.chosen_href:
            return NavigateCommand(url=decision.chosen_href)

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
