"""Session and run history endpoints (per-user, persisted)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import AppState, get_current_user, get_state
from app.core.auth import User
from app.core.errors import NotFoundError
from app.schemas.models import (
    RunListResponse,
    RunModel,
    SessionListResponse,
    SessionModel,
)

router = APIRouter()


@router.post("/sessions", response_model=SessionModel, summary="Create a new session")
async def create_session(
    scene: str | None = Query(default=None),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> SessionModel:
    """Create a fresh per-user session (its own world + executor)."""

    live = await state.registry.get_or_create(user, None, scene=scene)
    record = await state.repository.get_session(user.id, live.session_id)
    return SessionModel(**record.to_dict())


@router.get("/sessions", response_model=SessionListResponse, summary="List the caller's sessions")
async def list_sessions(
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> SessionListResponse:
    records = await state.repository.list_sessions(user.id)
    return SessionListResponse(sessions=[SessionModel(**r.to_dict()) for r in records])


@router.get(
    "/sessions/{session_id}/runs",
    response_model=RunListResponse,
    summary="List runs for one of the caller's sessions",
)
async def list_session_runs(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> RunListResponse:
    record = await state.repository.get_session(user.id, session_id)
    if record is None:
        raise NotFoundError(f"Unknown session '{session_id}'.")
    runs = await state.repository.list_runs(user.id, session_id=session_id, limit=limit)
    return RunListResponse(runs=[RunModel(**r.to_dict()) for r in runs])


@router.get("/runs", response_model=RunListResponse, summary="List the caller's recent runs")
async def list_runs(
    limit: int = Query(default=50, ge=1, le=500),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> RunListResponse:
    runs = await state.repository.list_runs(user.id, limit=limit)
    return RunListResponse(runs=[RunModel(**r.to_dict()) for r in runs])
