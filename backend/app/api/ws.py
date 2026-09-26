"""WebSocket endpoint streaming live execution step events.

Authentication: the connection must present a valid Supabase JWT via the
``token`` query parameter (``/ws/execution?token=<jwt>``) — see
:func:`app.core.auth.authenticate_ws`. Unauthenticated sockets are closed with
code 1008. Each command runs against the caller's own per-session world via the
:class:`~app.services.session_registry.SessionRegistry`.

Protocol (JSON over a single connection at ``/ws/execution``):

* The client sends one command object::

      {"instruction": "pick up the red block", "mode": "llm",
       "session_id": "...", "reset_scene": "default", "continue_on_error": false}

  or, to execute a pre-built plan::

      {"plan": [{"action": "move_to", "args": {"target": "red_block"}}, ...]}

* The server replies with a stream of typed messages:

  - ``{"type": "plan", ...}``        — the resolved plan + validation
  - ``{"type": "world", ...}``       — the initial world snapshot
  - ``{"type": "step", ...}``        — one per executed primitive (pre/post state)
  - ``{"type": "result", ...}``      — the final execution report
  - ``{"type": "error", "message"}`` — on any failure
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import AppState
from app.core.auth import User, authenticate_ws
from app.core.logging import get_logger
from app.db.repository import RunRecord
from app.domain.planner import Plan, PlanStep
from app.domain.world_model import available_scenes
from app.services.session_registry import LiveSession

logger = get_logger(__name__)
router = APIRouter()


@router.websocket("/ws/execution")
async def execution_ws(websocket: WebSocket) -> None:
    state: AppState = websocket.app.state.app_state
    # Authenticate BEFORE accepting business traffic. authenticate_ws closes the
    # socket with 1008 on failure; we accept first so the close handshake works.
    await websocket.accept()
    user: User | None = await authenticate_ws(websocket, state.settings)
    if user is None:
        return
    try:
        while True:
            command = await websocket.receive_json()
            await _handle_command(websocket, state, user, command)
    except WebSocketDisconnect:
        logger.info("execution websocket disconnected")
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("execution websocket error")
        await _safe_send(websocket, {"type": "error", "message": str(exc)})


async def _handle_command(
    websocket: WebSocket, state: AppState, user: User, command: dict[str, Any]
) -> None:
    session_id = command.get("session_id")
    reset_scene = command.get("reset_scene")

    live: LiveSession = await state.registry.get_or_create(user, session_id, scene=reset_scene)

    async with live.lock:
        if reset_scene:
            if reset_scene not in available_scenes():
                await websocket.send_json(
                    {"type": "error", "message": f"unknown scene '{reset_scene}'"}
                )
                return
            live.world.reset(reset_scene)

        continue_on_error = bool(command.get("continue_on_error", False))

        # Resolve the plan: either an explicit plan or via the planning service.
        if command.get("plan"):
            try:
                plan = Plan(
                    instruction=command.get("instruction", ""),
                    steps=[PlanStep.from_dict(s) for s in command["plan"]],
                )
            except (ValueError, TypeError) as exc:
                await websocket.send_json({"type": "error", "message": f"bad plan: {exc}"})
                return
            notes: list[str] = []
            planner_used = "client"
            validation = None
        else:
            instruction = command.get("instruction", "")
            if not instruction:
                await websocket.send_json(
                    {"type": "error", "message": "provide an 'instruction' or a 'plan'"}
                )
                return
            mode = command.get("mode") or state.settings.default_planner_mode
            outcome = await live.planning.plan_with_memory(
                instruction, live.world, mode=mode, user_id=user.id
            )
            plan = outcome.plan
            notes = outcome.notes
            planner_used = outcome.planner_used
            validation = outcome.validation

            await websocket.send_json(
                {
                    "type": "plan",
                    "session_id": live.session_id,
                    "plan": plan.to_dict(),
                    "validation": validation.to_dict(),
                    "planner_used": planner_used,
                    "llm_available": outcome.llm_available,
                    "notes": notes,
                }
            )
            if not validation.valid:
                await websocket.send_json(
                    {
                        "type": "result",
                        "success": False,
                        "message": "plan failed validation; nothing executed",
                    }
                )
                return

        if validation is None:
            await websocket.send_json(
                {
                    "type": "plan",
                    "session_id": live.session_id,
                    "plan": plan.to_dict(),
                    "planner_used": planner_used,
                    "notes": notes,
                }
            )

        # Send the initial world snapshot, then stream step events.
        await websocket.send_json({"type": "world", "state": live.world.snapshot()})

        succeeded = 0
        executed = 0
        for event in live.executor.iter_execute(plan, live.world, continue_on_error):
            executed += 1
            succeeded += 1 if event.success else 0
            await websocket.send_json({"type": "step", **event.to_dict()})
            # A small delay makes the front-end animation legible without blocking.
            await asyncio.sleep(0.18)

        success = (
            executed == len(plan.steps)
            and succeeded == len(plan.steps)
            and bool(plan.steps)
        )
        final_state = live.world.snapshot()

    await state.repository.save_run(
        RunRecord(
            session_id=live.session_id,
            user_id=user.id,
            kind="ws-execute",
            params={"instruction": plan.instruction, "planner_used": planner_used},
            metrics={"success": success, "steps_executed": executed},
        )
    )

    await websocket.send_json(
        {
            "type": "result",
            "session_id": live.session_id,
            "success": success,
            "steps_total": len(plan.steps),
            "steps_executed": executed,
            "steps_succeeded": succeeded,
            "final_state": final_state,
            "message": "completed" if success else "stopped before completing",
        }
    )


async def _safe_send(websocket: WebSocket, payload: dict[str, Any]) -> None:
    with contextlib.suppress(Exception):  # pragma: no cover - connection may be closed
        await websocket.send_json(payload)
