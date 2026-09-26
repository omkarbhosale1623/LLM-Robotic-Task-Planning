"""Planning, execution, and plan-and-run endpoints (per-user, per-session)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import AppState, get_current_user, get_state
from app.core.auth import User
from app.core.errors import NotFoundError
from app.db.repository import RunRecord
from app.domain.planner import Plan, PlanStep
from app.domain.world_model import WorldModel, available_scenes
from app.schemas.models import (
    ExecuteRequest,
    ExecuteResponse,
    PlanAndRunRequest,
    PlanAndRunResponse,
    PlanRequest,
    PlanResponse,
)

router = APIRouter()


def _resolve_scene(scene: str | None) -> None:
    if scene is not None and scene not in available_scenes():
        raise NotFoundError(f"Unknown scene '{scene}'.", {"available": available_scenes()})


def _resolve_mode(state: AppState, mode: str | None) -> str:
    return mode or state.settings.default_planner_mode


@router.post("/plan", response_model=PlanResponse, summary="Decompose an instruction into a plan")
async def create_plan(
    body: PlanRequest,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> PlanResponse:
    """Turn a natural-language instruction into a validated, ordered plan.

    Plans against the caller's session world by default. Set
    ``use_current_world=false`` (optionally with ``scene``) to plan against a
    fresh scene without mutating the session world. Each successful plan is
    stored to the user's plan memory for few-shot retrieval on later requests.
    """

    live = await state.registry.get_or_create(user, body.session_id, scene=body.scene)
    mode = _resolve_mode(state, body.mode)

    if body.use_current_world:
        world = live.world
    else:
        _resolve_scene(body.scene)
        world = WorldModel()
        world.reset(body.scene or state.settings.default_scene)

    async with live.lock:
        outcome = await live.planning.plan_with_memory(
            body.instruction, world, mode=mode, user_id=user.id
        )

    await state.repository.save_run(
        RunRecord(
            session_id=live.session_id,
            user_id=user.id,
            kind="plan",
            params={"instruction": body.instruction, "mode": mode},
            metrics={
                "planner_used": outcome.planner_used,
                "valid": outcome.validation.valid,
                "steps": len(outcome.plan.steps),
            },
        )
    )
    return PlanResponse(session_id=live.session_id, **outcome.to_dict())


@router.post("/execute", response_model=ExecuteResponse, summary="Execute a plan step-by-step")
async def execute_plan(
    body: ExecuteRequest,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> ExecuteResponse:
    """Execute a client-supplied plan against the caller's session world."""

    live = await state.registry.get_or_create(user, body.session_id, scene=body.reset_scene)

    if body.reset_scene is not None:
        _resolve_scene(body.reset_scene)

    plan = Plan(
        instruction=body.instruction,
        steps=[PlanStep(action=s.action, args=s.args, rationale=s.rationale) for s in body.plan],
    )
    async with live.lock:
        if body.reset_scene is not None:
            live.world.reset(body.reset_scene)
        report = live.executor.execute(
            plan, live.world, continue_on_error=body.continue_on_error
        )

    await state.repository.save_run(
        RunRecord(
            session_id=live.session_id,
            user_id=user.id,
            kind="execute",
            params={"steps": [s.to_dict() for s in plan.steps]},
            metrics={"success": report.success, "steps_executed": report.steps_executed},
        )
    )
    return ExecuteResponse(session_id=live.session_id, **report.to_dict())


@router.post(
    "/plan-and-run",
    response_model=PlanAndRunResponse,
    summary="Plan an instruction and execute it in one call",
)
async def plan_and_run(
    body: PlanAndRunRequest,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> PlanAndRunResponse:
    """Plan ``instruction`` then immediately execute it against the session world."""

    live = await state.registry.get_or_create(user, body.session_id, scene=body.reset_scene)
    mode = _resolve_mode(state, body.mode)

    if body.reset_scene is not None:
        _resolve_scene(body.reset_scene)

    async with live.lock:
        if body.reset_scene is not None:
            live.world.reset(body.reset_scene)
        outcome = await live.planning.plan_with_memory(
            body.instruction, live.world, mode=mode, user_id=user.id
        )
        execution: ExecuteResponse | None = None
        if outcome.validation.valid and outcome.plan.steps:
            report = live.executor.execute(
                outcome.plan, live.world, continue_on_error=body.continue_on_error
            )
            execution = ExecuteResponse(session_id=live.session_id, **report.to_dict())

    await state.repository.save_run(
        RunRecord(
            session_id=live.session_id,
            user_id=user.id,
            kind="plan-and-run",
            params={"instruction": body.instruction, "mode": mode},
            metrics={
                "planner_used": outcome.planner_used,
                "valid": outcome.validation.valid,
                "executed": execution.success if execution else False,
            },
        )
    )

    payload = outcome.to_dict()
    return PlanAndRunResponse(
        session_id=live.session_id,
        plan=payload["plan"],
        validation=payload["validation"],
        planner_used=payload["planner_used"],
        llm_available=payload["llm_available"],
        notes=payload["notes"],
        execution=execution,
    )
