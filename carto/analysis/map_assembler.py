"""
MapAssembler — schema-native output builder.

Constructs a strictly aligned `WebAppSecurityMapMinimal` JSON structure
by parsing the `EventLog` sequence and the raw observations/inferences
held in the `SessionStore`.
"""

from __future__ import annotations

from typing import Any
from datetime import UTC, datetime

from carto.domain.campaign import CampaignSummary
from carto.domain.events import EventKind
from carto.domain.models import Run
from carto.domain.observations import PageObservation, NetworkRequest
from carto.domain.inferences import ActionInventory, NextActionDecision, StateDelta
from carto.storage.event_log import EventLog
from carto.storage.session_store import SessionStore

from carto.domain.schema import (
    WebAppSecurityMapMinimal,
    Metadata, CrawlScope, CrawlerContext,
    Actor, Kind as ActorKind, AuthState as SchemaAuthState, SourceMode,
    View, ViewType,
    UiElement, Kind1 as UiKind, ActionType as SchemaActionType,
    StateItem, StorageKind, Persistence,
    Endpoint, Protocol, Method, RequestContract, ResponseContract,
    ObservedRequest, RequestInstance, ResponseInstance, Correlation,
    Flow, FlowStep, StepType,
    Session as SchemaSession, Relation, Evidence, Kind2 as EvidenceKind
)

