"""Pydantic v2 request/response models.

These mirror the dataclasses in the domain/service layers but keep the HTTP
contract explicit and self-documenting. Where a response wraps deeply nested,
already-serialised dictionaries (world snapshots, step events), the models use
permissive ``dict``/``Any`` typing so the OpenAPI schema stays readable without
duplicating every nested shape.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PlannerMode = Literal["heuristic", "llm", "auto"]


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


class PlanStepModel(BaseModel):
    action: str = Field(..., examples=["move_to"])
    args: dict[str, Any] = Field(default_factory=dict, examples=[{"target": "red_block"}])
    rationale: str = ""


class PlanModel(BaseModel):
    instruction: str
    planner: str
    steps: list[PlanStepModel]
    notes: list[str] = Field(default_factory=list)


class ValidationModel(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    grounded_targets: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Health & world
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str = "ok"
    app: str
    version: str
    llm_available: bool
    llm_note: str


class WorldResponse(BaseModel):
    scene_name: str
    objects: list[dict[str, Any]]
    locations: list[dict[str, Any]]
    robot: dict[str, Any]


class SceneConfigRequest(BaseModel):
    """Reset to a named scene, or load a fully custom scene description."""

    scene: str | None = Field(
        default=None,
        description="Name of a built-in scene to reset to (e.g. 'default', 'stack').",
    )
    custom: dict[str, Any] | None = Field(
        default=None,
        description="A full scene payload with objects/locations/robot to load.",
    )


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


class PlanRequest(BaseModel):
    instruction: str = Field(
        ...,
        min_length=1,
        examples=["pick up the red block and place it on the shelf"],
    )
    mode: PlannerMode | None = Field(
        default=None,
        description="Planner mode; defaults to 'llm' when a provider key is set, else 'heuristic'.",
    )
    session_id: str | None = Field(
        default=None,
        description="Session to plan within; a new one is created when omitted.",
    )
    use_current_world: bool = Field(
        default=True,
        description="Plan against the session's live world; if false a fresh scene is used.",
    )
    scene: str | None = Field(
        default=None,
        description="Optional scene to plan against (only when use_current_world is false).",
    )


class PlanResponse(BaseModel):
    session_id: str
    plan: PlanModel
    validation: ValidationModel
    planner_used: str
    requested_mode: str
    llm_available: bool
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class ExecuteRequest(BaseModel):
    plan: list[PlanStepModel] = Field(..., min_length=1)
    instruction: str = ""
    session_id: str | None = Field(
        default=None,
        description="Session to execute within; a new one is created when omitted.",
    )
    continue_on_error: bool = False
    reset_scene: str | None = Field(
        default=None,
        description="Optional scene to reset the world to before executing.",
    )


class ExecuteResponse(BaseModel):
    session_id: str | None = None
    success: bool
    steps_total: int
    steps_executed: int
    steps_succeeded: int
    events: list[dict[str, Any]]
    final_state: dict[str, Any] | None
    message: str


class PlanAndRunRequest(BaseModel):
    instruction: str = Field(..., min_length=1)
    mode: PlannerMode | None = Field(
        default=None,
        description="Planner mode; defaults to 'llm' when a provider key is set, else 'heuristic'.",
    )
    session_id: str | None = Field(
        default=None,
        description="Session to plan+run within; a new one is created when omitted.",
    )
    reset_scene: str | None = Field(
        default=None,
        description="Optional scene to reset the world to before planning+running.",
    )
    continue_on_error: bool = False


class PlanAndRunResponse(BaseModel):
    session_id: str
    plan: PlanModel
    validation: ValidationModel
    planner_used: str
    llm_available: bool
    notes: list[str] = Field(default_factory=list)
    execution: ExecuteResponse | None = None


# ---------------------------------------------------------------------------
# Benchmark & capabilities
# ---------------------------------------------------------------------------


class BenchmarkRequest(BaseModel):
    mode: PlannerMode = Field(default="heuristic")
    session_id: str | None = Field(
        default=None,
        description="Optional session to attribute the benchmark run to.",
    )


class BenchmarkResponse(BaseModel):
    total: int
    passed: int
    completion_rate: float
    mode: str
    results: list[dict[str, Any]]


class CapabilitiesResponse(BaseModel):
    primitives: list[dict[str, Any]]
    scenes: list[str]
    benchmark_commands: list[dict[str, Any]]
    planner_modes: list[str]
    default_mode: str
    llm_available: bool
    llm_backend: str
    llm_note: str


# ---------------------------------------------------------------------------
# Sessions & runs
# ---------------------------------------------------------------------------


class SessionModel(BaseModel):
    id: str
    user_id: str
    project: str
    config: dict[str, Any] = Field(default_factory=dict)
    status: str
    created_at: str
    updated_at: str


class SessionListResponse(BaseModel):
    sessions: list[SessionModel]


class RunModel(BaseModel):
    id: str
    session_id: str
    user_id: str
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class RunListResponse(BaseModel):
    runs: list[RunModel]
