# Documentation — LLM Robotic Task-Planning Agent

Project docs for the natural-language → validated primitive plan → tabletop
execution system. Start with the root [`../README.md`](../README.md) for a
high-level tour, then dive into the topics below.

## Index

| Document | What's inside |
| -------- | ------------- |
| [architecture.md](./architecture.md) | Components, the NL→plan→execution data flow, the simulation-vs-real design, the STRIPS-like world model, and the **benchmark methodology**. |
| [api.md](./api.md) | Full REST endpoint reference (`/api/v1`), request/response examples, the `/ws/execution` WebSocket protocol, and the primitive action catalog. |
| [observability.md](./observability.md) | Metrics catalog, Prometheus + Grafana usage, dashboard panels, alerts, and example PromQL. |
| [development.md](./development.md) | Local setup, project layout, running tests + lint, conventions, and how to add a primitive / benchmark command. |
| [deployment.md](./deployment.md) | Docker / Compose deployment, environment variables, Supabase setup, the monitoring stack, scaling notes, and enabling the real LLM backend. |
| [../infra/supabase/README.md](../infra/supabase/README.md) | Supabase project setup: keys, JWT secret, `schema.sql` (sessions/runs/plan_memory, RLS, pgvector), and the scaling model. |

## Quick links

- API docs (Swagger UI): http://localhost:8000/docs
- Metrics: http://localhost:8000/metrics
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3001
- Infra / monitoring stack: [`../infra/README.md`](../infra/README.md)

## At a glance

- **Backend** — FastAPI (`backend/app/`), pydantic v2, websockets. Always-enforced
  Supabase JWT auth (stdlib HS256), per-user/session isolation, and Supabase
  Postgres + pgvector persistence (import-guarded). A deterministic heuristic
  planner is always available; the real LLM planner is **Mistral** (default) or
  **Anthropic Claude**, used when a provider key is set.
- **Frontend** — Next.js 14 dashboard (`frontend/`) with a Supabase email/password
  login gate: instruction console, plan visualiser, animated top-down scene,
  execution timeline, benchmark dashboard.
- **Domain** — a STRIPS-like tabletop world with explicit primitive
  preconditions/effects, a dry-run plan validator, and a 20-command benchmark.
- **Observability** — Prometheus metrics at `/metrics` + a Grafana dashboard
  (see [observability.md](./observability.md)).
