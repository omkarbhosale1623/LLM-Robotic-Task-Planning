"""Deterministic NL -> plan heuristic planner and plan validation.

This module provides:

* :class:`PlanStep` / :class:`Plan` — the validated plan representation.
* :class:`HeuristicPlanner` — a grammar/heuristic parser that turns a natural
  language instruction + a world snapshot into an ordered, precondition-aware
  plan of primitives. This is the *always-available* fallback that needs no LLM.
* :func:`validate_plan` — a STRIPS-style validator that dry-runs a plan against a
  cloned world and rejects ungrounded or illegal plans.

The heuristic parser performs four passes:

1. **Tokenise & segment** the instruction into clauses (split on "then", "and
   then", "after that", commas, ";").
2. **Extract** verbs, colors, shapes and relation/destination phrases per clause.
3. **Ground** noun phrases to concrete object/location ids in the world.
4. **Expand** each grounded clause into the precondition-correct primitive
   sequence (``move_to`` -> ``pick`` -> ``move_to`` -> ``place`` ...), inserting
   any unstacking steps needed to clear a target first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.domain import primitives
from app.domain.world_model import LocationKind, WorldModel

# ---------------------------------------------------------------------------
# Plan representation
# ---------------------------------------------------------------------------


@dataclass
class PlanStep:
    """A single primitive invocation inside a plan."""

    action: str
    args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "args": self.args, "rationale": self.rationale}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanStep:
        if "action" not in data:
            raise ValueError("plan step missing 'action'")
        args = data.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError("plan step 'args' must be an object")
        return cls(action=str(data["action"]), args=args, rationale=str(data.get("rationale", "")))


@dataclass
class Plan:
    """An ordered list of plan steps plus provenance metadata."""

    instruction: str
    steps: list[PlanStep] = field(default_factory=list)
    planner: str = "heuristic"  # heuristic | llm
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instruction": self.instruction,
            "planner": self.planner,
            "steps": [s.to_dict() for s in self.steps],
            "notes": self.notes,
        }


@dataclass
class ValidationResult:
    """Outcome of validating a plan against a world."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    grounded_targets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "grounded_targets": self.grounded_targets,
        }


class PlanningError(Exception):
    """Raised when an instruction cannot be parsed into a grounded plan."""


# ---------------------------------------------------------------------------
# Lexicon
# ---------------------------------------------------------------------------

COLORS = {"red", "blue", "green", "yellow", "orange", "purple", "black", "white"}
SHAPES = {
    "block": "block",
    "blocks": "block",
    "cube": "block",
    "cubes": "block",
    "ball": "ball",
    "balls": "ball",
    "sphere": "ball",
    "cup": "cup",
    "cups": "cup",
    "mug": "cup",
    "bowl": "bowl",
}

# Verb -> canonical intent.
PICK_VERBS = {"pick", "grab", "grasp", "take", "lift", "get", "fetch"}
PLACE_VERBS = {"place", "put", "drop", "set", "stack", "release", "deposit"}
MOVE_VERBS = {"move", "bring", "carry", "transfer", "relocate", "push", "send"}
DETECT_VERBS = {"detect", "find", "locate", "look", "scan", "see", "identify"}

# Phrases that introduce a destination.
DEST_PREPOSITIONS = ("onto", "on top of", "on", "into", "in", "to", "inside", "at", "over")

