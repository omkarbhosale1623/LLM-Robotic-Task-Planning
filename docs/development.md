# Development

## Prerequisites
- Python 3.11+
- Node.js 20+

## Backend
```bash
cd backend
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000       # http://localhost:8000/docs
```

### Tests & lint
```bash
python -m pytest -q          # 50 tests; no LLM key / db / torch required (all guarded)
ruff check app tests
```
Tests mint their own HS256 JWT (`tests/conftest.py:make_token`) with a known test
secret, so auth is enforced and the suite is green offline and keyless.

### Auth in local dev
Auth is always enforced. Either point `SUPABASE_*` at a real project and log in
through the frontend gate, or set `AUTH_REQUIRED=false` for quick local
exploration (any request is then treated as an anonymous user). Mint a token for
manual API testing the same way the tests do, or via the Supabase Auth REST API.

### Enable a real LLM planner
```bash
# Mistral (default backend) — SDK ships in requirements.txt
export ENABLE_LLM=true LLM_BACKEND=mistral MISTRAL_API_KEY=...   # mistral-large-latest
# or Anthropic
export ENABLE_LLM=true LLM_BACKEND=anthropic ANTHROPIC_API_KEY=sk-ant-...  # claude-opus-4-8
```
The default planner mode is `llm` when a provider key is present, else
`heuristic`; with no key the heuristic planner is always used and `/capabilities`
reports `llm_available=false` with a note.

## Frontend
```bash
cd frontend
npm install
cp .env.local.example .env.local   # set NEXT_PUBLIC_API_BASE_URL + NEXT_PUBLIC_SUPABASE_*
npm run dev                  # http://localhost:3000 (Supabase email/password login gate)
npm run lint
```

## Project layout
```
02-llm-robotic-task-planning/
├── backend/        FastAPI app (domain, services, db/ repo, core/auth), tests
├── frontend/       Next.js 14 dashboard + Supabase login gate (AuthProvider, LoginGate)
├── infra/supabase/ schema.sql (RLS, pgvector) + setup README
├── infra/          Prometheus + Grafana stack
├── docs/           this documentation
├── docker-compose.yml · Makefile · README.md · .env.example
```

## Extending

- **Add a primitive** — define it in `domain/primitives.py` (name, args,
  preconditions, effects); the planner/validator/executor pick it up via the
  catalog. Add a parser rule in `domain/planner.py` if it should be reachable
  from natural language.
- **Add a benchmark command** — append an instruction + outcome predicate in
  `services/benchmark.py`.

## Conventions
- Domain logic is framework-free and unit-tested.
- `PlanningService` is the single entry point that chooses heuristic ⇄ LLM and
  handles per-user plan memory (`plan_with_memory`).
- All optional deps (`mistralai`, `anthropic`, `sqlalchemy`/`asyncpg`,
  `sentence-transformers`/`torch`) are import-guarded — the app boots and tests
  pass without them.
- Auth is verified with the standard library; nothing on the boot/test path
  requires `pyjwt`, a database, or a provider key.
