"""Benchmark suite endpoints (auth-protected; runs attributed per user)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import AppState, get_current_user, get_state
from app.core.auth import User
from app.db.repository import RunRecord
from app.schemas.models import BenchmarkRequest, BenchmarkResponse

router = APIRouter()


async def _run_and_record(
    state: AppState, user: User, mode: str, session_id: str | None
) -> BenchmarkResponse:
    report = state.benchmark.run(mode=mode)
    live = await state.registry.get_or_create(user, session_id)
    await state.repository.save_run(
        RunRecord(
            session_id=live.session_id,
            user_id=user.id,
            kind="benchmark",
            params={"mode": mode},
            metrics={
                "total": report.total,
                "passed": report.passed,
                "success_rate": round(report.completion_rate, 4),
            },
        )
    )
    return BenchmarkResponse(**report.to_dict())


@router.get("/benchmark", response_model=BenchmarkResponse, summary="Run the benchmark suite")
async def run_benchmark_get(
    mode: str = Query(default="heuristic", pattern="^(heuristic|llm|auto)$"),
    session_id: str | None = Query(default=None),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> BenchmarkResponse:
    """Run the fixed 20-command suite and report the task-completion rate."""

    return await _run_and_record(state, user, mode, session_id)


@router.post("/benchmark", response_model=BenchmarkResponse, summary="Run the benchmark suite")
async def run_benchmark_post(
    body: BenchmarkRequest,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> BenchmarkResponse:
    return await _run_and_record(state, user, body.mode, body.session_id)
