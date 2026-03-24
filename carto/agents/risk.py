"""
RiskAgent — flags security-relevant patterns as RiskSignals.

Phase 2 work item.  This module defines the interface only.

Responsibilities (Phase 2):
- Analyse ActionInventory for patterns associated with known vulnerability
  classes (CSRF, IDOR, open redirects, sensitive data exposure, etc.)
- Correlate risk patterns with CWE identifiers
- Assign severity levels
- Produce RiskSignal objects for the final report
"""

from __future__ import annotations

from carto.agents.base import AgentError, BaseAgent
from carto.contracts.envelope import MessageEnvelope
from carto.domain.artifacts import RiskSignal
from carto.domain.inferences import ActionInventory


class RiskAgent(BaseAgent[ActionInventory, RiskSignal]):
    """
    Analyses an ActionInventory for security-relevant signals.

    Note: The output type here is RiskSignal as a single placeholder.
    Phase 2 will introduce RiskReport containing a list[RiskSignal].

    TODO (Phase 2):
        - Define RiskReport(signals: list[RiskSignal]).
        - Implement pattern matching for: missing CSRF tokens, exposed
          admin paths, sensitive field types in GET forms, open redirects.
        - Map each finding to a CWE and CVSS estimate.
        - Feed RiskSignals into the Coverage report.
    """

    def __init__(self, llm_client: object, model_name: str = "gpt-4o") -> None:
        self._llm = llm_client
        self._model_name = model_name

    @property
    def agent_name(self) -> str:
        return "risk_agent"

    def run(
        self,
        envelope: MessageEnvelope[ActionInventory],
    ) -> MessageEnvelope[RiskSignal]:
        raise AgentError(
            self.agent_name,
            "RiskAgent not implemented — Phase 2 work item.",
        )
