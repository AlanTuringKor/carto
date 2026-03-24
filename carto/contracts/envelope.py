"""
MessageEnvelope — typed wrapper for all inter-component communication.

Every message passed between agents, and from agents to the orchestrator,
must be wrapped in a MessageEnvelope.  This ensures that all communication
is timestamped, typed, and correlation-trackable without a free-text channel.

Usage:
    envelope = MessageEnvelope[ActionInventory](
        source="page_understanding_agent",
        target="action_planner_agent",
        correlation_id=run_id,
        payload=inventory,
    )
    serialised = envelope.model_dump_json()
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


class MessageEnvelope(BaseModel, Generic[T]):
    """
    Generic typed envelope for all agent messages.

    Fields
    ------
    envelope_id:
        Unique identifier for this message instance.
    source:
        Logical name of the sending component (e.g. ``"page_understanding_agent"``).
    target:
        Logical name of the intended recipient (e.g. ``"action_planner_agent"``).
    correlation_id:
        Groups related messages together — typically the ``run_id``.
    timestamp:
        UTC time the message was created.
    payload:
        The typed message content.  The generic parameter ``T`` constrains
        this to a specific Pydantic model.
    schema_version:
        Bumped when the payload schema changes in a breaking way.
    """

    envelope_id: str = Field(default_factory=_uuid)
    source: str
    target: str
    correlation_id: str       # run_id in most cases
    timestamp: datetime = Field(default_factory=_now)
    payload: T
    schema_version: str = "1.0"

    model_config = {"arbitrary_types_allowed": True}
