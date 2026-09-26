"""Planning facade.

Combines the always-available :class:`~app.domain.planner.HeuristicPlanner` with
the optional :class:`~app.domain.llm_planner.LLMPlanner`, implementing graceful
degradation:

* ``mode="heuristic"`` — always uses the deterministic parser.
* ``mode="llm"`` — tries the LLM backend; if it is unavailable or returns an
  invalid plan, it silently falls back to the heuristic planner and records a
  truthful note explaining what happened.
* ``mode="auto"`` — prefer the LLM if available, otherwise heuristic.

When a repository + embedder are supplied, the service also:

* **retrieves** the top-k most-similar prior successful plans for the user and
  injects them as few-shot examples into the LLM prompt, and
* **stores** each new successful (instruction -> plan) pair to plan memory.

Plan memory is best-effort and non-blocking — any failure is logged and skipped,
so planning never breaks because the database or embedder is unavailable.

The returned :class:`PlanOutcome` carries the plan, its validation result, and
the planner that actually produced it, so the UI can show "LLM unavailable"
notes truthfully.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.core.logging import get_logger
from app.core.metrics import record_plan
from app.db.repository import PlanMemoryRecord, Repository
from app.domain.embeddings import Embedder
from app.domain.llm_planner import FewShotExample, LLMPlanner, LLMUnavailable
from app.domain.planner import (
    HeuristicPlanner,
    Plan,
    PlanningError,
    ValidationResult,
    validate_plan,
)
from app.domain.world_model import WorldModel

logger = get_logger(__name__)


@dataclass
class PlanOutcome:
    """Result of a planning request, including provenance and validation."""

    plan: Plan
    validation: ValidationResult
    planner_used: str  # heuristic | llm
    requested_mode: str
    llm_available: bool
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "validation": self.validation.to_dict(),
            "planner_used": self.planner_used,
            "requested_mode": self.requested_mode,
            "llm_available": self.llm_available,
            "notes": self.notes,
        }


class PlanningService:
    """Orchestrates planner selection, fallback, and plan memory."""

    def __init__(self, settings: Settings, repository: Repository | None = None) -> None:
        self.settings = settings
        self.repository = repository
        self.heuristic = HeuristicPlanner()
        self.llm = LLMPlanner(settings)
        self._embedder = Embedder(settings) if settings.enable_plan_memory else None

    def llm_available(self) -> bool:
        return self.settings.enable_llm and self.llm.is_available()

    def availability_note(self) -> str:
        return self.llm.availability_note()

    def default_mode(self) -> str:
        return self.settings.default_planner_mode

    def plan(self, instruction: str, world: WorldModel, mode: str = "heuristic") -> PlanOutcome:
        """Synchronous plan (no plan-memory I/O). Used by the benchmark + tests."""

        outcome = self._plan(instruction, world, mode, few_shots=[])
        record_plan(outcome.planner_used, len(outcome.plan.steps))
        return outcome

    async def plan_with_memory(
        self,
        instruction: str,
        world: WorldModel,
        mode: str,
        user_id: str,
    ) -> PlanOutcome:
        """Async plan that consults + updates per-user plan memory.

        Retrieves few-shot examples before planning (LLM modes only) and stores
        the resulting plan when it is valid and non-empty. Both steps degrade
        gracefully to a no-op on any error.
        """

        few_shots: list[FewShotExample] = []
        embedding: list[float] | None = None
        want_llm = (mode or "").lower() in ("llm", "auto") and self.llm_available()

        if self._memory_enabled() and want_llm:
            embedding = self._safe_embed(instruction)
            if embedding is not None:
                few_shots = await self._retrieve_few_shots(user_id, embedding)

        outcome = self._plan(instruction, world, mode, few_shots=few_shots)
        record_plan(outcome.planner_used, len(outcome.plan.steps))

        if self._memory_enabled() and outcome.validation.valid and outcome.plan.steps:
            if embedding is None:
                embedding = self._safe_embed(instruction)
            if embedding is not None:
                await self._store_memory(user_id, instruction, outcome.plan, embedding)
        return outcome

    # -- internals -----------------------------------------------------------

    def _plan(
        self,
        instruction: str,
        world: WorldModel,
        mode: str,
        few_shots: list[FewShotExample],
    ) -> PlanOutcome:
        mode = (mode or "heuristic").lower()
        notes: list[str] = []
        want_llm = mode in ("llm", "auto") and self.llm_available()

        if mode == "llm" and not self.llm_available():
            notes.append(self.availability_note())

        if want_llm:
            try:
                plan = self.llm.plan(instruction, world, few_shots=few_shots)
                validation = validate_plan(plan, world)
                if few_shots:
                    notes.append(f"Injected {len(few_shots)} similar prior plan(s) as context.")
                plan.notes.extend(notes)
                return PlanOutcome(
                    plan=plan,
                    validation=validation,
                    planner_used="llm",
                    requested_mode=mode,
                    llm_available=True,
                    notes=notes,
                )
            except LLMUnavailable as exc:
                logger.info("LLM planner fell back to heuristic: %s", exc)
                notes.append(f"LLM planner unavailable ({exc}); used heuristic planner.")

        # Heuristic path (default and fallback).
        try:
            plan = self.heuristic.plan(instruction, world)
        except PlanningError as exc:
            empty = Plan(instruction=instruction, planner="heuristic", notes=notes + [str(exc)])
            validation = ValidationResult(valid=False, errors=[str(exc)])
            return PlanOutcome(
                plan=empty,
                validation=validation,
                planner_used="heuristic",
                requested_mode=mode,
                llm_available=self.llm_available(),
                notes=notes + [str(exc)],
            )

        plan.notes.extend(notes)
        validation = validate_plan(plan, world)
        return PlanOutcome(
            plan=plan,
            validation=validation,
            planner_used="heuristic",
            requested_mode=mode,
            llm_available=self.llm_available(),
            notes=notes,
        )

    def _memory_enabled(self) -> bool:
        return bool(self.settings.enable_plan_memory and self.repository and self._embedder)

    def _safe_embed(self, text: str) -> list[float] | None:
        if self._embedder is None:
            return None
        try:
            return self._embedder.embed(text)
        except Exception as exc:  # pragma: no cover - embedder is defensive itself
            logger.warning("plan-memory embedding failed (%s); skipping memory", exc)
            return None

    async def _retrieve_few_shots(
        self, user_id: str, embedding: list[float]
    ) -> list[FewShotExample]:
        try:
            records = await self.repository.search_plan_memory(
                user_id, embedding, top_k=self.settings.plan_memory_top_k
            )
        except Exception as exc:  # pragma: no cover - DB/optional path
            logger.warning("plan-memory retrieval failed (%s); skipping", exc)
            return []
        return [
            FewShotExample(instruction=r.instruction, plan=r.plan)
            for r in records
            if r.plan.get("steps")
        ]

    async def _store_memory(
        self, user_id: str, instruction: str, plan: Plan, embedding: list[float]
    ) -> None:
        try:
            await self.repository.save_plan_memory(
                PlanMemoryRecord(
                    user_id=user_id,
                    instruction=instruction,
                    plan=plan.to_dict(),
                    embedding=embedding,
                )
            )
        except Exception as exc:  # pragma: no cover - DB/optional path
            logger.warning("plan-memory store failed (%s); skipping", exc)
