"""Step-by-step plan executor.

Runs a validated :class:`~app.domain.planner.Plan` against a
:class:`~app.domain.world_model.WorldModel`, applying each primitive in turn and
emitting a per-step :class:`StepEvent` containing the action, its args, the
pre/post world snapshots, and success/failure information.

Execution is **fail-fast by default**: the first failing precondition stops the
run (a real robot wouldn't blindly continue), but the caller can opt into
``continue_on_error`` to collect every failure for debugging.

The executor exposes both a batch API (:meth:`execute`) and a generator
(:meth:`iter_execute`) so the WebSocket endpoint can stream events live.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from app.domain import primitives
from app.domain.planner import Plan
from app.domain.world_model import WorldModel


@dataclass
class StepEvent:
    """A single executed step with before/after world snapshots."""

    index: int
    action: str
    args: dict[str, Any]
    rationale: str
    success: bool
    reason: str
    pre_state: dict[str, Any]
    post_state: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "action": self.action,
            "args": self.args,
            "rationale": self.rationale,
            "success": self.success,
            "reason": self.reason,
            "pre_state": self.pre_state,
            "post_state": self.post_state,
        }


@dataclass
class ExecutionReport:
    """Aggregate result of executing a plan."""

    success: bool
    steps_total: int
    steps_executed: int
    steps_succeeded: int
    events: list[StepEvent] = field(default_factory=list)
    final_state: dict[str, Any] | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "steps_total": self.steps_total,
            "steps_executed": self.steps_executed,
            "steps_succeeded": self.steps_succeeded,
            "events": [e.to_dict() for e in self.events],
            "final_state": self.final_state,
            "message": self.message,
        }


class Executor:
    """Executes plans against a world model, emitting step events."""

    def iter_execute(
        self,
        plan: Plan,
        world: WorldModel,
        continue_on_error: bool = False,
    ) -> Iterator[StepEvent]:
        """Yield a :class:`StepEvent` for each executed step against ``world``.

        The ``world`` is mutated in place as the plan runs. Stops at the first
        failure unless ``continue_on_error`` is set.
        """

        for index, step in enumerate(plan.steps):
            pre_state = world.snapshot()
            result = primitives.apply(step.action, step.args, world)
            post_state = world.snapshot()

            event = StepEvent(
                index=index,
                action=step.action,
                args=step.args,
                rationale=step.rationale,
                success=result.ok,
                reason=result.reason or ("ok" if result.ok else "failed"),
                pre_state=pre_state,
                post_state=post_state,
            )
            yield event

            if not result.ok and not continue_on_error:
                return

    def execute(
        self,
        plan: Plan,
        world: WorldModel,
        continue_on_error: bool = False,
    ) -> ExecutionReport:
        """Execute ``plan`` fully and return an :class:`ExecutionReport`.

        ``world`` is mutated in place. Task success means every step in the plan
        was executed and succeeded.
        """

        events = list(self.iter_execute(plan, world, continue_on_error))
        executed = len(events)
        succeeded = sum(1 for e in events if e.success)
        success = executed == len(plan.steps) and succeeded == len(plan.steps)

        if not plan.steps:
            message = "plan was empty"
        elif success:
            message = "plan executed successfully"
        else:
            failed = next((e for e in events if not e.success), None)
            if failed is not None:
                message = f"failed at step {failed.index} ({failed.action}): {failed.reason}"
            else:
                message = "plan did not complete"

        return ExecutionReport(
            success=success,
            steps_total=len(plan.steps),
            steps_executed=executed,
            steps_succeeded=succeeded,
            events=events,
            final_state=world.snapshot(),
            message=message,
        )
