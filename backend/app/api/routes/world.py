"""World inspection and scene configuration endpoints (per-user, per-session)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import AppState, get_current_user, get_state
from app.core.auth import User
from app.core.errors import NotFoundError
from app.domain.world_model import available_scenes
from app.schemas.models import SceneConfigRequest, WorldResponse

router = APIRouter()


@router.get("/world", response_model=WorldResponse, summary="Get the caller's session world state")
async def get_world(
    session_id: str | None = Query(default=None),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> WorldResponse:
    live = await state.registry.get_or_create(user, session_id)
    return WorldResponse(**live.world.snapshot())


@router.post("/world/reset", response_model=WorldResponse, summary="Reset or configure the scene")
async def reset_world(
    body: SceneConfigRequest,
    session_id: str | None = Query(default=None),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> WorldResponse:
    """Reset the session world to a built-in scene, or load a custom scene."""

    live = await state.registry.get_or_create(user, session_id)
    async with live.lock:
        if body.custom is not None:
            live.world.load_scene(body.custom)
        else:
            scene = body.scene or state.settings.default_scene
            if scene not in available_scenes():
                raise NotFoundError(
                    f"Unknown scene '{scene}'.", {"available": available_scenes()}
                )
            live.world.reset(scene)
        snapshot = live.world.snapshot()
    return WorldResponse(**snapshot)


@router.get("/world/scenes", summary="List the built-in scenes")
def list_scenes() -> dict[str, list[str]]:
    return {"scenes": available_scenes()}
