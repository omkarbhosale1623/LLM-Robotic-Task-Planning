# Deployment

## Docker Compose (full stack)
From the project root:
```bash
docker compose up --build
```
| Service | Port | URL |
|---------|------|-----|
| frontend | 3000 | http://localhost:3000 |
| backend | 8000 | http://localhost:8000/docs |
| prometheus | 9090 | http://localhost:9090 |
| grafana | 3001 | http://localhost:3001 |

App images are multi-stage and run as non-root; the backend has a `HEALTHCHECK`
against `/health`.

Tear down (including volumes):
```bash
docker compose down -v
```

Pass env via a root `.env` (gitignored) consumed by `docker-compose.yml`. Copy
`.env.example` and fill in real values; **never commit real secrets**.

## Environment variables

| Var | Default | Purpose |
|-----|---------|---------|
| `LOG_LEVEL` | `INFO` | log verbosity |
| `DEFAULT_SCENE` | `default` | scene loaded at startup |
| `CORS_ORIGINS` | localhost:3000 | allowed browser origins |
| `AUTH_REQUIRED` | `true` | enforce Supabase JWT on `/api/v1/**` + `/ws/**` |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` | — | Supabase project + keys |
| `SUPABASE_JWT_SECRET` | — | HS256 secret used to verify user JWTs |
| `DATABASE_URL` | — | `postgresql+asyncpg://…` Supabase Postgres DSN |
| `PERSISTENCE_BACKEND` | `auto` | `auto` \| `supabase` \| `memory` |
| `ENABLE_LLM` | `true` | enable the real LLM planner |
| `LLM_BACKEND` | `mistral` | `mistral` (default) or `anthropic` |
| `MISTRAL_API_KEY` / `MISTRAL_MODEL` | — / `mistral-large-latest` | Mistral backend |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | — / `claude-opus-4-8` | Anthropic backend |
| `ENABLE_PLAN_MEMORY` / `PLAN_MEMORY_TOP_K` / `EMBEDDING_DIM` | `true` / `3` / `384` | pgvector few-shot memory |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | frontend → backend |
| `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` | — | browser Supabase login client |

## Supabase setup
1. Create a Supabase project; collect the URL, anon/service-role keys, JWT secret,
   and Postgres DSN (see [`../infra/supabase/README.md`](../infra/supabase/README.md)).
2. Apply [`../infra/supabase/schema.sql`](../infra/supabase/schema.sql) (creates
   `sessions`/`runs`/`plan_memory`, enables pgvector + RLS).
3. Fill `DATABASE_URL`, `SUPABASE_*`, and `NEXT_PUBLIC_SUPABASE_*` in `.env`.

## Enabling the real LLM planner
1. The Mistral SDK ships in `requirements.txt`; set `LLM_BACKEND=mistral` and
   `MISTRAL_API_KEY` (or `LLM_BACKEND=anthropic` + `ANTHROPIC_API_KEY`).
2. Rebuild: `docker compose build backend`.

The LLM planner emits structured-JSON actions validated against the same
primitive catalog as the heuristic planner, with pgvector few-shot context; if
the LLM is unavailable or returns an invalid plan, the service falls back to the
heuristic planner with a truthful note.

## Scaling notes
- **Persistence is shared** via Supabase Postgres — any instance can read a user's
  sessions/runs/results. This scales horizontally behind a load balancer.
- **Live in-process session state is per-instance** (`SessionRegistry`). For a
  heavy live session, use sticky routing (route a `session_id` to the same
  instance) or run one instance per heavy session.
- `/health` and `/metrics` are public and ready for probes / Prometheus scraping.
- The backend connects with the service role (bypasses RLS) and additionally
  scopes every query by `user_id`; RLS is defence-in-depth for direct client access.
