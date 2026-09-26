# Architecture

## Overview

A user signs in (Supabase) and gives a natural-language instruction (e.g. *"pick
up the red block and put it on the shelf"*). The system decomposes it into an
ordered, **validated** sequence of robot primitives and executes them
step-by-step against a simulated tabletop world, streaming each step to the UI. A
deterministic heuristic planner is always available; a real LLM-backed planner —
**Mistral by default**, Anthropic Claude as an alternative — is used when a
provider key is set. Every `/api/v1/**` route and `/ws/**` requires a Supabase
JWT; each user gets their own world + executor per session; sessions/runs/plan
memory persist to Supabase Postgres when configured. No GPU, database, or API key
is required to boot or test.

```
┌──────────────────────────────┐   REST + WS (Bearer JWT)   ┌───────────────────────────────┐
│ Next.js 14 dashboard          │ ◀────────────────────────▶ │ FastAPI backend                │
│  • Supabase login gate        │  /api/v1/...  /ws/execution │  • require_user (Supabase JWT) │
│  • instruction console        │  ?token=<jwt>               │  • SessionRegistry (per user)  │
│  • plan visualiser (mini-DAG) │                             │  • PlanningService + plan mem  │
│  • tabletop SVG scene         │                             │  • heuristic + Mistral/Claude  │
│  • execution timeline         │                             │  • STRIPS world + Executor     │
│  • benchmark dashboard        │                             │  • Repository (memory / SQL)   │
└──────────────────────────────┘                             │  • Prometheus /metrics (public)│
        │ Supabase JS                                         └───────────────────────────────┘
        ▼                                                                  │ SQLAlchemy async
   Supabase Auth ◀───────────────── issues user JWT ─────────────────────▶ Supabase Postgres + pgvector
```

## Backend components

| Module | Responsibility |
|--------|----------------|
| `domain/world_model.py` | STRIPS-like tabletop: objects (color/shape/position/on-top-of/inside), locations (surfaces/containers/zones), robot + gripper. Built-in scenes; reset/configure. |
| `domain/primitives.py` | The 7 primitives (`move_to`, `pick`, `place`, `open_gripper`, `close_gripper`, `detect`, `wait`) with explicit preconditions/effects. |
| `domain/planner.py` | Deterministic NL→plan parser (clause segmentation → verb/color/shape extraction → grounding to ids → precondition-aware expansion) + a STRIPS dry-run validator. Always available. |
| `domain/llm_planner.py` | Real LLM planner. **Mistral** (`mistral-large-latest`, `response_format=json_object`) by default via the `mistralai` SDK or an `httpx` REST fallback; **Anthropic** Claude (`claude-opus-4-8`, adaptive thinking + JSON-schema) as an alternative. Output validated against the primitive schema; few-shot examples injected from plan memory. Imports guarded. |
| `domain/embeddings.py` | Embeds instructions for plan-memory retrieval — sentence-transformers when available, else a deterministic stdlib hashing embedder. |
| `services/planning_service.py` | Facade choosing heuristic ⇄ LLM with graceful fallback + a note; retrieves/stores per-user plan memory (`plan_with_memory`). |
| `services/session_registry.py` | Per-`(user, session)` live `WorldModel` + `Executor`, with per-session lock + idle eviction. Replaces the old global singleton. |
| `services/executor.py` | Executes a plan step-by-step, emitting per-step events with pre/post world snapshots and success/failure. |
| `services/benchmark.py` | The fixed 20-command suite with outcome predicates; reports per-command + overall task-completion rate. |
| `core/auth.py` | Stdlib Supabase HS256 JWT verification (`hmac`/`hashlib`), `require_user`, `authenticate_ws`. RS256/JWKS extension point marked. |
| `db/` | `Repository` (abstract) + `MemoryRepository` (default) + import-guarded `SqlRepository` (SQLAlchemy async + asyncpg + pgvector). `get_repository(settings)` factory. |
| `core/metrics.py` | Domain Prometheus metrics (`plan_requests_total`, `plan_actions`, `benchmark_success_rate`). |
| `api/routes/*` | `world`, `planning`, `benchmark`, `capabilities`, `sessions` (sessions + runs history). All under the auth'd `/api/v1` router. |
| `api/ws.py` | WebSocket `/ws/execution` (auth via `?token=`) streaming plan → world → step → result. |

## NL → plan → execution flow

1. **Plan** — `PlanningService.plan(instruction, world, mode)` produces a `Plan`
   of primitives. The heuristic parser grounds entities/relations to concrete
   object/location ids and orders steps to satisfy preconditions (auto-unstacking,
   gripper open/close, cross-clause pronoun resolution).
2. **Validate** — a STRIPS dry-run checks each step's preconditions against a copy
   of the world; ungrounded or illegal plans are rejected with reasons.
3. **Execute** — `Executor.execute(plan, world)` applies effects step-by-step,
   emitting events (action, args, pre/post snapshot, success) and a final result.
4. **Benchmark** — `BenchmarkRunner.run(mode)` plans + executes the 20-command
   suite and aggregates task-completion rate.

## Benchmark methodology

A fixed suite of 20 natural-language commands, each paired with an **outcome
predicate** over the final world state (e.g. "red block is on the shelf"). For
each command the runner plans, validates, executes, then evaluates the predicate.
The reported **task-completion rate** is the fraction of commands whose predicate
holds after execution. The heuristic planner scores 20/20 on the bundled suite;
the LLM planner can be benchmarked the same way when enabled.

## Auth, sessions & persistence

- **Auth (always enforced)** — `core/auth.py` verifies Supabase HS256 JWTs using
  only the standard library; `require_user` gates every `/api/v1/**` route and
  `authenticate_ws` gates `/ws/**` (token via `?token=`). `/health` + `/metrics`
  are public. For asymmetric Supabase keys, swap the marked extension point to a
  JWKS/RS256 verify.
- **Session isolation** — `SessionRegistry` holds a live world + executor per
  `(user_id, session_id)`; a per-session lock serialises concurrent requests for
  the same session, while different sessions run independently. A user can only
  address their own sessions.
- **Persistence** — sessions, runs (plan/execute/benchmark, incl. success rate)
  and plan memory persist via the `Repository`. `MemoryRepository` is the offline
  default; `SqlRepository` (Supabase Postgres + pgvector) is used when
  `DATABASE_URL` + libs are present. RLS in `infra/supabase/schema.sql` enforces
  per-user isolation at the DB.
- **Plan memory** — each successful (instruction→plan) pair is embedded and stored
  in `plan_memory(... embedding vector(384) ...)`; the top-k most-similar prior
  plans are injected as few-shot context into the LLM prompt.

## Simulated vs. real

| Concern | Default (always works) | Real integration |
|---------|------------------------|------------------|
| Planner | deterministic heuristic | LLM: **Mistral** (default) or Anthropic Claude, used when a key is set |
| Auth | stdlib HS256 JWT verify | Supabase Auth issues the tokens; RS256/JWKS extension point provided |
| Persistence | in-memory repo | Supabase Postgres + pgvector (import-guarded) |
| Robot/world | STRIPS tabletop simulation | swap `Executor` targets for a real arm / ROS2 |
| Compute | CPU only | optional API calls / local embedder model |

Optional integrations are import-guarded; the app boots and all tests pass with
no key, no database, and no torch/transformers/mistralai/anthropic.

## Scaling model

Persistence (sessions/runs/results) is shared via Postgres, so any backend
instance can read a user's history. **Live in-process session objects are
per-instance** — for a heavy live session use sticky routing (route a session_id
to the same instance) or run one instance per heavy session. See
`infra/supabase/README.md`.
