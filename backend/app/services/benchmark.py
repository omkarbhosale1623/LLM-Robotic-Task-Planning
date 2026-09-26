"""Benchmark suite.

A fixed suite of 20 natural-language commands, each paired with a scene and an
``expected`` predicate describing the success condition. For each command the
benchmark:

1. resets a fresh world to the command's scene,
2. plans the instruction (heuristic or LLM, via :class:`PlanningService`),
3. executes the plan,
4. checks the expected outcome predicate against the final world.

It reports per-command success and the overall task-completion rate — the headline
metric for the project's README.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.core.metrics import set_benchmark_success_rate
from app.db.repository import Repository
from app.domain.world_model import WorldModel
from app.services.executor import Executor
from app.services.planning_service import PlanningService

# A predicate over the final world state -> (passed, human readable detail).
Predicate = Callable[[WorldModel], "tuple[bool, str]"]


# ---------------------------------------------------------------------------
# Outcome predicate factories
# ---------------------------------------------------------------------------


def on(object_id: str, target_id: str) -> Predicate:
    def check(world: WorldModel) -> tuple[bool, str]:
        obj = world.get_object(object_id)
        if obj is None:
            return False, f"{object_id} missing from world"
        ok = obj.on_top_of == target_id
        return ok, f"{object_id}.on_top_of={obj.on_top_of} (want {target_id})"

    return check


def inside(object_id: str, container_id: str) -> Predicate:
    def check(world: WorldModel) -> tuple[bool, str]:
        obj = world.get_object(object_id)
        if obj is None:
            return False, f"{object_id} missing from world"
        ok = obj.inside == container_id
        return ok, f"{object_id}.inside={obj.inside} (want {container_id})"

    return check


def near_location(object_id: str, location_id: str, tol: float = 0.18) -> Predicate:
    def check(world: WorldModel) -> tuple[bool, str]:
        obj = world.get_object(object_id)
        loc = world.get_location(location_id)
        if obj is None or loc is None:
            return False, "object or location missing"
        dist = obj.position.distance_to(loc.anchor)
        return dist <= tol, f"dist({object_id},{location_id})={dist:.3f} (tol {tol})"

    return check


def held(object_id: str) -> Predicate:
    def check(world: WorldModel) -> tuple[bool, str]:
        ok = world.robot.holding == object_id
        return ok, f"robot.holding={world.robot.holding} (want {object_id})"

    return check


def all_of(*predicates: Predicate) -> Predicate:
    def check(world: WorldModel) -> tuple[bool, str]:
        details = []
        ok_all = True
        for p in predicates:
            ok, detail = p(world)
            ok_all = ok_all and ok
            details.append(detail)
        return ok_all, "; ".join(details)

    return check


def plan_is_valid() -> Predicate:
    """Sentinel predicate; success is decided by plan validity + execution only.

    Used for perception-only commands where there is no world-state change.
    """

    def check(world: WorldModel) -> tuple[bool, str]:
        return True, "perception command (no state change expected)"

    return check


# ---------------------------------------------------------------------------
# Suite definition
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkCommand:
    id: int
    instruction: str
    scene: str
    expected: Predicate
    description: str


BENCHMARK_SUITE: list[BenchmarkCommand] = [
    BenchmarkCommand(1, "pick up the red block", "default", held("red_block"),
                     "Grasp a single object."),
    BenchmarkCommand(2, "pick up the red block and place it on the shelf", "default",
                     on("red_block", "shelf"), "Canonical pick-and-place onto a surface."),
    BenchmarkCommand(3, "put the blue block on the shelf", "default",
                     on("blue_block", "shelf"), "Place by color onto the shelf."),
    BenchmarkCommand(4, "move the green ball to the bin", "default",
                     inside("green_ball", "bin"), "Move into a container."),
    BenchmarkCommand(5, "place the yellow cup in the bin", "default",
                     inside("yellow_cup", "bin"), "Place a cup into the bin."),
    BenchmarkCommand(6, "put the red block in the left zone", "default",
                     near_location("red_block", "left_zone"), "Move to a named zone."),
    BenchmarkCommand(7, "move the blue block to the right zone", "default",
                     near_location("blue_block", "right_zone"), "Move to the right zone."),
    BenchmarkCommand(8, "grab the green ball", "default", held("green_ball"),
                     "Grasp using a synonym verb."),
    BenchmarkCommand(9, "stack the red block on the blue block", "default",
                     on("red_block", "blue_block"), "Stack one block on another."),
    BenchmarkCommand(10, "pick up the red block then place it on the shelf", "default",
                     on("red_block", "shelf"), "Two-clause sequence with 'then'."),
    BenchmarkCommand(11, "put the red block on the shelf and then put the blue block on the shelf",
                     "default", all_of(on("red_block", "shelf"), on("blue_block", "shelf")),
                     "Two pick-and-place tasks chained."),
    BenchmarkCommand(12, "move the green ball to the bin then move the blue block to the bin",
                     "default", all_of(inside("green_ball", "bin"), inside("blue_block", "bin")),
                     "Two moves into the bin."),
    BenchmarkCommand(13, "detect the red block", "default", plan_is_valid(),
                     "Perception-only command."),
    BenchmarkCommand(14, "find the yellow cup", "default", plan_is_valid(),
                     "Perception with a synonym verb."),
    BenchmarkCommand(15, "take the red block from the top of the blue block", "stack",
                     held("red_block"), "Unstack the top block in a stacked scene."),
    BenchmarkCommand(16, "put the red block on the shelf", "stack", on("red_block", "shelf"),
                     "Pick a stacked block and place it on the shelf."),
    BenchmarkCommand(17, "place the green block on the blue block", "stack",
                     on("green_block", "blue_block"),
                     "Stack onto a block that is itself supporting another (auto-clear)."),
    BenchmarkCommand(18, "move all the red things to the left zone", "sorting",
                     near_location("red_block", "left_zone"),
                     "Move a red object to a zone (sorting scene)."),
    BenchmarkCommand(19, "put the green ball in the bin", "sorting", inside("green_ball", "bin"),
                     "Sort a ball into the bin."),
    BenchmarkCommand(20, "pick up the yellow cup and place it on the shelf", "sorting",
                     on("yellow_cup", "shelf"), "Pick-and-place in the sorting scene."),
]


@dataclass
class CommandResult:
    id: int
    instruction: str
    scene: str
    description: str
    planner_used: str
    plan_valid: bool
    executed_ok: bool
    outcome_ok: bool
    passed: bool
    detail: str
    step_count: int
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "instruction": self.instruction,
            "scene": self.scene,
            "description": self.description,
            "planner_used": self.planner_used,
            "plan_valid": self.plan_valid,
            "executed_ok": self.executed_ok,
            "outcome_ok": self.outcome_ok,
            "passed": self.passed,
            "detail": self.detail,
            "step_count": self.step_count,
            "notes": self.notes,
        }


@dataclass
class BenchmarkReport:
    total: int
    passed: int
    completion_rate: float
    mode: str
    results: list[CommandResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "completion_rate": round(self.completion_rate, 4),
            "mode": self.mode,
            "results": [r.to_dict() for r in self.results],
        }


class BenchmarkRunner:
    """Runs the fixed benchmark suite and computes the task-completion rate."""

    def __init__(self, settings: Settings, repository: Repository | None = None) -> None:
        self.settings = settings
        # The benchmark uses the synchronous plan() path (no per-user plan
        # memory), so the repository is optional here and only forwarded for
        # consistent LLM/availability configuration.
        self.planning = PlanningService(settings, repository=repository)
        self.executor = Executor()

    def run(self, mode: str = "heuristic") -> BenchmarkReport:
        """Run all 20 commands and return an aggregate :class:`BenchmarkReport`."""

        results: list[CommandResult] = []
        for cmd in BENCHMARK_SUITE:
            results.append(self._run_command(cmd, mode))

        passed = sum(1 for r in results if r.passed)
        rate = passed / len(results) if results else 0.0
        # Publish the headline completion rate to Prometheus (no-op if the
        # optional metrics backend is unavailable).
        set_benchmark_success_rate(mode, rate)
        return BenchmarkReport(
            total=len(results),
            passed=passed,
            completion_rate=rate,
            mode=mode,
            results=results,
        )

    def _run_command(self, cmd: BenchmarkCommand, mode: str) -> CommandResult:
        world = WorldModel()
        world.reset(cmd.scene)

        outcome = self.planning.plan(cmd.instruction, world, mode=mode)
        plan = outcome.plan
        plan_valid = outcome.validation.valid

        executed_ok = False
        outcome_ok = False
        detail = ""

        if plan_valid and plan.steps:
            report = self.executor.execute(plan, world)
            executed_ok = report.success
            outcome_ok, detail = cmd.expected(world)
            if not executed_ok:
                detail = f"execution: {report.message}; outcome: {detail}"
        else:
            detail = "; ".join(outcome.validation.errors) or "no valid plan produced"

        passed = plan_valid and executed_ok and outcome_ok
        return CommandResult(
            id=cmd.id,
            instruction=cmd.instruction,
            scene=cmd.scene,
            description=cmd.description,
            planner_used=outcome.planner_used,
            plan_valid=plan_valid,
            executed_ok=executed_ok,
            outcome_ok=outcome_ok,
            passed=passed,
            detail=detail,
            step_count=len(plan.steps),
            notes=outcome.notes,
        )


def benchmark_catalog() -> list[dict[str, Any]]:
    """Serialisable list of benchmark commands (for the ``/capabilities`` view)."""

    return [
        {"id": c.id, "instruction": c.instruction, "scene": c.scene, "description": c.description}
        for c in BENCHMARK_SUITE
    ]
