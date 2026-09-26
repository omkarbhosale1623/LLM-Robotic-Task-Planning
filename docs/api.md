# API Reference

Base URL: `http://localhost:8000` · Versioned prefix: `/api/v1` · Interactive docs: `/docs`

## Authentication

Every `/api/v1/**` route and the `/ws/**` WebSocket require a **Supabase JWT**:

- REST: `Authorization: Bearer <access_token>`
- WebSocket: `/ws/execution?token=<access_token>`

Public (no auth): `/health`, `/metrics`, `/`, `/docs`, `/openapi.json`, `/redoc`.
A missing/invalid token returns `401` with
`{"error": {"type": "authentication_error", ...}}`. The token is verified with
stdlib HS256 against `SUPABASE_JWT_SECRET` (`sub` → user id). Requests
accept/return a `session_id`; omit it to create a new per-user session.

## Meta
| Method | Path | Auth | Returns |
|--------|------|------|---------|
| GET | `/health` | — | service status + LLM availability note |
| GET | `/metrics` | — | Prometheus exposition (HTTP + planner domain metrics) |

## World (`/api/v1`)
| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/world` | — | current world snapshot |
| POST | `/world/reset` | `SceneConfigRequest` | reset to a built-in scene or load a custom scene |
| GET | `/world/scenes` | — | list of built-in scene names |

## Planning (`/api/v1`)
| Method | Path | Body | Returns |
|--------|------|------|---------|
| POST | `/plan` | `PlanRequest` | validated plan + validation report + planner used |
| POST | `/execute` | `ExecuteRequest` | step-by-step execution report |
| POST | `/plan-and-run` | `PlanAndRunRequest` | plan + (if valid) execution in one call |

### `PlanRequest`
```json
{
  "instruction": "pick up the red block and place it on the shelf",
  "mode": null,                   // heuristic | llm | auto; null → default (llm if a key is set, else heuristic)
  "session_id": null,             // null → create a new per-user session
  "use_current_world": true,
  "scene": null
}
```
`use_current_world=false` (optionally with `scene`) plans against a fresh scene
without mutating the session world. Responses include the `session_id` used.

## Sessions & runs (`/api/v1`)
| Method | Path | Returns |
|--------|------|---------|
| POST | `/sessions` | create a new per-user session |
| GET | `/sessions` | list the caller's sessions |
| GET | `/sessions/{id}/runs` | runs (plan/execute/benchmark) for one session |
| GET | `/runs` | the caller's recent runs across sessions |

Each plan/execute/benchmark call records a `run` (with result metrics, incl.
benchmark success rate). Sessions/runs persist to Supabase Postgres when
configured, else to an in-memory store.

## Benchmark (`/api/v1`)
| Method | Path | Body / Query | Returns |
|--------|------|--------------|---------|
| GET | `/benchmark` | `?mode=heuristic\|llm\|auto` | task-completion rate + per-command breakdown |
| POST | `/benchmark` | `BenchmarkRequest` | same |

## Capabilities (`/api/v1`)
| Method | Path | Returns |
|--------|------|---------|
| GET | `/capabilities` | primitives, scenes, benchmark commands, planner modes, `default_mode`, `llm_available`, `llm_backend` + note |

The **primitive catalog**: `move_to`, `pick`, `place`, `open_gripper`,
`close_gripper`, `detect`, `wait` — each with preconditions/effects.

### Example — plan and run (authenticated)
```bash
curl -X POST localhost:8000/api/v1/plan-and-run \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" \
  -d '{"instruction":"put the red block on the shelf","mode":"heuristic"}'
```
Returns the `session_id`, the ordered plan, the validation result, the planner
used (`heuristic`/`llm`), `llm_available`, notes, and the execution report.

## WebSocket `/ws/execution`

Connect with the token in the query string and send a command:
`/ws/execution?token=<jwt>` → `{ "instruction": "...", "mode": "llm", "session_id": "..." }`.
The server streams frames:

| `type` | Payload |
|--------|---------|
| `plan` | the decomposed plan + validation |
| `world` | initial world snapshot |
| `step` | each executed action: args, pre/post world snapshot, success |
| `result` | final success + summary |

## Error envelope
Consistent JSON via the centralized handler, e.g. an unknown scene →
`{ "detail": "Unknown scene 'x'.", ... }` with the list of available scenes.
