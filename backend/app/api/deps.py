"""Shared API dependencies and the application-wide state.

The global mutable singleton (a single shared ``WorldModel`` + services) has been
replaced by a per-user, per-session :class:`SessionRegistry`. ``AppState`` now
holds process-wide collaborators only — the repository, the shared planner config
(via the registry's planner factory), and the benchmark runner — while each user
gets their own live world + executor keyed by ``(user_id, session_id)``.

This module also builds the live auth dependency (:func:`make_require_user`),
which closes over the app's :class:`Settings` so the stdlib JWT verifier can read
``SUPABASE_JWT_SECRET``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Header, Request

from app.config import Settings, get_settings
from app.core.auth import AuthError, User, _extract_bearer, verify_supabase_jwt
from app.db.repository import Repository, get_repository
from app.services.benchmark import BenchmarkRunner
from app.services.planning_service import PlanningService
from app.services.session_registry import SessionRegistry


@dataclass
class AppState:
    """Process-wide collaborators (no per-user state lives here)."""

    settings: Settings
    repository: Repository
    registry: SessionRegistry
    benchmark: BenchmarkRunner
    planning: PlanningService  # shared, stateless facade for availability + benchmarks


def build_state(settings: Settings | None = None) -> AppState:
    """Construct the process-wide :class:`AppState`.

    The repository is selected per ``PERSISTENCE_BACKEND`` (memory by default,
    SQL when a ``DATABASE_URL`` + libs are present). ``init()``/``close()`` are
    driven from the app lifespan.
    """

    settings = settings or get_settings()
    repository = get_repository(settings)
    registry = SessionRegistry(settings, repository)
    planning = PlanningService(settings, repository=repository)
    return AppState(
        settings=settings,
        repository=repository,
        registry=registry,
        benchmark=BenchmarkRunner(settings),
        planning=planning,
    )


def get_state(request: Request) -> AppState:
    """FastAPI dependency returning the process-wide :class:`AppState`."""

    return request.app.state.app_state


def get_current_user(request: Request) -> User:
    """Return the :class:`User` set on the request by the auth dependency.

    The router-level ``require_user`` dependency runs first and stores the
    verified principal on ``request.state.user``; handlers read it back here.
    """

    user = getattr(request.state, "user", None)
    if user is None:  # pragma: no cover - require_user always runs first
        raise AuthError("request is not authenticated")
    return user


def make_require_user(settings: Settings) -> Callable[..., User]:
    """Build the live ``require_user`` dependency bound to ``settings``.

    Returns a FastAPI dependency that verifies the ``Authorization: Bearer
    <token>`` header against the Supabase JWT secret, stores the :class:`User`
    on ``request.state.user`` for downstream handlers, and returns it. When
    ``AUTH_REQUIRED`` is false (not the production default), it still verifies a
    supplied token but allows anonymous access.
    """

    def require_user(
        request: Request, authorization: str | None = Header(default=None)
    ) -> User:
        if not settings.auth_required:
            user = User(id="anonymous", email=None, role="anonymous")
            if authorization:
                with contextlib.suppress(AuthError):
                    user = verify_supabase_jwt(_extract_bearer(authorization), settings)
            request.state.user = user
            return user
        token = _extract_bearer(authorization)
        user = verify_supabase_jwt(token, settings)
        request.state.user = user
        return user

    return require_user
