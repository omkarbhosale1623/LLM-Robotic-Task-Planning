# Backend — LLM Robotic Task-Planning Agent

FastAPI service that turns a natural-language instruction into a validated
sequence of robot primitives and executes it step-by-step against a simulated
tabletop world. A deterministic heuristic planner always works; a real LLM-backed
planner — **Mistral by default**, Anthropic Claude as an alternative — is used
when a provider key is set. Every `/api/v1/**` route and `/ws/**` requires a
**Supabase JWT** (verified with the Python standard library — no `pyjwt`);
`/health` + `/metrics` stay public. Each user gets their **own world + executor
per session**, and sessions/runs/plan-memory persist to **Supabase Postgres**
when configured. No GPU, database, or API key is required to boot or test.

## Run
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # fill in SUPABASE_* / DATABASE_URL / MISTRAL_API_KEY
uvicorn app.main:app --reload --port 8000   # docs at /docs

# Real LLM (Mistral default):
#   ENABLE_LLM=true LLM_BACKEND=mistral MISTRAL_API_KEY=...  (model: mistral-large-latest)
# Or Anthropic:
#   ENABLE_LLM=true LLM_BACKEND=anthropic ANTHROPIC_API_KEY=sk-ant-...  (claude-opus-4-8)
# Persistence: set DATABASE_URL to a Supabase Postgres DSN (postgresql+asyncpg://…);
#   apply ../infra/supabase/schema.sql first. Otherwise an in-memory repo is used.
```

## Auth, sessions & persistence
- **Auth** — `app/core/auth.py` verifies Supabase HS256 JWTs with `hmac`/`hashlib`
  (constant-time compare, `exp`/`aud`/`iss` checks). The `require_user` dependency
  is applied at the `/api/v1` router level; the WS reads the token from `?token=`.
  Set `AUTH_REQUIRED=false` only for local exploration without Supabase.
- **Sessions** — `app/services/session_registry.py` keys a live `WorldModel` +
  `Executor` by `(user_id, session_id)`, with a per-session lock and idle eviction.
  A user can only touch their own sessions.
- **Persistence** — `app/db/`: an abstract `Repository`, an in-memory default, and
  an import-guarded SQLAlchemy(async)+asyncpg `SqlRepository` (loaded only when
  `DATABASE_URL` is set and the libs import). `PERSISTENCE_BACKEND=auto|supabase|memory`.
- **Plan memory** — successful (instruction→plan) pairs are embedded
  (`app/domain/embeddings.py`: sentence-transformers when available, else a stdlib
  hashing embedder) and stored in pgvector; the top-k similar prior plans are
  injected as few-shot context into the LLM prompt.

## Test & lint
```bash
python -m pytest -q          # 50 tests; no LLM key / db / torch needed (guarded)
ruff check app tests
```
Tests mint their own HS256 JWT with a known test secret (`tests/conftest.py:make_token`),
so auth is enforced and the suite is green offline and keyless.

## Layout
```
app/
  main.py              app factory, routers (auth at router level), /metrics, lifespan
  config.py            pydantic-settings (auth / persistence / Mistral+Anthropic / memory)
  api/deps.py          AppState (repo + registry), make_require_user, get_current_user
  api/routes/          world.py, planning.py, benchmark.py, capabilities.py, sessions.py
  api/ws.py            WebSocket /ws/execution (authenticated via ?token=)
  core/                logging, errors, auth (stdlib JWT), metrics
  db/                  repository (abstract), memory_repo, sql_repo (guarded), records
  domain/              world_model, primitives, planner (heuristic), llm_planner, embeddings
  services/            executor, benchmark, planning_service, session_registry
  schemas/             pydantic request/response models
tests/                 auth, domain, services, api, ws, metrics, brain (real-brain pieces)
```

## Key endpoints
`GET /health` · `GET /metrics` (public) · `GET /api/v1/world` · `POST /api/v1/plan`
· `POST /api/v1/execute` · `POST /api/v1/plan-and-run` · `GET|POST /api/v1/benchmark`
· `GET /api/v1/capabilities` · `POST|GET /api/v1/sessions` · `GET /api/v1/sessions/{id}/runs`
· `GET /api/v1/runs` · `WS /ws/execution?token=<jwt>` (all `/api/v1` + WS require a Bearer JWT).

See [`../docs/api.md`](../docs/api.md) for the full reference and the benchmark
methodology, and [`../infra/supabase/README.md`](../infra/supabase/README.md) for
Supabase setup (keys, `schema.sql`, RLS, pgvector, scaling).
