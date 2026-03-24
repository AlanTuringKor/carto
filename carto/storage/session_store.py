"""
SessionStore — in-memory registry for Sessions and Runs.

This is Phase 1's persistence layer.  It is intentionally simple:
all data lives in plain Python dicts keyed by ID.

Design for swap-out:
    The store exposes a small, stable interface.  Phase 2 can replace
    the dict-based implementation with a SQLite or Postgres backend
    without changing any call sites.

Thread safety:
    Not thread-safe in Phase 1.  The orchestrator is single-threaded.
    Phase 2 should add asyncio.Lock if concurrent runs are introduced.
"""

from __future__ import annotations

from carto.domain.models import Run, Session


class SessionNotFoundError(KeyError):
    pass


class RunNotFoundError(KeyError):
    pass


class SessionStore:
    """In-memory store for Session and Run objects."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._runs: dict[str, Run] = {}

    # ------------------------------------------------------------------
    # Session operations
    # ------------------------------------------------------------------

    def create_session(self, session: Session) -> Session:
        """Persist a new session.  Raises ValueError if ID already exists."""
        if session.session_id in self._sessions:
            raise ValueError(f"Session {session.session_id!r} already exists.")
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> Session:
        """Retrieve a session by ID."""
        try:
            return self._sessions[session_id]
        except KeyError:
            raise SessionNotFoundError(session_id) from None

    def update_session(self, session: Session) -> Session:
        """Replace a session record.  Raises SessionNotFoundError if missing."""
        if session.session_id not in self._sessions:
            raise SessionNotFoundError(session.session_id)
        self._sessions[session.session_id] = session
        return session

    def list_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    # ------------------------------------------------------------------
    # Run operations
    # ------------------------------------------------------------------

    def create_run(self, run: Run) -> Run:
        """Persist a new run.  Raises ValueError if ID already exists."""
        if run.run_id in self._runs:
            raise ValueError(f"Run {run.run_id!r} already exists.")
        self._runs[run.run_id] = run

        # Also register the run_id in its parent session
        session = self.get_session(run.session_id)
        if run.run_id not in session.run_ids:
            updated = session.model_copy(
                update={"run_ids": [*session.run_ids, run.run_id]}
            )
            self._sessions[session.session_id] = updated

        return run

    def get_run(self, run_id: str) -> Run:
        try:
            return self._runs[run_id]
        except KeyError:
            raise RunNotFoundError(run_id) from None

    def update_run(self, run: Run) -> Run:
        """Replace a run record.  Raises RunNotFoundError if missing."""
        if run.run_id not in self._runs:
            raise RunNotFoundError(run.run_id)
        self._runs[run.run_id] = run
        return run

    def list_runs(self, session_id: str | None = None) -> list[Run]:
        runs = list(self._runs.values())
        if session_id:
            runs = [r for r in runs if r.session_id == session_id]
        return runs

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        return {
            "sessions": len(self._sessions),
            "runs": len(self._runs),
        }
