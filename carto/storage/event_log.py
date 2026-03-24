"""
Event log storage for Carto.

Provides protocol and in-memory implementation for the structured
audit trail.  The ``EventLog`` protocol is designed so that a
persistent implementation (database, JSONL file, etc.) can be swapped
in later without changing any call sites.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

import structlog

from carto.domain.events import Event, EventKind

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class EventLog(Protocol):
    """Minimal interface for event log backends."""

    def emit(self, event: Event) -> None:
        """Record an event."""
        ...

    def get_events(
        self,
        run_id: str,
        kind: EventKind | None = None,
    ) -> list[Event]:
        """Retrieve events for a run, optionally filtered by kind."""
        ...

    def export_json(self, run_id: str, path: str) -> None:
        """Export all events for a run to a JSON file."""
        ...


# ---------------------------------------------------------------------------
# In-memory implementation
# ---------------------------------------------------------------------------


class InMemoryEventLog:
    """
    List-backed event log.

    Good for testing and single-run CLI usage.  For durable storage,
    replace with a JSONL or database-backed implementation that
    satisfies the ``EventLog`` protocol.
    """

    def __init__(self) -> None:
        self._events: list[Event] = []

    def emit(self, event: Event) -> None:
        self._events.append(event)
        logger.debug(
            "event_log.emit",
            kind=event.kind,
            run_id=event.run_id,
            step=event.step,
        )

    def get_events(
        self,
        run_id: str,
        kind: EventKind | None = None,
    ) -> list[Event]:
        return [
            e
            for e in self._events
            if e.run_id == run_id and (kind is None or e.kind == kind)
        ]

    def export_json(self, run_id: str, path: str) -> None:
        events = self.get_events(run_id)
        out = [e.model_dump(mode="json") for e in events]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(out, indent=2, default=str))
        logger.info("event_log.exported", run_id=run_id, path=path, count=len(out))

    @property
    def count(self) -> int:
        return len(self._events)