class MapAssembler:
    """
    Transforms a mapping campaign into the canonical `WebAppSecurityMapMinimal` schema.
    """

    def assemble(
        self,
        summary: CampaignSummary,
        event_logs: dict[str, EventLog],
        store: SessionStore,
    ) -> WebAppSecurityMapMinimal:
        
        # 1. Initialize root object structures
        metadata = self._build_metadata(summary)
        
        self.actors: dict[str, Actor] = {}
        self.views: dict[str, View] = {}
        self.ui_elements: dict[str, UiElement] = {}
        self.endpoints: dict[str, Endpoint] = {}
        self.observed_requests: dict[str, ObservedRequest] = {}
        self.state_items: dict[str, StateItem] = {}
        self.flows: dict[str, Flow] = {}
        self.flow_steps: list[FlowStep] = []
        self.sessions: dict[str, SchemaSession] = {}
        self.evidence: dict[str, Evidence] = {}
        
        # Process each role run in the campaign
        for role_summary in summary.role_summaries:
            run_id = role_summary.run_id
            run = store.get_run(run_id)
            actor = self._build_actor(role_summary, run)
            self.actors[actor.id.root] = actor
            
            event_log = event_logs.get(role_summary.role_name)
            if event_log:
                self._process_run(run, event_log, store, actor)

        return WebAppSecurityMapMinimal(
            schema_name="WebAppSecurityMapMinimal",
            schema_version="1.0",
            metadata=metadata,
            actors=list(self.actors.values()),
            views=list(self.views.values()),
            ui_elements=list(self.ui_elements.values()),
            state_items=list(self.state_items.values()),
            endpoints=list(self.endpoints.values()),
            observed_requests=list(self.observed_requests.values()),
            entities=[],
            flows=list(self.flows.values()),
            flow_steps=self.flow_steps,
            sessions=list(self.sessions.values()),
            relations=[],
            evidence=list(self.evidence.values()),
        )

    def _build_metadata(self, summary: CampaignSummary) -> Metadata:
        return Metadata(
            target_base_url=summary.target_url,
            app_name=None,
            crawl_started_at=summary.completed_at or datetime.now(tz=UTC),
            crawl_finished_at=summary.completed_at or datetime.now(tz=UTC),
            crawl_scope=CrawlScope(
                allowed_hosts=[], 
                allowed_path_prefixes=[]
            ),
            crawler_context=CrawlerContext(
                run_id=summary.campaign_id,
                model_name=None,
                browser_profile_id=None,
                notes=None
            )
        )

    def _build_actor(self, rs: Any, run: Run) -> Actor:
        actor_id = f"actor-{rs.role_name}"
        kind_map = {
            "anonymous": ActorKind.anonymous,
            "authenticated": ActorKind.authenticated
        }
        kind = kind_map.get(rs.role_name, ActorKind.role_variant)
        
        auth_map = {
            "unauthenticated": SchemaAuthState.unauthenticated,
            "authenticated": SchemaAuthState.authenticated,
        }
        auth_state = auth_map.get(rs.auth_state, SchemaAuthState.unknown)
        
        return Actor(
            id=actor_id,
            label=rs.role_name,
            kind=kind,
            auth_state=auth_state,
            role_labels=[],
            parent_actor_id=None,
            session_capabilities=[],
            source_mode=SourceMode.observed,
            confidence=1.0,
            evidence_refs=[],
            notes=None
        )

    def _process_run(self, run: Run, event_log: EventLog, store: SessionStore, actor: Actor) -> None:
        events = event_log.get_events(run.run_id)
        
        # Build a flow for this run
        flow_id = f"flow-{run.run_id}"
        self.flows[flow_id] = Flow(
            id=flow_id,
            name=f"Run Sequence {run.run_id}",
            goal="Mapping exploration",
            actor_ids=[actor.id.root],
            entry_view_id=None,
            trigger_ui_element_id=None,
            preconditions=[],
            postconditions=[],
            step_ids=[],
            entity_ids=[],
            source_mode=SourceMode.observed,
            confidence=1.0,
            evidence_refs=[],
            notes=None
        )
        
        sess_id = f"sess-{run.run_id}"
        self.sessions[sess_id] = SchemaSession(
            id=sess_id,
            actor_id=actor.id.root,
            started_at=run.started_at,
            ended_at=run.finished_at,
            initial_url=run.start_url,
            final_url=None,
            observed_view_ids=[],
            observed_flow_ids=[flow_id],
            observed_request_ids=[],
            source_mode=SourceMode.observed,
            confidence=1.0,
            evidence_refs=[],
            notes=None
        )

        flow_step_order = 1
        
        for ev in events:
            if ev.kind == EventKind.PAGE_OBSERVED:
                obs_id = ev.data.get("observation_id")
                obs = store.get_observation(obs_id)
                if isinstance(obs, PageObservation):
                    view_id = self._add_view(obs)
                    if view_id and view_id not in [v.root for v in self.sessions[sess_id].observed_view_ids]:
                        self.sessions[sess_id].observed_view_ids.append(view_id)
                    
                    # Create Flow Step for Page Observe
                    step_id = f"step-{ev.event_id}"
                    self.flow_steps.append(FlowStep(
                        id=step_id,
                        flow_id=flow_id,
                        order=flow_step_order,
                        step_type=StepType.response,
                        ref_id=view_id,
                        expects_from_step_id=None,
                        produces_state_tags=[],
                        consumes_state_tags=[],
                        source_mode=SourceMode.observed,
                        confidence=1.0,
                        evidence_refs=[]
                    ))
                    self.flows[flow_id].step_ids.append(step_id)
                    flow_step_order += 1
                    
                    self._process_network(obs, actor.id.root, sess_id)

            elif ev.kind == EventKind.INFERENCE_PRODUCED:
                inf_id = ev.data.get("inference_id")
                inf = store.get_inference(inf_id)
                if isinstance(inf, ActionInventory):
                    self._add_ui_elements(inf)
                elif isinstance(inf, NextActionDecision):
                    # Flow step for decision
                    step_id = f"step-{ev.event_id}"
                    ui_ref = f"ui-{inf.action_id}" if inf.action_id else "unknown"
                    if ui_ref in self.ui_elements:
                        self.flow_steps.append(FlowStep(
                            id=step_id,
                            flow_id=flow_id,
                            order=flow_step_order,
                            step_type=StepType.ui_action,
                            ref_id=ui_ref,
                            expects_from_step_id=None,
                            produces_state_tags=[],
                            consumes_state_tags=[],
                            source_mode=SourceMode.inferred,
                            confidence=1.0,
                            evidence_refs=[]
                        ))
                        self.flows[flow_id].step_ids.append(step_id)
                        flow_step_order += 1

    def _add_view(self, obs: PageObservation) -> str:
        # Simplistic deduplication by URL. Should use a router or normalized URL.
        view_id = f"view-{hash(obs.final_url)}"
        if view_id not in self.views:
            self.views[view_id] = View(
                id=view_id,
                label=obs.title or "Unknown",
                view_type=ViewType.page,
                canonical_route=obs.final_url,
                url_examples=[obs.final_url],
                title_text=obs.title,
                parent_view_id=None,
                reachable_actor_ids=[],
                required_state_tags=[],
                produced_state_tags=[],
                entity_ids=[],
                source_mode=SourceMode.observed,
                confidence=1.0,
                evidence_refs=[],
                notes=None
            )
        return view_id

    def _add_ui_elements(self, inv: ActionInventory) -> None:
        view_id = f"view-{hash(inv.current_url)}"
        for action in inv.discovered_actions:
            ui_id = f"ui-{action.action_id}"
            if ui_id not in self.ui_elements:
                self.ui_elements[ui_id] = UiElement(
                    id=ui_id,
                    view_id=view_id,
                    kind=UiKind.unknown, # Fallback
                    label=action.label,
                    selector_hint=None,
                    action_type=SchemaActionType.unknown, # Fallback
                    parameter_defs=[],
                    reads_state_item_ids=[],
                    writes_state_item_ids=[],
                    expected_endpoint_ids=[],
                    source_mode=SourceMode.inferred,
                    confidence=1.0,
                    evidence_refs=[],
                    notes=None
                )

    def _process_network(self, obs: PageObservation, actor_id: str, session_id: str) -> None:
        if not obs.network_requests:
            return
            
        for req in obs.network_requests:
            # Create endpoint if not exist
            ep_id = f"ep-{req.method}-{hash(req.url)}"
            if ep_id not in self.endpoints:
                self.endpoints[ep_id] = Endpoint(
                    id=ep_id,
                    protocol=Protocol.http if req.url.startswith("http:") else Protocol.https,
                    host=None,
                    method=getattr(Method, req.method.upper(), Method.UNKNOWN),
                    path_template=req.url,
                    operation_name=None,
                    request_contract=RequestContract(
                        header_names=list(req.headers.keys()),
                        path_params=[],
                        query_params=[],
                        body_content_types=[],
                        body_shape=None
                    ),
                    response_contract=ResponseContract(
                        status_codes=[req.response_status] if req.response_status else [],
                        header_names=[],
                        body_content_types=[],
                        body_shape=None
                    ),
                    auth_inputs_observed=[],
                    entity_ids=[],
                    source_mode=SourceMode.observed,
                    confidence=1.0,
                    evidence_refs=[],
                )
                
            # Create ObservedRequest
            req_id = f"req-{req.request_id}"
            if req_id not in self.observed_requests:
                self.observed_requests[req_id] = ObservedRequest(
                    id=req_id,
                    session_id=session_id,
                    order=0,
                    actor_id=actor_id,
                    endpoint_id=ep_id,
                    initiated_by_ui_element_id=None,
                    preceding_request_id=None,
                    request_instance=RequestInstance(
                        url=req.url,
                        header_names=list(req.headers.keys()),
                        query_keys=[],
                        body_keys=[],
                        body_shape=None,
                        body_example_redacted=None
                    ),
                    response_instance=ResponseInstance(
                        status_code=req.response_status,
                        header_names=[],
                        body_shape=None,
                        body_keys=[],
                        body_example_redacted=None
                    ),
                    correlation=Correlation(
                        traceparent_present=False,
                        tracestate_present=False,
                        request_id_headers=[]
                    ),
                    state_reads=[],
                    state_writes=[],
                    resulting_view_id=None,
                    resulting_entity_ids=[],
                    source_mode=SourceMode.observed,
                    confidence=1.0,
                    evidence_refs=[],
                )
                self.sessions[session_id].observed_request_ids.append(req_id)
