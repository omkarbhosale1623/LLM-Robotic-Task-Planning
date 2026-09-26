# Observability stack (`infra/`)

Prometheus + Grafana monitoring for the **LLM Robotic Task-Planning Agent**. The
FastAPI backend is instrumented with
[`prometheus-fastapi-instrumentator`](https://github.com/trallnag/prometheus-fastapi-instrumentator)
and exposes metrics at `/metrics`; Prometheus scrapes them and Grafana renders a
pre-provisioned dashboard.

> Ports: **backend 8000**, **frontend 3000**, **Prometheus 9090**, **Grafana 3001**.

```
infra/
├── docker-compose.monitoring.yml     # standalone Prometheus + Grafana (monitor a running backend)
├── prometheus/
│   ├── prometheus.yml                # scrape config: backend:8000/metrics + self
│   └── alerts.yml                    # alert rules: backend down, high 5xx, high p95, low benchmark rate
└── grafana/
    ├── provisioning/
    │   ├── datasources/datasource.yml  # Prometheus datasource (uid PROMETHEUS, default)
    │   └── dashboards/dashboards.yml   # dashboard provider -> /var/lib/grafana/dashboards
    └── dashboards/
        └── llm-planner-overview.json   # the dashboard (9 panels)
```

## Two ways to run

### 1. All-in-one (recommended) — root compose

The root [`../docker-compose.yml`](../docker-compose.yml) already includes
`prometheus` and `grafana` alongside `backend` and `frontend`, mounting the
configs from this directory:

```bash
# from the project root
docker compose up --build
```

| Service    | URL                              |
| ---------- | -------------------------------- |
| Frontend   | http://localhost:3000            |
| Backend    | http://localhost:8000 (docs `/docs`) |
| Metrics    | http://localhost:8000/metrics    |
| Prometheus | http://localhost:9090            |
| Grafana    | http://localhost:3001            |

### 2. Standalone — monitor an already-running backend

Use `docker-compose.monitoring.yml` to attach Prometheus + Grafana to a backend
that is already up (it joins the same `planner-net` network the app stack
creates):

```bash
# from the project root: start the app first, then monitoring
docker compose up -d backend frontend
docker compose -f infra/docker-compose.monitoring.yml up -d
```

If your app stack's network is named differently, adjust the `external` network
name at the bottom of `docker-compose.monitoring.yml` (check with
`docker network ls`).

## Grafana

- Image `grafana/grafana:11.4.0`, published on `3001:3000`.
- **Anonymous viewer access** is enabled for the demo (`GF_AUTH_ANONYMOUS_ENABLED=true`),
  so the dashboard opens with no login. The admin account password is `admin`
  (`GF_SECURITY_ADMIN_PASSWORD=admin`) if you want to edit.
- The Prometheus datasource and the **LLM Planner — Overview** dashboard are
  auto-provisioned on startup — no manual import needed. Find it under
  Dashboards → "LLM Planner" folder.

## Prometheus

- Image `prom/prometheus:v3.1.0`, published on `9090:9090`.
- `prometheus.yml`: global 15s scrape interval; jobs `backend` (`backend:8000`,
  path `/metrics`) and `prometheus` (self).
- `alerts.yml` is loaded via `rule_files`; see active alerts at
  http://localhost:9090/alerts. Rules: `BackendDown`, `HighErrorRate`,
  `HighRequestLatencyP95`, `LowBenchmarkSuccessRate`.

## Metrics catalog

| Metric | Type | Labels | Source |
| ------ | ---- | ------ | ------ |
| `http_requests_total` | counter | `handler`, `method`, `status` | instrumentator (default) |
| `http_request_duration_seconds` | histogram | `handler`, `method` | instrumentator (default) |
| `plan_requests_total` | counter | `mode` (`heuristic`/`llm`/`client`) | `PlanningService.plan` |
| `plan_actions` | histogram | — | `PlanningService.plan` (plan length) |
| `benchmark_success_rate` | gauge | `mode` | `BenchmarkRunner.run` |

The three domain metrics are defined in
[`../backend/app/core/metrics.py`](../backend/app/core/metrics.py) and are
**guarded**: if `prometheus_client` is not installed, the helpers become no-ops
and the app still boots. `benchmark_success_rate` is only populated after a
benchmark run is triggered (`GET`/`POST /api/v1/benchmark`).

See [`../docs/observability.md`](../docs/observability.md) for dashboard panel
descriptions and example PromQL queries.
