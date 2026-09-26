"""Tests for the executor, planning service and benchmark."""

from __future__ import annotations

from app.config import Settings
from app.domain.planner import HeuristicPlanner
from app.domain.world_model import WorldModel
from app.services.benchmark import BenchmarkRunner
from app.services.executor import Executor
from app.services.planning_service import PlanningService


def test_executor_emits_events_and_updates_world(world: WorldModel) -> None:
    plan = HeuristicPlanner().plan("pick up the red block", world)
    report = Executor().execute(plan, world)
    assert report.success
    assert report.steps_executed == report.steps_total
    # Gripper now holds the block.
    assert world.robot.holding == "red_block"
    # Each event carries pre/post snapshots.
    assert all("robot" in e.pre_state and "robot" in e.post_state for e in report.events)


def test_executor_fails_fast_on_bad_step(world: WorldModel) -> None:
    from app.domain.planner import Plan, PlanStep

    plan = Plan(
        instruction="x",
        steps=[PlanStep("pick", {"target": "red_block"})],  # missing move_to first
    )
    report = Executor().execute(plan, world)
    assert not report.success
    assert report.steps_succeeded == 0


def test_planning_service_falls_back_without_llm(settings: Settings, world: WorldModel) -> None:
    service = PlanningService(settings)
    assert not service.llm_available()
    outcome = service.plan("pick up the red block and place it on the shelf", world, mode="llm")
    # LLM unavailable => heuristic planner used, with an explanatory note.
    assert outcome.planner_used == "heuristic"
    assert outcome.validation.valid
    assert any("heuristic" in n.lower() for n in outcome.notes)


def test_benchmark_returns_rate(settings: Settings) -> None:
    report = BenchmarkRunner(settings).run(mode="heuristic")
    assert report.total == 20
    assert 0.0 <= report.completion_rate <= 1.0
    # The deterministic planner should solve the large majority of the suite.
    assert report.passed >= 16
    assert all("passed" in r.to_dict() for r in report.results)
