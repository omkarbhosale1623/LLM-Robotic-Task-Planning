"""In-memory repository (default; used offline and by tests).

Thread-/task-safe enough for a single process: a lock guards the dicts. Plan
memory similarity uses cosine over the stored embeddings, mirroring what the
pgvector backend does in Postgres.
"""

from __future__ import annotations

import asyncio

from app.db.repository import (
    PlanMemoryRecord,
    Repository,
    RunRecord,
    SessionRecord,
    _now,
)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class MemoryRepository(Repository):
    """Volatile, in-process persistence. Resets when the process restarts."""

    backend = "memory"

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[str, SessionRecord] = {}
        self._runs: list[RunRecord] = []
        self._plan_memory: list[PlanMemoryRecord] = []

    async def init(self) -> None:  # pragma: no cover - trivial
        return None

    async def close(self) -> None:  # pragma: no cover - trivial
        return None

    # -- sessions ------------------------------------------------------------

    async def create_session(self, record: SessionRecord) -> SessionRecord:
        async with self._lock:
            self._sessions[record.id] = record
        return record

    async def get_session(self, user_id: str, session_id: str) -> SessionRecord | None:
        async with self._lock:
            rec = self._sessions.get(session_id)
            if rec is None or rec.user_id != user_id:
                return None
            return rec

    async def list_sessions(self, user_id: str) -> list[SessionRecord]:
        async with self._lock:
            rows = [s for s in self._sessions.values() if s.user_id == user_id]
        return sorted(rows, key=lambda s: s.created_at, reverse=True)

    async def touch_session(self, user_id: str, session_id: str) -> None:
        async with self._lock:
            rec = self._sessions.get(session_id)
            if rec is not None and rec.user_id == user_id:
                rec.updated_at = _now()

    # -- runs ----------------------------------------------------------------

    async def save_run(self, record: RunRecord) -> RunRecord:
        async with self._lock:
            self._runs.append(record)
        return record

    async def list_runs(
        self, user_id: str, session_id: str | None = None, limit: int = 50
    ) -> list[RunRecord]:
        async with self._lock:
            rows = [
                r
                for r in self._runs
                if r.user_id == user_id and (session_id is None or r.session_id == session_id)
            ]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows[:limit]

    # -- plan memory ---------------------------------------------------------

    async def save_plan_memory(self, record: PlanMemoryRecord) -> PlanMemoryRecord:
        async with self._lock:
            self._plan_memory.append(record)
        return record

    async def search_plan_memory(
        self, user_id: str, embedding: list[float], top_k: int = 3
    ) -> list[PlanMemoryRecord]:
        async with self._lock:
            candidates = [m for m in self._plan_memory if m.user_id == user_id]
        scored = sorted(
            candidates, key=lambda m: _cosine(embedding, m.embedding), reverse=True
        )
        return scored[: max(0, top_k)]
