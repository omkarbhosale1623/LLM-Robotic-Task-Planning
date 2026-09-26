"""SQLAlchemy(async) + asyncpg repository backed by Supabase Postgres.

**Import-guarded.** This module imports SQLAlchemy at module top level, which is
fine because it is only ever imported by :func:`app.db.repository.get_repository`
inside a ``try`` block — and only when ``DATABASE_URL`` is set. Nothing on the
boot path imports it unconditionally, so the app still starts (and tests pass)
when SQLAlchemy / asyncpg are absent.

Schema mirrors ``infra/supabase/schema.sql``. Plan-memory similarity uses the
pgvector ``<=>`` cosine-distance operator when the ``vector`` extension is
available; if it is not, the table column degrades to ``jsonb`` and similarity
is computed in Python (the same cosine the memory repo uses).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.logging import get_logger
from app.db.repository import (
    PlanMemoryRecord,
    Repository,
    RunRecord,
    SessionRecord,
    _now,
)

logger = get_logger(__name__)


class SqlRepository(Repository):
    """Async Postgres repository (Supabase). Tables are created if absent."""

    backend = "supabase"

    def __init__(self, dsn: str, settings: Any) -> None:
        self._engine: AsyncEngine = create_async_engine(dsn, pool_pre_ping=True, future=True)
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)
        self._dim = int(getattr(settings, "embedding_dim", 384))
        self._has_vector = False

    async def init(self) -> None:
        async with self._engine.begin() as conn:
            try:
                await conn.execute(text("create extension if not exists vector;"))
                self._has_vector = True
            except Exception:  # pragma: no cover - depends on DB privileges
                logger.warning("pgvector extension unavailable; plan memory uses jsonb fallback")
                self._has_vector = False

            await conn.execute(
                text(
                    """
                    create table if not exists sessions (
                        id uuid primary key default gen_random_uuid(),
                        user_id text not null,
                        project text not null default 'llm-robotic-task-planning',
                        config jsonb not null default '{}'::jsonb,
                        status text not null default 'active',
                        created_at timestamptz not null default now(),
                        updated_at timestamptz not null default now()
                    );
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    create table if not exists runs (
                        id uuid primary key default gen_random_uuid(),
                        session_id uuid not null,
                        user_id text not null,
                        kind text not null,
                        params jsonb not null default '{}'::jsonb,
                        metrics jsonb not null default '{}'::jsonb,
                        created_at timestamptz not null default now()
                    );
                    """
                )
            )
            embedding_col = f"vector({self._dim})" if self._has_vector else "jsonb"
            await conn.execute(
                text(
                    f"""
                    create table if not exists plan_memory (
                        id uuid primary key default gen_random_uuid(),
                        user_id text not null,
                        instruction text not null,
                        plan jsonb not null,
                        embedding {embedding_col},
                        created_at timestamptz not null default now()
                    );
                    """
                )
            )

    async def close(self) -> None:
        await self._engine.dispose()

    # -- sessions ------------------------------------------------------------

    async def create_session(self, record: SessionRecord) -> SessionRecord:
        async with self._sessionmaker() as session:
            await session.execute(
                text(
                    """
                    insert into sessions (id, user_id, project, config, status, created_at, updated_at)
                    values (:id, :user_id, :project, cast(:config as jsonb), :status, :created_at, :updated_at)
                    """
                ),
                {
                    "id": record.id,
                    "user_id": record.user_id,
                    "project": record.project,
                    "config": _json(record.config),
                    "status": record.status,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                },
            )
            await session.commit()
        return record

    async def get_session(self, user_id: str, session_id: str) -> SessionRecord | None:
        async with self._sessionmaker() as session:
            row = (
                await session.execute(
                    text(
                        "select id, user_id, project, config, status, created_at, updated_at "
                        "from sessions where id = :id and user_id = :user_id"
                    ),
                    {"id": session_id, "user_id": user_id},
                )
            ).mappings().first()
        return _session_from_row(row) if row else None

    async def list_sessions(self, user_id: str) -> list[SessionRecord]:
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    text(
                        "select id, user_id, project, config, status, created_at, updated_at "
                        "from sessions where user_id = :user_id order by created_at desc"
                    ),
                    {"user_id": user_id},
                )
            ).mappings().all()
        return [_session_from_row(r) for r in rows]

    async def touch_session(self, user_id: str, session_id: str) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                text(
                    "update sessions set updated_at = :ts where id = :id and user_id = :user_id"
                ),
                {"ts": _now(), "id": session_id, "user_id": user_id},
            )
            await session.commit()

    # -- runs ----------------------------------------------------------------

    async def save_run(self, record: RunRecord) -> RunRecord:
        async with self._sessionmaker() as session:
            await session.execute(
                text(
                    """
                    insert into runs (id, session_id, user_id, kind, params, metrics, created_at)
                    values (:id, :session_id, :user_id, :kind, cast(:params as jsonb),
                            cast(:metrics as jsonb), :created_at)
                    """
                ),
                {
                    "id": record.id,
                    "session_id": record.session_id,
                    "user_id": record.user_id,
                    "kind": record.kind,
                    "params": _json(record.params),
                    "metrics": _json(record.metrics),
                    "created_at": record.created_at,
                },
            )
            await session.commit()
        return record

    async def list_runs(
        self, user_id: str, session_id: str | None = None, limit: int = 50
    ) -> list[RunRecord]:
        clause = "where user_id = :user_id"
        params: dict[str, Any] = {"user_id": user_id, "limit": limit}
        if session_id is not None:
            clause += " and session_id = :session_id"
            params["session_id"] = session_id
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    text(
                        "select id, session_id, user_id, kind, params, metrics, created_at "
                        f"from runs {clause} order by created_at desc limit :limit"
                    ),
                    params,
                )
            ).mappings().all()
        return [_run_from_row(r) for r in rows]

    # -- plan memory ---------------------------------------------------------

    async def save_plan_memory(self, record: PlanMemoryRecord) -> PlanMemoryRecord:
        embedding_param = (
            _vector_literal(record.embedding) if self._has_vector else _json(record.embedding)
        )
        cast = "vector" if self._has_vector else "jsonb"
        async with self._sessionmaker() as session:
            await session.execute(
                text(
                    f"""
                    insert into plan_memory (id, user_id, instruction, plan, embedding, created_at)
                    values (:id, :user_id, :instruction, cast(:plan as jsonb),
                            cast(:embedding as {cast}), :created_at)
                    """
                ),
                {
                    "id": record.id,
                    "user_id": record.user_id,
                    "instruction": record.instruction,
                    "plan": _json(record.plan),
                    "embedding": embedding_param,
                    "created_at": record.created_at,
                },
            )
            await session.commit()
        return record

    async def search_plan_memory(
        self, user_id: str, embedding: list[float], top_k: int = 3
    ) -> list[PlanMemoryRecord]:
        if self._has_vector:
            async with self._sessionmaker() as session:
                rows = (
                    await session.execute(
                        text(
                            "select id, user_id, instruction, plan, created_at "
                            "from plan_memory where user_id = :user_id "
                            "order by embedding <=> cast(:embedding as vector) asc limit :limit"
                        ),
                        {
                            "user_id": user_id,
                            "embedding": _vector_literal(embedding),
                            "limit": top_k,
                        },
                    )
                ).mappings().all()
            return [_memory_from_row(r) for r in rows]

        # jsonb fallback: rank in Python.
        from app.db.memory_repo import _cosine

        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    text(
                        "select id, user_id, instruction, plan, embedding, created_at "
                        "from plan_memory where user_id = :user_id"
                    ),
                    {"user_id": user_id},
                )
            ).mappings().all()
        records = [_memory_from_row(r, with_embedding=True) for r in rows]
        records.sort(key=lambda m: _cosine(embedding, m.embedding), reverse=True)
        return records[: max(0, top_k)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json(value: Any) -> str:
    import json

    return json.dumps(value)


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"


def _coerce_json(value: Any) -> Any:
    import json

    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:  # pragma: no cover - defensive
            return value
    return value


def _session_from_row(row: Any) -> SessionRecord:
    return SessionRecord(
        id=str(row["id"]),
        user_id=row["user_id"],
        project=row["project"],
        config=_coerce_json(row["config"]) or {},
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _run_from_row(row: Any) -> RunRecord:
    return RunRecord(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        user_id=row["user_id"],
        kind=row["kind"],
        params=_coerce_json(row["params"]) or {},
        metrics=_coerce_json(row["metrics"]) or {},
        created_at=row["created_at"],
    )


def _memory_from_row(row: Any, with_embedding: bool = False) -> PlanMemoryRecord:
    embedding: list[float] = []
    if with_embedding:
        embedding = _coerce_json(row["embedding"]) or []
    return PlanMemoryRecord(
        id=str(row["id"]),
        user_id=row["user_id"],
        instruction=row["instruction"],
        plan=_coerce_json(row["plan"]) or {},
        embedding=embedding,
        created_at=row["created_at"],
    )
