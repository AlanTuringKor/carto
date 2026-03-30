"""
Orchestrator — the top-level observe → infer → decide → execute loop.

The orchestrator coordinates all components without containing business
logic itself.  It:
1. Drives the run lifecycle (start, step, stop).
2. Issues commands to the executor.
3. Routes observations to agents (page understanding, action planner,
   form filler, state diff).
4. Records state snapshots and detects auth transitions.
5. Emits structured events to the audit log.
6. Checks approval gates before sensitive commands.
7. Accumulates network data for HAR export.
8. Decides when to stop based on agent signals.
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
    WaitCommand,
)
from carto.contracts.envelope import MessageEnvelope
from carto.domain.approval import (
    ApprovalDecision,
    ApprovalPolicy,
    ApprovalRequest,
    AutoApprovePolicy,
)
from carto.domain.events import (
    approval_requested_event,
    approval_resolved_event,
    auth_transition_event,
    command_issued_event,
    command_result_event,
    decision_made_event,
    error_event,
    form_fill_planned_event,
    inference_produced_event,
    page_observed_event,
    run_completed_event,
    run_started_event,
    state_diff_computed_event,
    step_started_event,
)
from carto.domain.inferences import (
    ActionInventory,
    FormFillerInput,
    FormFillPlan,
    NextActionDecision,
    StateDelta,
    StateDiffInput,
)
from carto.domain.models import ActionKind, AuthState, Run, RunStatus, State
from carto.domain.observations import ErrorObservation, PageObservation
from carto.executor.base import BaseExecutor
from carto.export.har import HarBuilder
from carto.storage.event_log import EventLog, InMemoryEventLog
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
    enable_approval_gates: bool = False


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
    event_log:
        Structured event log (defaults to InMemoryEventLog).
    approval_policy:
        Approval gate policy (defaults to AutoApprovePolicy).
    har_builder:
        HAR export builder (optional — HAR export disabled if None).
    role_name, role_username, role_password:
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
        event_log: EventLog | None = None,
        approval_policy: ApprovalPolicy | None = None,
        har_builder: HarBuilder | None = None,
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
        self._event_log: EventLog = event_log or InMemoryEventLog()
        self._approval_policy = approval_policy or AutoApprovePolicy()
        self._har_builder = har_builder
        self._role_name = role_name
        self._role_username = role_username
        self._role_password = role_password

    @property
    def event_log(self) -> EventLog:
        """Access the event log (for testing / export)."""
        return self._event_log

    @property
    def har_builder(self) -> HarBuilder | None:
        """Access the HAR builder (for export)."""
        return self._har_builder

    async def run(self, run: Run) -> Run:
        """
        Execute a full mapping run from start to stop.

        Returns the updated Run with final status and step count.
        """
        logger.info("orchestrator.run.start", run_id=run.run_id, url=run.start_url)

        self._event_log.emit(run_started_event(
            run_id=run.run_id,
            session_id=run.session_id,
            start_url=run.start_url,
        ))

        self._store.update_run(run.model_copy(update={"status": RunStatus.RUNNING}))
        self._executor.set_run_id(run.run_id)  # type: ignore[attr-defined]

        state = State(
            run_id=run.run_id,
            current_url=run.start_url,
        )

        step = 0
        try:
            # ── Initial navigation ──────────────────────────────────────
            nav_cmd = NavigateCommand(url=run.start_url)
            self._event_log.emit(command_issued_event(
                run_id=run.run_id, step=step,
                command_kind=nav_cmd.kind, command_id=nav_cmd.command_id,
                target=run.start_url,
            ))

            observation = await self._executor.execute(nav_cmd)
            step += 1

            if isinstance(observation, ErrorObservation):
                self._event_log.emit(error_event(
                    run_id=run.run_id, step=step,
                    error_type="initial_nav_failed", message=observation.message,
                ))
                return self._finish_run(run, RunStatus.FAILED, step, observation.message)

            assert isinstance(observation, PageObservation)
            self._store.add_observation(observation)
            self._record_observation(observation, run.run_id, step)
            prev_state = state
            state = self._update_state(state, observation)

            # ── Main observe → infer → decide → execute loop ─────────────
            while step < self._config.max_steps:
                self._event_log.emit(step_started_event(
                    run_id=run.run_id, step=step, url=observation.url,
                ))

                if self._config.screenshot_each_step:
                    await self._executor.execute(ScreenshotCommand())

                # ── Observe: page understanding agent ─────────────────
                inventory = await self._observe(observation, run, step)
                if inventory is None:
                    break

                # ── State diff (if enabled) ───────────────────────────
                if self._config.enable_state_diff and self._state_diff_agent:
                    delta = await self._diff_state(
                        prev_state, state, observation, run, step,
                    )
                    if delta and delta.login_detected:
                        state = state.model_copy(
                            update={"auth_state": AuthState.AUTHENTICATED}
                        )
                        self._event_log.emit(auth_transition_event(
                            run_id=run.run_id, step=step,
                            before_authenticated=False, after_authenticated=True,
                            trigger="login_detected",
                        ))
                    elif delta and delta.logout_detected:
                        state = state.model_copy(
                            update={"auth_state": AuthState.UNAUTHENTICATED}
                        )
                        self._event_log.emit(auth_transition_event(
                            run_id=run.run_id, step=step,
                            before_authenticated=True, after_authenticated=False,
                            trigger="logout_detected",
                        ))

                # ── Form filling (if login page detected) ─────────────
                if (
                    self._config.enable_form_filling
                    and self._form_filler_agent
                    and inventory.is_login_page
                    and inventory.discovered_forms
                    and state.auth_state != AuthState.AUTHENTICATED
                ):
                    fill_result = await self._fill_form(
                        inventory, observation, run, step,
                    )
                    if fill_result:
                        observation, state, step_inc = fill_result
                        step += step_inc
                        prev_state = state
                        continue

                # ── Decide: action planner agent ──────────────────────
                decision = await self._decide(inventory, state, run, step)
                if decision is None or decision.should_stop:
                    break

                # ── Convert to command ─────────────────────────────────
                command = self._decision_to_command(decision)
                if command is None:
                    logger.warning("orchestrator.unresolvable_decision", step=step)
                    break

                # ── Approval gate ──────────────────────────────────────
                if self._config.enable_approval_gates:
                    approved = await self._check_approval(
                        decision, inventory, run, step,
                    )
                    if not approved:
                        logger.info("orchestrator.action_denied", step=step)
                        break

                # ── Execute ────────────────────────────────────────────
                self._event_log.emit(command_issued_event(
                    run_id=run.run_id, step=step,
                    command_kind=command.kind, command_id=command.command_id,
                    target=getattr(command, "url", None) or getattr(command, "css_selector", None),
                ))

                prev_state = state
                observation = await self._executor.execute(command)
                step += 1

                if isinstance(observation, ErrorObservation):
                    self._event_log.emit(command_result_event(
                        run_id=run.run_id, step=step,
                        command_id=command.command_id, success=False,
                        error=observation.message,
                    ))
                    if self._config.stop_on_agent_error:
                        break
                    
                    # Recover state by attempting a zero-duration wait
                    observation = await self._executor.execute(WaitCommand(duration_ms=0))
                    if isinstance(observation, ErrorObservation):
                        logger.error("orchestrator.recovery_failed", error=observation.message)
                        break
                        
                    continue

                assert isinstance(observation, PageObservation)
                self._store.add_observation(observation)
                self._event_log.emit(command_result_event(
                    run_id=run.run_id, step=step,
                    command_id=command.command_id, success=True,
                    result_url=observation.final_url,
                ))
                self._record_observation(observation, run.run_id, step)
                state = self._update_state(state, observation)

        except Exception as exc:
            logger.exception("orchestrator.unhandled_error", run_id=run.run_id)
            self._event_log.emit(error_event(
                run_id=run.run_id, step=step,
                error_type=type(exc).__name__, message=str(exc),
            ))
            return self._finish_run(run, RunStatus.FAILED, step, str(exc))

        return self._finish_run(run, RunStatus.COMPLETED, step)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_observation(
        self, obs: PageObservation, run_id: str, step: int
    ) -> None:
        """Record a page observation in the event log and HAR builder."""
        self._event_log.emit(page_observed_event(
            run_id=run_id, step=step,
            observation_id=obs.observation_id,
            url=obs.url, title=obs.title,
            status_code=obs.status_code,
            element_count=len(obs.interactive_elements),
            form_count=len(obs.forms_raw),
            cookies=obs.cookies,
        ))
        if self._har_builder:
            self._har_builder.add_observation(obs)

    async def _observe(
        self,
        observation: PageObservation,
        run: Run,
        step: int,
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
            inventory = result.payload
            self._store.add_inference(inventory)

            self._event_log.emit(inference_produced_event(
                run_id=run.run_id, step=step,
                inference_kind=inventory.kind,
                agent_name=inventory.agent_name,
                inference_id=inventory.inference_id,
                summary={
                    "page_cluster": inventory.page_cluster,
                    "is_login_page": inventory.is_login_page,
                    "actions": len(inventory.discovered_actions),
                    "forms": len(inventory.discovered_forms),
                },
            ))

            # Provide visibility into what was actually found on the page
            action_summaries = [f"[{a.kind}] {a.label or a.css_selector}" for a in inventory.discovered_actions]
            if action_summaries:
                logger.info("page.discovered_actions", items=action_summaries)
            
            form_summaries = [f"method={f.method} action={f.action}" for f in inventory.discovered_forms]
            if form_summaries:
                logger.info("page.discovered_forms", items=form_summaries)

            return inventory
        except Exception as exc:
            logger.warning("orchestrator.page_agent_error", error=str(exc))
            self._event_log.emit(error_event(
                run_id=run.run_id, step=step,
                error_type="page_agent_error", message=str(exc),
            ))
            return None

    async def _decide(
        self,
        inventory: ActionInventory,
        state: State,
        run: Run,
        step: int,
    ) -> NextActionDecision | None:
        """Call the ActionPlannerAgent if wired, else return None."""
        if self._planner_agent is None:
            return None

        try:
            if hasattr(self._planner_agent, "set_state"):
                self._planner_agent.set_state(state)

            envelope: MessageEnvelope[ActionInventory] = MessageEnvelope(
                source="orchestrator",
                target="action_planner_agent",
                correlation_id=run.run_id,
                payload=inventory,
            )
            result: MessageEnvelope[NextActionDecision] = self._planner_agent.run(envelope)
            decision = result.payload
            self._store.add_inference(decision)

            self._event_log.emit(decision_made_event(
                run_id=run.run_id, step=step,
                action_kind=decision.chosen_action_kind,
                action_label=decision.chosen_label,
                rationale=decision.rationale,
                should_stop=decision.should_stop,
            ))

            return decision
        except Exception as exc:
            logger.warning("orchestrator.planner_agent_error", error=str(exc))
            self._event_log.emit(error_event(
                run_id=run.run_id, step=step,
                error_type="planner_agent_error", message=str(exc),
            ))
            return None

    async def _fill_form(
        self,
        inventory: ActionInventory,
        observation: PageObservation,
        run: Run,
        step: int,
    ) -> tuple[PageObservation, State, int] | None:
        """Attempt to fill and submit a login form."""
        if not self._form_filler_agent or not inventory.discovered_forms:
            return None

        form_fields = inventory.discovered_forms[0]

        csrf_name = None
        csrf_value = None
        for field in form_fields:
            if field.name and any(
                hint in field.name.lower()
                for hint in ["csrf", "xsrf", "_token", "authenticity"]
            ):
                csrf_name = field.name
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
            self._store.add_inference(plan)

            self._event_log.emit(form_fill_planned_event(
                run_id=run.run_id, step=step,
                field_count=len(plan.field_instructions),
                is_login_form=plan.is_login_form,
                should_submit=plan.should_submit,
            ))
        except Exception as exc:
            logger.warning("orchestrator.form_filler_error", error=str(exc))
            return None

        return await self._execute_form_fill(plan, run, step)

    async def _execute_form_fill(
        self,
        plan: FormFillPlan,
        run: Run,
        step: int,
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

        if plan.should_submit and plan.form_css_selector:
            submit_selector = (
                f"{plan.form_css_selector} [type='submit'], "
                f"{plan.form_css_selector} button[type='submit'], "
                f"{plan.form_css_selector} input[type='submit']"
            )
            submit_cmd = ClickCommand(
                css_selector=submit_selector,
                wait_for_navigation=True,
            )
            obs = await self._executor.execute(submit_cmd)
            step_increment += 1

            if isinstance(obs, PageObservation):
                self._record_observation(obs, run.run_id, step + step_increment)
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
        step: int,
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
            self._store.add_inference(delta)

            self._event_log.emit(state_diff_computed_event(
                run_id=run.run_id, step=step,
                auth_state_changed=delta.auth_state_changed,
                login_detected=delta.login_detected,
                logout_detected=delta.logout_detected,
                summary=delta.summary,
            ))

            return delta
        except Exception as exc:
            logger.warning("orchestrator.state_diff_error", error=str(exc))
            return None

    async def _check_approval(
        self,
        decision: NextActionDecision,
        inventory: ActionInventory,
        run: Run,
        step: int,
    ) -> bool:
        """Check if the decision requires approval; return True if approved."""
        reason = self._approval_policy.requires_approval(
            action_kind=decision.chosen_action_kind,
            action_label=decision.chosen_label,
            is_login_form=inventory.is_login_page,
            is_logout_action=inventory.is_logout_page,
            is_credential_submission=(
                inventory.is_login_page
                and decision.chosen_action_kind in (ActionKind.SUBMIT, ActionKind.CLICK)
            ),
        )

        if reason is None:
            return True

        request = ApprovalRequest(
            run_id=run.run_id,
            step=step,
            reason=reason,
            action_label=decision.chosen_label,
            action_kind=decision.chosen_action_kind,
            css_selector=decision.chosen_css_selector,
            target_url=decision.chosen_href,
        )

        self._event_log.emit(approval_requested_event(
            run_id=run.run_id, step=step,
            request_id=request.request_id,
            reason=reason,
            action_label=decision.chosen_label,
        ))

        result = self._approval_policy.request_approval(request)

        self._event_log.emit(approval_resolved_event(
            run_id=run.run_id, step=step,
            request_id=request.request_id,
            decision=result.decision,
            decided_by=result.decided_by,
        ))

        return result.decision == ApprovalDecision.APPROVED

    def _decision_to_command(
        self, decision: NextActionDecision
    ) -> NavigateCommand | ClickCommand | FillCommand | SelectCommand | None:
        """Convert a NextActionDecision into an executable Command."""
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

        self._event_log.emit(run_completed_event(
            run_id=run.run_id,
            session_id=run.session_id,
            status=status,
            step_count=step_count,
            error=error,
        ))

        logger.info(
            "orchestrator.run.complete",
            run_id=run.run_id,
            status=status,
            steps=step_count,
        )
        return finished
