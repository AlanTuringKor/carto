"""Tests for SessionStore."""

from __future__ import annotations

import pytest

from carto.domain.models import Run, RunStatus, Session, SessionStatus
from carto.storage.session_store import RunNotFoundError, SessionNotFoundError, SessionStore


@pytest.fixture()
def store() -> SessionStore:
    return SessionStore()


@pytest.fixture()
def session(store: SessionStore) -> Session:
    return store.create_session(Session(target_url="https://example.com"))


class TestSessionStore:
    def test_create_and_get_session(self, store: SessionStore) -> None:
        s = Session(target_url="https://example.com")
        store.create_session(s)
        retrieved = store.get_session(s.session_id)
        assert retrieved.session_id == s.session_id

    def test_duplicate_session_raises(self, store: SessionStore) -> None:
        s = Session(target_url="https://example.com")
        store.create_session(s)
        with pytest.raises(ValueError, match="already exists"):
            store.create_session(s)

    def test_get_missing_session_raises(self, store: SessionStore) -> None:
        with pytest.raises(SessionNotFoundError):
            store.get_session("nonexistent")

    def test_update_session(self, store: SessionStore, session: Session) -> None:
        updated = session.model_copy(update={"status": SessionStatus.RUNNING})
        store.update_session(updated)
        assert store.get_session(session.session_id).status == SessionStatus.RUNNING

    def test_update_missing_session_raises(self, store: SessionStore) -> None:
        fake = Session(target_url="https://x.com")
        with pytest.raises(SessionNotFoundError):
            store.update_session(fake)

    def test_list_sessions(self, store: SessionStore) -> None:
        store.create_session(Session(target_url="https://a.com"))
        store.create_session(Session(target_url="https://b.com"))
        assert len(store.list_sessions()) == 2


class TestRunStore:
    def test_create_and_get_run(self, store: SessionStore, session: Session) -> None:
        run = Run(session_id=session.session_id, start_url="https://example.com")
        store.create_run(run)
        retrieved = store.get_run(run.run_id)
        assert retrieved.run_id == run.run_id

    def test_run_registered_in_session(self, store: SessionStore, session: Session) -> None:
        run = Run(session_id=session.session_id, start_url="https://example.com")
        store.create_run(run)
        updated_session = store.get_session(session.session_id)
        assert run.run_id in updated_session.run_ids

    def test_duplicate_run_raises(self, store: SessionStore, session: Session) -> None:
        run = Run(session_id=session.session_id, start_url="https://example.com")
        store.create_run(run)
        with pytest.raises(ValueError, match="already exists"):
            store.create_run(run)

    def test_get_missing_run_raises(self, store: SessionStore) -> None:
        with pytest.raises(RunNotFoundError):
            store.get_run("nonexistent")

    def test_update_run(self, store: SessionStore, session: Session) -> None:
        run = Run(session_id=session.session_id, start_url="https://example.com")
        store.create_run(run)
        updated = run.model_copy(update={"status": RunStatus.RUNNING})
        store.update_run(updated)
        assert store.get_run(run.run_id).status == RunStatus.RUNNING

    def test_list_runs_by_session(self, store: SessionStore, session: Session) -> None:
        run1 = Run(session_id=session.session_id, start_url="https://a.com")
        run2 = Run(session_id=session.session_id, start_url="https://b.com")
        store.create_run(run1)
        store.create_run(run2)
        assert len(store.list_runs(session_id=session.session_id)) == 2

    def test_stats(self, store: SessionStore, session: Session) -> None:
        run = Run(session_id=session.session_id, start_url="https://example.com")
        store.create_run(run)
        stats = store.stats()
        assert stats["sessions"] == 1
        assert stats["runs"] == 1
