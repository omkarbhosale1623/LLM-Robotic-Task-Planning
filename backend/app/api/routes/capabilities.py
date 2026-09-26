"""Capabilities catalog endpoint (primitives, scenes, commands, planner modes)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import AppState, get_state
from app.domain.primitives import primitive_catalog
from app.domain.world_model import available_scenes
from app.schemas.models import CapabilitiesResponse
from app.services.benchmark import benchmark_catalog

router = APIRouter()


@router.get(
    "/capabilities",
    response_model=CapabilitiesResponse,
    summary="List primitives, scenes, benchmark commands and planner modes",
)
def get_capabilities(state: AppState = Depends(get_state)) -> CapabilitiesResponse:
    return CapabilitiesResponse(
        primitives=primitive_catalog(),
        scenes=available_scenes(),
        benchmark_commands=benchmark_catalog(),
        planner_modes=["heuristic", "llm", "auto"],
        default_mode=state.settings.default_planner_mode,
        llm_available=state.planning.llm_available(),
        llm_backend=state.settings.llm_backend,
        llm_note=state.planning.availability_note(),
    )
