"""Tabletop world model.

A deterministic, GPU-free simulation of a simple tabletop manipulation scene.
The world holds:

* **Objects** — colored shapes (block, ball, cup, ...) with a 2D position, the
  surface/object they rest on, and an optional ``inside`` relation (for bins/cups).
* **Locations** — named regions of the table (table, shelf, bin, zones) with a
  2D anchor used both for grounding and for the front-end scene visualiser.
* **Robot** — a gripper with a pose and a ``holding`` reference.

The model is intentionally STRIPS-like: state is a set of typed facts, and the
primitive actions in :mod:`app.domain.primitives` read/modify this state through
a small, well-defined surface. Everything is JSON-serialisable so it can be
streamed to the front-end over REST/WebSocket.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class LocationKind(str, Enum):
    """Semantic category of a location, used by the scene renderer."""

    SURFACE = "surface"  # table, shelf — things can be placed on top
    CONTAINER = "container"  # bin, box — things go *inside*
    ZONE = "zone"  # an abstract region on the table


@dataclass(frozen=True)
class Vec2:
    """A 2D point in table coordinates (metres-ish, arbitrary but consistent)."""

    x: float
    y: float

    def to_dict(self) -> dict[str, float]:
        return {"x": round(self.x, 4), "y": round(self.y, 4)}

    def distance_to(self, other: Vec2) -> float:
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5


@dataclass
class WorldObject:
    """A manipulable object on the table."""

    id: str
    color: str
    shape: str  # block | ball | cup | cube | bowl ...
    position: Vec2
    on_top_of: str | None = None  # id of object/location it rests on
    inside: str | None = None  # id of a container it sits inside
    size: float = 0.08

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "color": self.color,
            "shape": self.shape,
            "position": self.position.to_dict(),
            "on_top_of": self.on_top_of,
            "inside": self.inside,
            "size": self.size,
        }


@dataclass
class Location:
    """A named region of the workspace."""

    id: str
    name: str
    kind: LocationKind
    anchor: Vec2
    width: float = 0.30
    height: float = 0.30

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind.value,
            "anchor": self.anchor.to_dict(),
            "width": self.width,
            "height": self.height,
        }


@dataclass
class Robot:
    """The single-arm robot with a gripper."""

    pose: Vec2
    gripper_open: bool = True
    holding: str | None = None  # id of the object currently grasped

    def to_dict(self) -> dict[str, Any]:
        return {
            "pose": self.pose.to_dict(),
            "gripper_open": self.gripper_open,
            "holding": self.holding,
        }


# ---------------------------------------------------------------------------
# World model
# ---------------------------------------------------------------------------


class WorldModel:
    """A mutable tabletop world supporting reset, scene configuration, and queries."""

    def __init__(self) -> None:
        self.objects: dict[str, WorldObject] = {}
        self.locations: dict[str, Location] = {}
        self.robot: Robot = Robot(pose=Vec2(0.0, 0.0))
        self.scene_name: str = "empty"
        self.reset()

    # -- construction --------------------------------------------------------

    def reset(self, scene: str = "default") -> None:
        """Reset the world to one of the built-in scenes."""

        builder = _SCENES.get(scene)
        if builder is None:
            raise KeyError(
                f"Unknown scene '{scene}'. Available: {sorted(_SCENES)}"
            )
        self.objects, self.locations, self.robot = builder()
        self.scene_name = scene

    def load_scene(self, payload: dict[str, Any]) -> None:
        """Configure the world from a serialised scene description.

        ``payload`` may contain ``objects``, ``locations`` and ``robot`` keys. Any
        missing key keeps the current value, so callers can patch one object set
        at a time. Raises ``ValueError`` on malformed input.
        """

        try:
            if "locations" in payload:
                self.locations = {
                    loc["id"]: Location(
                        id=loc["id"],
                        name=loc.get("name", loc["id"]),
                        kind=LocationKind(loc.get("kind", "surface")),
                        anchor=Vec2(**loc["anchor"]),
                        width=loc.get("width", 0.30),
                        height=loc.get("height", 0.30),
                    )
                    for loc in payload["locations"]
                }
            if "objects" in payload:
                self.objects = {
                    obj["id"]: WorldObject(
                        id=obj["id"],
                        color=obj["color"],
                        shape=obj["shape"],
                        position=Vec2(**obj["position"]),
                        on_top_of=obj.get("on_top_of"),
                        inside=obj.get("inside"),
                        size=obj.get("size", 0.08),
                    )
                    for obj in payload["objects"]
                }
            if "robot" in payload:
                r = payload["robot"]
                self.robot = Robot(
                    pose=Vec2(**r["pose"]),
                    gripper_open=r.get("gripper_open", True),
                    holding=r.get("holding"),
                )
        except (KeyError, TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise ValueError(f"Malformed scene payload: {exc}") from exc

        self.scene_name = payload.get("scene_name", "custom")

    # -- queries -------------------------------------------------------------

    def get_object(self, object_id: str) -> WorldObject | None:
        return self.objects.get(object_id)

    def get_location(self, location_id: str) -> Location | None:
        return self.locations.get(location_id)

    def is_target_id(self, target_id: str) -> bool:
        """True if ``target_id`` names a known object or location."""

        return target_id in self.objects or target_id in self.locations

    def anchor_of(self, target_id: str) -> Vec2:
        """Return the 2D anchor of an object or location target."""

        if target_id in self.objects:
            return self.objects[target_id].position
        if target_id in self.locations:
            return self.locations[target_id].anchor
        raise KeyError(f"No object or location with id '{target_id}'")

    def objects_on(self, target_id: str) -> list[WorldObject]:
        """Objects currently resting on top of ``target_id``."""

        return [o for o in self.objects.values() if o.on_top_of == target_id]

    def is_clear(self, object_id: str) -> bool:
        """True if no object rests on top of ``object_id`` (graspable)."""

        return not self.objects_on(object_id)

    def find_objects(
        self, color: str | None = None, shape: str | None = None
    ) -> list[WorldObject]:
        """Return objects matching an optional color and/or shape filter."""

        result = []
        for obj in self.objects.values():
            if color is not None and obj.color.lower() != color.lower():
                continue
            if shape is not None and obj.shape.lower() != shape.lower():
                continue
            result.append(obj)
        return sorted(result, key=lambda o: o.id)

    # -- snapshots -----------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """A deep, JSON-serialisable snapshot of the full world state."""

        return {
            "scene_name": self.scene_name,
            "objects": [o.to_dict() for o in self.objects.values()],
            "locations": [loc.to_dict() for loc in self.locations.values()],
            "robot": self.robot.to_dict(),
        }

    def clone(self) -> WorldModel:
        """Return an independent copy (used by the planner to dry-run plans)."""

        twin = WorldModel.__new__(WorldModel)
        twin.objects = {k: replace(v) for k, v in self.objects.items()}
        twin.locations = {k: replace(v) for k, v in self.locations.items()}
        twin.robot = replace(self.robot)
        twin.scene_name = self.scene_name
        return twin

    def __deepcopy__(self, memo: dict[int, Any]) -> WorldModel:  # pragma: no cover
        return self.clone()


# ---------------------------------------------------------------------------
# Built-in scenes
# ---------------------------------------------------------------------------


def _make_locations() -> dict[str, Location]:
    return {
        "table": Location("table", "Table", LocationKind.SURFACE, Vec2(0.0, 0.0), 1.0, 0.7),
        "shelf": Location("shelf", "Shelf", LocationKind.SURFACE, Vec2(0.40, 0.30), 0.30, 0.18),
        "bin": Location("bin", "Bin", LocationKind.CONTAINER, Vec2(-0.40, 0.30), 0.22, 0.22),
        "left_zone": Location("left_zone", "Left zone", LocationKind.ZONE, Vec2(-0.30, -0.20), 0.25, 0.25),
        "right_zone": Location("right_zone", "Right zone", LocationKind.ZONE, Vec2(0.30, -0.20), 0.25, 0.25),
    }


def _scene_default() -> tuple[dict[str, WorldObject], dict[str, Location], Robot]:
    locations = _make_locations()
    objects = {
        "red_block": WorldObject("red_block", "red", "block", Vec2(-0.20, -0.10), on_top_of="table"),
        "blue_block": WorldObject("blue_block", "blue", "block", Vec2(0.0, -0.10), on_top_of="table"),
        "green_ball": WorldObject("green_ball", "green", "ball", Vec2(0.20, -0.10), on_top_of="table"),
        "yellow_cup": WorldObject("yellow_cup", "yellow", "cup", Vec2(0.0, 0.05), on_top_of="table"),
    }
    robot = Robot(pose=Vec2(0.0, -0.35), gripper_open=True, holding=None)
    return objects, locations, robot


def _scene_stack() -> tuple[dict[str, WorldObject], dict[str, Location], Robot]:
    """A stacking scene: red block already sits on top of the blue block."""

    locations = _make_locations()
    objects = {
        "blue_block": WorldObject("blue_block", "blue", "block", Vec2(0.0, -0.10), on_top_of="table"),
        "red_block": WorldObject("red_block", "red", "block", Vec2(0.0, -0.10), on_top_of="blue_block"),
        "green_block": WorldObject("green_block", "green", "block", Vec2(0.25, -0.10), on_top_of="table"),
        "yellow_cup": WorldObject("yellow_cup", "yellow", "cup", Vec2(-0.25, -0.05), on_top_of="table"),
    }
    robot = Robot(pose=Vec2(0.0, -0.35), gripper_open=True, holding=None)
    return objects, locations, robot


def _scene_sorting() -> tuple[dict[str, WorldObject], dict[str, Location], Robot]:
    """A sorting scene with several blocks/balls to move into zones and the bin."""

    locations = _make_locations()
    objects = {
        "red_block": WorldObject("red_block", "red", "block", Vec2(-0.25, -0.10), on_top_of="table"),
        "red_ball": WorldObject("red_ball", "red", "ball", Vec2(-0.10, -0.18), on_top_of="table"),
        "blue_block": WorldObject("blue_block", "blue", "block", Vec2(0.05, -0.10), on_top_of="table"),
        "green_block": WorldObject("green_block", "green", "block", Vec2(0.20, -0.16), on_top_of="table"),
        "green_ball": WorldObject("green_ball", "green", "ball", Vec2(0.30, -0.05), on_top_of="table"),
        "yellow_cup": WorldObject("yellow_cup", "yellow", "cup", Vec2(-0.05, 0.05), on_top_of="table"),
    }
    robot = Robot(pose=Vec2(0.0, -0.35), gripper_open=True, holding=None)
    return objects, locations, robot


def _scene_empty() -> tuple[dict[str, WorldObject], dict[str, Location], Robot]:
    return {}, _make_locations(), Robot(pose=Vec2(0.0, -0.35))


_SCENES: dict[str, Any] = {
    "default": _scene_default,
    "stack": _scene_stack,
    "sorting": _scene_sorting,
    "empty": _scene_empty,
}


def available_scenes() -> list[str]:
    """Names of the built-in scenes that :meth:`WorldModel.reset` accepts."""

    return sorted(_SCENES)
