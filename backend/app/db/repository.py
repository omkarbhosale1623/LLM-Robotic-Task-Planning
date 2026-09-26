"""Abstract repository + persistence record types + factory.

The :class:`Repository` interface is intentionally small and async. Concrete
implementations:

* :class:`~app.db.memory_repo.MemoryRepository` — default, in-process, used by
  tests and whenever no database is configured.
* :class:`~app.db.sql_repo.SqlRepository` — SQLAlchemy(async)+asyncpg backed by
  Supabase Postgres, **import-guarded** so it is only loaded when a
  ``DATABASE_URL`` is present and the libraries import.

Per-user isolation is enforced at this layer (every read/write is scoped by
``user_id``) *and* at the database via Supabase Row-Level-Security policies.
"""

from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class SessionRecord:
    """A persisted planning session, owned by a single user."""

    user_id: str
    id: str = field(default_factory=_new_id)
    project: str = "llm-robotic-task-planning"
    config: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "project": self.project,
            "config": self.config,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class RunRecord:
    """A persisted run: a plan / execute / benchmark invocation and its result."""

    session_id: str
    user_id: str
    kind: str  # plan | execute | plan-and-run | benchmark
    id: str = field(default_factory=_new_id)
    params: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "kind": self.kind,
            "params": self.params,
            "metrics": self.metrics,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class PlanMemoryRecord:
    """A successful (instruction -> plan) pair with an embedding for retrieval."""

    user_id: str
    instruction: str
    plan: dict[str, Any]
    embedding: list[float]
    id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "instruction": self.instruction,
            "plan": self.plan,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Abstract repository
# ---------------------------------------------------------------------------


class Repository(abc.ABC):
    """Async persistence interface, scoped per user."""

    backend: str = "abstract"

    @abc.abstractmethod
    async def init(self) -> None:
        """Prepare the backend (create tables / pools). Idempotent."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Release any held resources."""

    # -- sessions ------------------------------------------------------------

    @abc.abstractmethod
    async def create_session(self, record: SessionRecord) -> SessionRecord: ...

    @abc.abstractmethod
    async def get_session(self, user_id: str, session_id: str) -> SessionRecord | None: ...

    @abc.abstractmethod
    async def list_sessions(self, user_id: str) -> list[SessionRecord]: ...

    @abc.abstractmethod
    async def touch_session(self, user_id: str, session_id: str) -> None:
        """Bump ``updated_at`` for a session (no-op if absent)."""

    # -- runs ----------------------------------------------------------------

    @abc.abstractmethod
    async def save_run(self, record: RunRecord) -> RunRecord: ...

    @abc.abstractmethod
    async def list_runs(
        self, user_id: str, session_id: str | None = None, limit: int = 50
    ) -> list[RunRecord]: ...

    # -- plan memory (pgvector few-shot retrieval) ---------------------------

    @abc.abstractmethod
    async def save_plan_memory(self, record: PlanMemoryRecord) -> PlanMemoryRecord: ...

    @abc.abstractmethod
    async def search_plan_memory(
        self, user_id: str, embedding: list[float], top_k: int = 3
    ) -> list[PlanMemoryRecord]:
        """Return the ``top_k`` most similar prior plans for ``user_id``."""


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_repository(settings: Any) -> Repository:
    """Build the repository per ``PERSISTENCE_BACKEND``.

    * ``memory`` — always the in-memory repo.
    * ``supabase`` — force the SQL repo (raises if libs/DSN missing).
    * ``auto`` (default) — SQL when ``DATABASE_URL`` is set *and* SQLAlchemy +
      asyncpg import successfully; otherwise the in-memory repo with a warning.

    The SQL module is imported lazily so the app boots offline.
    """

    from app.db.memory_repo import MemoryRepository

    backend = (getattr(settings, "persistence_backend", "auto") or "auto").lower()
    dsn = getattr(settings, "database_url", None)

    if backend == "memory":
        return MemoryRepository()

    if backend in ("supabase", "auto") and dsn:
        try:
            from app.db.sql_repo import SqlRepository  # deferred, guarded

            return SqlRepository(dsn, settings)
        except Exception as exc:  # pragma: no cover - exercised only with DB libs
            if backend == "supabase":
                raise
            logger.warning(
                "PERSISTENCE_BACKEND=auto: SQL backend unavailable (%s); using memory repo.",
                exc,
            )
            return MemoryRepository()

    if backend == "supabase" and not dsn:
        raise RuntimeError("PERSISTENCE_BACKEND=supabase but DATABASE_URL is not set")

    return MemoryRepository()
