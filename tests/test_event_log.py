"""Tests for event log storage."""

import json
import os
import tempfile

from carto.domain.events import Event, EventKind, run_started_event, step_started_event
from carto.storage.event_log import EventLog, InMemoryEventLog


class TestInMemoryEventLog:
    def _make_log(self) -> InMemoryEventLog:
        return InMemoryEventLog()

    def test_emit_and_count(self):
        log = self._make_log()
        assert log.count == 0
        log.emit(run_started_event("r1", "s1", "https://x.com"))
        assert log.count == 1

    def test_get_events_by_run(self):
        log = self._make_log()
        log.emit(run_started_event("r1", "s1", "https://x.com"))
        log.emit(run_started_event("r2", "s1", "https://y.com"))
        assert len(log.get_events("r1")) == 1
        assert len(log.get_events("r2")) == 1

    def test_get_events_by_kind(self):
        log = self._make_log()
        log.emit(run_started_event("r1", "s1", "https://x.com"))
        log.emit(step_started_event("r1", 1, "https://x.com/page"))
        assert len(log.get_events("r1", kind=EventKind.RUN_STARTED)) == 1
        assert len(log.get_events("r1", kind=EventKind.STEP_STARTED)) == 1

    def test_export_json(self):
        log = self._make_log()
        log.emit(run_started_event("r1", "s1", "https://x.com"))
        log.emit(step_started_event("r1", 1, "https://x.com/page"))

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            log.export_json("r1", path)
            data = json.loads(open(path).read())
            assert len(data) == 2
            assert data[0]["kind"] == "run_started"
        finally:
            os.unlink(path)

    def test_satisfies_protocol(self):
        log = self._make_log()
        assert isinstance(log, EventLog)
