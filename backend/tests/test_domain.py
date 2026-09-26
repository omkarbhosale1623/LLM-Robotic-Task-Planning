"""Unit tests for the domain layer: world model, primitives, planner, validation."""

from __future__ import annotations

import pytest
from app.domain import primitives
from app.domain.planner import (
    HeuristicPlanner,
    Plan,
    PlanningError,
    PlanStep,
    validate_plan,
)
from app.domain.world_model import WorldModel


def test_world_reset_and_snapshot(world: WorldModel) -> None:
    snap = world.snapshot()
    ids = {o["id"] for o in snap["objects"]}
    assert {"red_block", "blue_block", "green_ball", "yellow_cup"} <= ids
    assert any(loc["id"] == "shelf" for loc in snap["locations"])
    assert snap["robot"]["holding"] is None


def test_pick_requires_move_first(world: WorldModel) -> None:
    # Without moving to the object, pick fails its precondition.
    res = primitives.check_precondition("pick", {"target": "red_block"}, world)
    assert not res.ok

    primitives.apply("move_to", {"target": "red_block"}, world)
    res = primitives.apply("pick", {"target": "red_block"}, world)
    assert res.ok
    assert world.robot.holding == "red_block"
    assert not world.robot.gripper_open


def test_place_updates_world(world: WorldModel) -> None:
    primitives.apply("move_to", {"target": "red_block"}, world)
    primitives.apply("pick", {"target": "red_block"}, world)
    primitives.apply("move_to", {"target": "shelf"}, world)
    res = primitives.apply("place", {"target": "shelf"}, world)
    assert res.ok
    assert world.robot.holding is None
    assert world.get_object("red_block").on_top_of == "shelf"


def test_heuristic_plan_simple_instruction(world: WorldModel) -> None:
    planner = HeuristicPlanner()
    plan = planner.plan("pick up the red block and place it on the shelf", world)
    actions = [s.action for s in plan.steps]
    assert actions == ["move_to", "pick", "move_to", "place"]
    assert plan.steps[1].args["target"] == "red_block"
    assert plan.steps[3].args["target"] == "shelf"

    result = validate_plan(plan, world)
    assert result.valid, result.errors


def test_heuristic_plan_into_container(world: WorldModel) -> None:
    planner = HeuristicPlanner()
    plan = planner.plan("move the green ball to the bin", world)
    assert validate_plan(plan, world).valid
    # Dry-run execution puts the ball inside the bin.
    sandbox = world.clone()
    for step in plan.steps:
        primitives.apply(step.action, step.args, sandbox)
    assert sandbox.get_object("green_ball").inside == "bin"


def test_planner_unstacks_blocked_object() -> None:
    world = WorldModel()
    world.reset("stack")  # red_block sits on blue_block
    planner = HeuristicPlanner()
    plan = planner.plan("put the blue block on the shelf", world)
    # Plan must first clear the red block off the blue block.
    assert any(s.action == "pick" and s.args.get("target") == "red_block" for s in plan.steps)
    assert validate_plan(plan, world).valid


def test_validation_rejects_bad_plan(world: WorldModel) -> None:
    # An ungrounded target and an illegal pick (no move first) must be rejected.
    bad = Plan(
        instruction="bad",
        steps=[
            PlanStep("pick", {"target": "purple_unicorn"}),  # ungrounded
            PlanStep("place", {"target": "shelf"}),  # nothing held
        ],
    )
    result = validate_plan(bad, world)
    assert not result.valid
    assert len(result.errors) >= 1


def test_validation_rejects_empty_plan(world: WorldModel) -> None:
    assert not validate_plan(Plan(instruction="x", steps=[]), world).valid


def test_planner_raises_on_ungroundable(world: WorldModel) -> None:
    planner = HeuristicPlanner()
    with pytest.raises(PlanningError):
        planner.plan("xyzzy frobnicate the widget", world)
