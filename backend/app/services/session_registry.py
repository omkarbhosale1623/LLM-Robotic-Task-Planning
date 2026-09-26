"""Per-(user, session) live state, replacing the old global singleton.

Each user gets their own evolving :class:`WorldModel` + :class:`Executor` per
session, so concurrent users never see each other's tabletop. Within a single
session, an ``asyncio.Lock`` serialises mutating requests (so two tabs editing
the same session don't interleave half-applied plans); different sessions run
independently.

A :class:`LiveSession` is created on first touch (``get_or_create``) and is also
recorded in the :class:`~app.db.repository.Repository` so any backend instance
can read the user's session/run history. Idle sessions are evicted after
``session_ttl_seconds`` to bound memory.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.config import Settings
from app.core.auth import User
from app.core.logging import get_logger
from app.db.repository import Repository, SessionRecord
from app.domain.world_model import WorldModel
from app.services.executor import Executor
from app.services.planning_service import PlanningService

logger = get_logger(__name__)


@dataclass
class LiveSession:
    """One user's live, in-process world + services for a single session."""

    session_id: str
    user_id: str
    settings: Settings
    world: WorldModel
    executor: Executor
    planning: PlanningService
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_used: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        self.last_used = time.monotonic()


class SessionRegistry:
    """Holds live sessions keyed by ``(user_id, session_id)``.

    The registry persists session metadata through the repository, enforces that
    a user may only touch their own sessions, and evicts idle in-process state.
    The shared planner/repository are injected so embeddings, plan memory, and
    LLM config are consistent across all sessions.
    """

    def __init__(self, settings: Settings, repository: Repository) -> None:
        self.settings = settings
        self.repository = repository
        self._sessions: dict[tuple[str, str], LiveSession] = {}
        self._guard = asyncio.Lock()

    async def get_or_create(
        self, user: User, session_id: str | None, scene: str | None = None
    ) -> LiveSession:
        """Return the live session, creating + persisting it on first use.

        If ``session_id`` is None a new session is minted. If a ``session_id`` is
        supplied but belongs to another user (or is unknown and not creatable),
        a fresh session is created under the caller — a user can never address
        another user's state.
        """

        await self._evict_idle()

        if session_id is not None:
            live = await self._get_live(user.id, session_id)
            if live is not None:
                live.touch()
                return live
            # Not live in-process: check persistence for ownership.
            record = await self.repository.get_session(user.id, session_id)
            if record is not None:
                return await self._materialise(user, record, scene)

        # Mint a brand-new session.
        record = SessionRecord(
            user_id=user.id,
            project="llm-robotic-task-planning",
            config={"scene": scene or self.settings.default_scene},
        )
        if session_id is not None:
            record.id = session_id  # honour a caller-chosen id for a new session
        await self.repository.create_session(record)
        return await self._materialise(user, record, scene)

    async def get(self, user: User, session_id: str) -> LiveSession | None:
        """Return a live session iff it exists and the caller owns it."""

        live = await self._get_live(user.id, session_id)
        if live is not None:
            live.touch()
            return live
        record = await self.repository.get_session(user.id, session_id)
        if record is None:
            return None
        return await self._materialise(user, record, None)

    async def drop(self, user: User, session_id: str) -> None:
        async with self._guard:
            self._sessions.pop((user.id, session_id), None)

    async def _get_live(self, user_id: str, session_id: str) -> LiveSession | None:
        async with self._guard:
            return self._sessions.get((user_id, session_id))

    async def _materialise(
        self, user: User, record: SessionRecord, scene: str | None
    ) -> LiveSession:
        world = WorldModel()
        chosen_scene = scene or record.config.get("scene") or self.settings.default_scene
        try:
            world.reset(chosen_scene)
        except KeyError:
            world.reset(self.settings.default_scene)
        live = LiveSession(
            session_id=record.id,
            user_id=user.id,
            settings=self.settings,
            world=world,
            executor=Executor(),
            planning=PlanningService(self.settings, repository=self.repository),
        )
        async with self._guard:
            self._sessions[(user.id, record.id)] = live
        await self.repository.touch_session(user.id, record.id)
        return live

    async def _evict_idle(self) -> None:
        ttl = max(1, int(self.settings.session_ttl_seconds))
        now = time.monotonic()
        async with self._guard:
            stale = [k for k, s in self._sessions.items() if now - s.last_used > ttl]
            for key in stale:
                self._sessions.pop(key, None)
        if stale:
            logger.info("evicted %d idle session(s)", len(stale))
