"""Primitive robot actions (STRIPS-like).

Each primitive declares:

* a **name** and an ordered argument schema,
* a **precondition** predicate over a :class:`~app.domain.world_model.WorldModel`,
* an **effect** that mutates the world when applied.

The executor (and the planner's validator) only ever interact with the world
through these primitives, which keeps the action semantics in one place.

The primitive set:

==============  ===========================================================
``move_to``     Move the gripper above an object or location.
``pick``        Grasp a clear object (requires open, empty gripper, robot near).
``place``       Release the held object onto/into a target.
``open_gripper``  Open the gripper, dropping any held object onto the table.
``close_gripper`` Close the empty gripper.
``detect``      Perceive a target (no physical effect; logs what was seen).
``wait``        A no-op delay primitive.
==============  ===========================================================
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.domain.world_model import LocationKind, Vec2, WorldModel

# Distance within which the gripper is considered "at" a target.
REACH_TOLERANCE = 0.12


@dataclass(frozen=True)
class ActionResult:
    """Outcome of evaluating a primitive's precondition."""

    ok: bool
    reason: str = ""


@dataclass(frozen=True)
class PrimitiveSpec:
    """Static description of a primitive action."""

    name: str
    args: tuple[str, ...]
    description: str
    precondition: Callable[[WorldModel, dict[str, Any]], ActionResult]
    effect: Callable[[WorldModel, dict[str, Any]], None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "args": list(self.args),
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_target(world: WorldModel, target: str | None) -> ActionResult:
    if not target:
        return ActionResult(False, "missing 'target' argument")
    if not world.is_target_id(target):
        return ActionResult(False, f"unknown target '{target}'")
    return ActionResult(True)


def _near(world: WorldModel, target: str) -> bool:
    try:
        anchor = world.anchor_of(target)
    except KeyError:
        return False
    return world.robot.pose.distance_to(anchor) <= REACH_TOLERANCE


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------


def _pre_move_to(world: WorldModel, args: dict[str, Any]) -> ActionResult:
    return _require_target(world, args.get("target"))


def _pre_pick(world: WorldModel, args: dict[str, Any]) -> ActionResult:
    target = args.get("target")
    res = _require_target(world, target)
    if not res.ok:
        return res
    if target not in world.objects:
        return ActionResult(False, f"'{target}' is not a graspable object")
    if world.robot.holding is not None:
        return ActionResult(False, f"gripper already holding '{world.robot.holding}'")
    if not world.robot.gripper_open:
        return ActionResult(False, "gripper must be open before picking")
    if not world.is_clear(target):
        blockers = ", ".join(o.id for o in world.objects_on(target))
        return ActionResult(False, f"'{target}' is not clear (blocked by {blockers})")
    if not _near(world, target):
        return ActionResult(False, f"robot is not at '{target}' (move_to first)")
    return ActionResult(True)


def _pre_place(world: WorldModel, args: dict[str, Any]) -> ActionResult:
    target = args.get("target")
    res = _require_target(world, target)
    if not res.ok:
        return res
    if world.robot.holding is None:
        return ActionResult(False, "gripper is not holding anything to place")
    if target == world.robot.holding:
        return ActionResult(False, "cannot place an object onto itself")
    if target in world.objects and not world.is_clear(target):
        blockers = ", ".join(o.id for o in world.objects_on(target))
        return ActionResult(
            False, f"target '{target}' is not clear (blocked by {blockers})"
        )
    if not _near(world, target):
        return ActionResult(False, f"robot is not at '{target}' (move_to first)")
    return ActionResult(True)


def _pre_open(world: WorldModel, args: dict[str, Any]) -> ActionResult:
    if world.robot.gripper_open:
        return ActionResult(False, "gripper already open")
    return ActionResult(True)


def _pre_close(world: WorldModel, args: dict[str, Any]) -> ActionResult:
    if not world.robot.gripper_open:
        return ActionResult(False, "gripper already closed")
    if world.robot.holding is not None:
        return ActionResult(False, "cannot close gripper while holding an object")
    return ActionResult(True)


def _pre_detect(world: WorldModel, args: dict[str, Any]) -> ActionResult:
    # Detect is permissive: a missing/known target both succeed (scan the scene).
    target = args.get("target")
    if target and not world.is_target_id(target):
        return ActionResult(False, f"unknown target '{target}'")
    return ActionResult(True)


def _pre_wait(world: WorldModel, args: dict[str, Any]) -> ActionResult:
    return ActionResult(True)


# ---------------------------------------------------------------------------
# Effects
# ---------------------------------------------------------------------------


def _eff_move_to(world: WorldModel, args: dict[str, Any]) -> None:
    anchor = world.anchor_of(args["target"])
    world.robot.pose = Vec2(anchor.x, anchor.y)


def _eff_pick(world: WorldModel, args: dict[str, Any]) -> None:
    target = args["target"]
    obj = world.objects[target]
    obj.on_top_of = None
    obj.inside = None
    world.robot.holding = target
    world.robot.gripper_open = False
    # The grasped object tracks the gripper pose.
    obj.position = Vec2(world.robot.pose.x, world.robot.pose.y)


def _eff_place(world: WorldModel, args: dict[str, Any]) -> None:
    target = args["target"]
    held_id = world.robot.holding
    assert held_id is not None  # guaranteed by precondition
    held = world.objects[held_id]

    anchor = world.anchor_of(target)
    held.position = Vec2(anchor.x, anchor.y)

    location = world.get_location(target)
    if location is not None and location.kind == LocationKind.CONTAINER:
        held.inside = target
        held.on_top_of = None
    else:
        held.on_top_of = target
        held.inside = None

    world.robot.holding = None
    world.robot.gripper_open = True


def _eff_open(world: WorldModel, args: dict[str, Any]) -> None:
    # Opening drops any held object straight down onto the table.
    if world.robot.holding is not None:
        dropped = world.objects[world.robot.holding]
        dropped.on_top_of = "table"
        dropped.inside = None
        world.robot.holding = None
    world.robot.gripper_open = True


def _eff_close(world: WorldModel, args: dict[str, Any]) -> None:
    world.robot.gripper_open = False


def _eff_noop(world: WorldModel, args: dict[str, Any]) -> None:
    return None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


PRIMITIVES: dict[str, PrimitiveSpec] = {
    "move_to": PrimitiveSpec(
        "move_to",
        ("target",),
        "Move the gripper above an object or location.",
        _pre_move_to,
        _eff_move_to,
    ),
    "pick": PrimitiveSpec(
        "pick",
        ("target",),
        "Grasp a clear object; requires an open, empty gripper positioned at the object.",
        _pre_pick,
        _eff_pick,
    ),
    "place": PrimitiveSpec(
        "place",
        ("target",),
        "Release the currently held object onto a surface or into a container.",
        _pre_place,
        _eff_place,
    ),
    "open_gripper": PrimitiveSpec(
        "open_gripper",
        (),
        "Open the gripper, dropping any held object onto the table.",
        _pre_open,
        _eff_open,
    ),
    "close_gripper": PrimitiveSpec(
        "close_gripper",
        (),
        "Close an empty gripper.",
        _pre_close,
        _eff_close,
    ),
    "detect": PrimitiveSpec(
        "detect",
        ("target",),
        "Perceive a target object or scan the scene; has no physical effect.",
        _pre_detect,
        _eff_noop,
    ),
    "wait": PrimitiveSpec(
        "wait",
        ("seconds",),
        "Pause for a number of seconds; a no-op in simulation.",
        _pre_wait,
        _eff_noop,
    ),
}


def primitive_names() -> list[str]:
    """Ordered list of registered primitive names."""

    return list(PRIMITIVES)


def primitive_catalog() -> list[dict[str, Any]]:
    """Serialisable catalog of primitives for the ``/capabilities`` endpoint."""

    return [spec.to_dict() for spec in PRIMITIVES.values()]


def check_precondition(action: str, args: dict[str, Any], world: WorldModel) -> ActionResult:
    """Evaluate the precondition of ``action`` against ``world`` (no mutation)."""

    spec = PRIMITIVES.get(action)
    if spec is None:
        return ActionResult(False, f"unknown primitive '{action}'")
    return spec.precondition(world, args)


def apply(action: str, args: dict[str, Any], world: WorldModel) -> ActionResult:
    """Apply ``action`` to ``world`` if its precondition holds.

    Returns the precondition :class:`ActionResult`; on success the world has been
    mutated in place, on failure it is untouched.
    """

    spec = PRIMITIVES.get(action)
    if spec is None:
        return ActionResult(False, f"unknown primitive '{action}'")
    result = spec.precondition(world, args)
    if result.ok:
        spec.effect(world, args)
    return result
