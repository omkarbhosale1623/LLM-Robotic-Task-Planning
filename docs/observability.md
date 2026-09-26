# Observability

The backend exposes Prometheus metrics at `/metrics`; Prometheus scrapes them and
Grafana renders a provisioned dashboard. See [`../infra/README.md`](../infra/README.md)
for how to run the stack.

## Metrics catalog

### Standard HTTP metrics (prometheus-fastapi-instrumentator)
| Metric | Type | Use |
|--------|------|-----|
| `http_requests_total` | counter | request rate, 5xx ratio |
| `http_request_duration_seconds_bucket` | histogram | latency quantiles |

### Domain metrics (`app/core/metrics.py`)
| Metric | Type | Meaning |
|--------|------|---------|
| `plan_requests_total{mode}` | counter | plan requests by planner mode (`heuristic`/`llm`/`auto`) |
| `plan_actions` | histogram | number of primitives per produced plan |
| `benchmark_success_rate{mode}` | gauge | task-completion rate of the last benchmark run |

Domain metrics are import-guarded: without `prometheus_client` they become no-ops.
`benchmark_success_rate` is only populated after a benchmark run is triggered.

## Useful PromQL
```promql
# plan request rate by planner mode
sum(rate(plan_requests_total[5m])) by (mode)

# average plan length (primitives per plan)
rate(plan_actions_sum[5m]) / clamp_min(rate(plan_actions_count[5m]), 1)

# latest benchmark task-completion rate
benchmark_success_rate

# 5xx ratio
sum(rate(http_requests_total{status=~"5.."}[5m]))
  / clamp_min(sum(rate(http_requests_total[5m])), 1)
```

## Dashboard
`infra/grafana/dashboards/llm-planner-overview.json` auto-provisions into Grafana:
request rate, latency, error ratio, plan requests by mode, plan-length
distribution, and benchmark success rate.

## Alerts (`infra/prometheus/alerts.yml`)
- **BackendDown** — `up{job="backend"} == 0` for 1m.
- **HighErrorRate** — >5% 5xx over 5m.
- **HighRequestLatencyP95** — p95 latency high for 10m.
- **LowBenchmarkSuccessRate** — `benchmark_success_rate` below threshold.