CLAUSE_SPLIT = re.compile(
    r"\bthen\b|\band then\b|\bafter that\b|\bnext\b|;|,",
    flags=re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Heuristic planner
# ---------------------------------------------------------------------------


PRONOUNS = {"it", "that", "this", "them", "those", "one"}


class HeuristicPlanner:
    """Grammar/heuristic NL -> plan parser. Pass the world per call.

    The only per-parse state is ``_last_subject`` (for pronoun resolution across
    clauses), reset at the start of every :meth:`plan` call.
    """

    def __init__(self) -> None:
        self._last_subject: str | None = None
        # Object the (simulated) gripper is already holding from a prior clause,
        # so a follow-up "place it ..." clause doesn't re-issue a pick.
        self._held: str | None = None

    def plan(self, instruction: str, world: WorldModel) -> Plan:
        """Parse ``instruction`` into a grounded :class:`Plan` for ``world``.

        Raises :class:`PlanningError` if no clause yields a grounded action.
        """

        text = instruction.strip()
        if not text:
            raise PlanningError("instruction is empty")

        plan = Plan(instruction=instruction, planner="heuristic")
        clauses = self._segment(text)
        produced_action = False
        # Reset per-parse clause-tracking state.
        self._last_subject = None
        self._held = None

        for clause in clauses:
            steps, notes = self._plan_clause(clause, world, plan)
            plan.steps.extend(steps)
            plan.notes.extend(notes)
            if any(s.action in ("pick", "place", "move_to", "detect") for s in steps):
                produced_action = True

        if not produced_action:
            raise PlanningError(
                f"could not ground any action in instruction: '{instruction}'"
            )
        return plan

    # -- pass 1: segmentation ------------------------------------------------

    def _segment(self, text: str) -> list[str]:
        parts = [p.strip() for p in CLAUSE_SPLIT.split(text) if p and p.strip()]
        return parts or [text]

    # -- pass 2/3: extraction + grounding per clause -------------------------

    def _plan_clause(
        self, clause: str, world: WorldModel, plan: Plan
    ) -> tuple[list[PlanStep], list[str]]:
        words = re.findall(r"[a-zA-Z_]+", clause.lower())
        if not words:
            return [], []

        verb = self._classify_verb(words)
        subject_phrase, dest_phrase = self._split_on_destination(clause)

        # Detection / perception clauses.
        if verb == "detect":
            target = self._ground_noun(subject_phrase or clause, world)
            if target is None:
                return [PlanStep("detect", {}, "scan the scene for objects")], [
                    f"'{clause.strip()}' -> scene scan (no specific object grounded)"
                ]
            return [PlanStep("detect", {"target": target}, f"perceive {target}")], []

        subject_id = self._ground_noun(subject_phrase, world)
        dest_id = self._ground_destination(dest_phrase, world)

        # Pronoun resolution: "place it on the shelf" -> reuse the last subject.
        if subject_id is None and self._mentions_pronoun(subject_phrase):
            subject_id = self._last_subject

        if subject_id is None:
            return [], [f"could not ground subject of clause: '{clause.strip()}'"]

        self._last_subject = subject_id

        # A bare "pick"/"grab" with no destination -> grasp and hold.
        if verb == "pick" and dest_id is None:
            steps = self._expand_pick(subject_id, world)
            self._held = subject_id
            return steps, []

        # move/place/stack with a destination -> full pick-and-place.
        if dest_id is None:
            # No destination found; treat as a pick if the verb implies grasping.
            if verb in ("place", "move"):
                return [], [
                    f"clause '{clause.strip()}' has no destination to {verb} to"
                ]
            steps = self._expand_pick(subject_id, world)
            self._held = subject_id
            return steps, []

        # If a prior clause already grasped this object, only carry + place it.
        if self._held == subject_id:
            steps = self._expand_place_held(subject_id, dest_id, world)
            self._held = None
            return steps, []

        steps = self._expand_pick_and_place(subject_id, dest_id, world)
        self._held = None
        return steps, []

    def _classify_verb(self, words: list[str]) -> str:
        for w in words:
            if w in PICK_VERBS:
                return "pick"
            if w in PLACE_VERBS:
                return "place"
            if w in MOVE_VERBS:
                return "move"
            if w in DETECT_VERBS:
                return "detect"
        # Default: if a destination phrase exists the caller treats it as move.
        return "move"

    def _split_on_destination(self, clause: str) -> tuple[str, str | None]:
        """Split a clause into (subject phrase, destination phrase)."""

        lowered = clause.lower()
        best_idx = -1
        best_prep = ""
        for prep in DEST_PREPOSITIONS:
            # Match the preposition as a whole word/phrase.
            for m in re.finditer(rf"\b{re.escape(prep)}\b", lowered):
                idx = m.start()
                # Prefer the *last* preposition so "pick up X" doesn't split on "up".
                if idx > best_idx:
                    best_idx = idx
                    best_prep = prep
        if best_idx == -1:
            return clause, None
        subject = clause[:best_idx]
        dest = clause[best_idx + len(best_prep):]
        return subject.strip(), dest.strip()

    def _mentions_pronoun(self, phrase: str | None) -> bool:
        if not phrase:
            return False
        return any(w in PRONOUNS for w in re.findall(r"[a-zA-Z_]+", phrase.lower()))

    def _ground_noun(self, phrase: str | None, world: WorldModel) -> str | None:
        """Ground a noun phrase to a concrete object id (preferred) or location id."""

        if not phrase:
            return None
        words = re.findall(r"[a-zA-Z_]+", phrase.lower())

        # Direct id reference (e.g. "red_block").
        for token in re.findall(r"[a-zA-Z_]+", phrase.lower()):
            if token in world.objects:
                return token

        color = next((w for w in words if w in COLORS), None)
        shape = next((SHAPES[w] for w in words if w in SHAPES), None)

        if color or shape:
            matches = world.find_objects(color=color, shape=shape)
            if len(matches) == 1:
                return matches[0].id
            if len(matches) > 1:
                # Ambiguous: pick the first deterministically but record nothing here.
                return matches[0].id

        # Fall back to a location reference.
        return self._ground_location(phrase, world)

    def _ground_destination(self, phrase: str | None, world: WorldModel) -> str | None:
        if not phrase:
            return None
        # Destinations are usually locations, but "on the blue block" is valid too.
        loc = self._ground_location(phrase, world)
        if loc is not None:
            return loc
        return self._ground_noun(phrase, world)

    def _ground_location(self, phrase: str, world: WorldModel) -> str | None:
        words = re.findall(r"[a-zA-Z_]+", phrase.lower())

        # 1. Direct id reference (e.g. "right_zone").
        for token in words:
            if token in world.locations:
                return token

        # 2. Disambiguating keywords/synonyms first — these resolve "left zone"
        #    vs "right zone" before the generic "zone" name match below.
        synonyms = {
            "shelf": "shelf",
            "bin": "bin",
            "trash": "bin",
            "table": "table",
            "left": "left_zone",
            "right": "right_zone",
        }
        for token in words:
            if token in synonyms and synonyms[token] in world.locations:
                return synonyms[token]

        # 3. Fall back to a unique display-name keyword match. Skip generic tokens
        #    ("zone") shared by several locations to avoid grounding the wrong one.
        generic = {"zone", "the", "a", "an"}
        for loc in world.locations.values():
            name_tokens = set(re.findall(r"[a-zA-Z_]+", loc.name.lower())) - generic
            if name_tokens and name_tokens & set(words):
                return loc.id
        return None

    # -- pass 4: precondition-aware expansion --------------------------------

    def _expand_pick(self, object_id: str, world: WorldModel) -> list[PlanStep]:
        steps: list[PlanStep] = []
        steps.extend(self._clear_above(object_id, world))
        steps.append(PlanStep("move_to", {"target": object_id}, f"approach {object_id}"))
        steps.append(PlanStep("pick", {"target": object_id}, f"grasp {object_id}"))
        return steps

    def _expand_pick_and_place(
        self, object_id: str, dest_id: str, world: WorldModel
    ) -> list[PlanStep]:
        steps: list[PlanStep] = []
        steps.extend(self._clear_above(object_id, world))
        # If the destination is an object, ensure it is clear too.
        if dest_id in world.objects:
            steps.extend(self._clear_above(dest_id, world))

        steps.append(PlanStep("move_to", {"target": object_id}, f"approach {object_id}"))
        steps.append(PlanStep("pick", {"target": object_id}, f"grasp {object_id}"))
        steps.append(PlanStep("move_to", {"target": dest_id}, f"carry {object_id} to {dest_id}"))

        loc = world.get_location(dest_id)
        verb = "into" if (loc and loc.kind == LocationKind.CONTAINER) else "onto"
        steps.append(
            PlanStep("place", {"target": dest_id}, f"release {object_id} {verb} {dest_id}")
        )
        return steps

    def _expand_place_held(
        self, object_id: str, dest_id: str, world: WorldModel
    ) -> list[PlanStep]:
        """Carry an already-grasped object to ``dest_id`` and place it."""

        steps: list[PlanStep] = []
        if dest_id in world.objects:
            steps.extend(self._clear_above(dest_id, world))
        steps.append(PlanStep("move_to", {"target": dest_id}, f"carry {object_id} to {dest_id}"))
        loc = world.get_location(dest_id)
        verb = "into" if (loc and loc.kind == LocationKind.CONTAINER) else "onto"
        steps.append(
            PlanStep("place", {"target": dest_id}, f"release {object_id} {verb} {dest_id}")
        )
        return steps

    def _clear_above(self, target_id: str, world: WorldModel) -> list[PlanStep]:
        """Insert steps to remove any objects stacked on ``target_id``."""

        steps: list[PlanStep] = []
        on_top = world.objects_on(target_id)
        for blocker in on_top:
            steps.append(
                PlanStep("move_to", {"target": blocker.id}, f"reach blocker {blocker.id}")
            )
            steps.append(PlanStep("pick", {"target": blocker.id}, f"unstack {blocker.id}"))
            steps.append(PlanStep("move_to", {"target": "table"}, "move to table"))
            steps.append(
                PlanStep("place", {"target": "table"}, f"set {blocker.id} aside on table")
            )
        return steps


# ---------------------------------------------------------------------------
# Plan validation
# ---------------------------------------------------------------------------


def validate_plan(plan: Plan, world: WorldModel) -> ValidationResult:
    """Dry-run ``plan`` against a clone of ``world`` and collect errors.

    A plan is valid iff every step references a known primitive, every target is
    grounded to a known object/location, and every precondition holds in
    sequence. The original world is never mutated.
    """

    sandbox = world.clone()
    errors: list[str] = []
    grounded: list[str] = []

    if not plan.steps:
        errors.append("plan has no steps")
        return ValidationResult(False, errors, grounded)

    for i, step in enumerate(plan.steps):
        spec = primitives.PRIMITIVES.get(step.action)
        if spec is None:
            errors.append(f"step {i}: unknown primitive '{step.action}'")
            continue

        # Argument-name grounding check (reject ungrounded targets early).
        target = step.args.get("target")
        if "target" in spec.args and target is not None:
            if not sandbox.is_target_id(str(target)):
                errors.append(
                    f"step {i} ({step.action}): ungrounded target '{target}'"
                )
                continue
            grounded.append(str(target))

        result = primitives.apply(step.action, step.args, sandbox)
        if not result.ok:
            errors.append(f"step {i} ({step.action}): {result.reason}")

    return ValidationResult(valid=not errors, errors=errors, grounded_targets=grounded)
