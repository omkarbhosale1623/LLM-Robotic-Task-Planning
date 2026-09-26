"""Tests for the (optional) Prometheus observability layer.

These are written to pass whether or not ``prometheus-fastapi-instrumentator`` /
``prometheus_client`` are installed: the domain-metric helpers must always be
safe no-ops, and the ``/metrics`` endpoint is only asserted when the dependency
is present.
"""

from __future__ import annotations

import importlib.util

from app.core import metrics
from fastapi.testclient import TestClient

HAS_PROMETHEUS = importlib.util.find_spec("prometheus_client") is not None
HAS_INSTRUMENTATOR = (
    importlib.util.find_spec("prometheus_fastapi_instrumentator") is not None
)


def test_metric_helpers_are_safe_noops() -> None:
    """The helpers never raise, regardless of whether the backend is installed."""

    metrics.record_plan("heuristic", 4)
    metrics.record_plan("llm", 0)
    metrics.set_benchmark_success_rate("heuristic", 1.0)
    # METRICS_ENABLED tracks dependency availability without forcing it.
    assert metrics.METRICS_ENABLED == HAS_PROMETHEUS


def test_metrics_endpoint_when_instrumentator_present(client: TestClient) -> None:
    if not HAS_INSTRUMENTATOR:
        # No instrumentator installed: /metrics is intentionally not mounted.
        assert client.get("/metrics").status_code == 404
        return

    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]


def test_plan_request_increments_metric_when_present(client: TestClient) -> None:
    if not HAS_PROMETHEUS:
        return

    # Drive a plan + a benchmark so the custom metrics get a value, then assert
    # the metric names show up in the exposition output.
    client.post(
        "/api/v1/plan",
        json={"instruction": "pick up the red block", "mode": "heuristic"},
    )
    client.get("/api/v1/benchmark?mode=heuristic")

    if not HAS_INSTRUMENTATOR:
        return
    body = client.get("/metrics").text
    assert "plan_requests_total" in body
    assert "benchmark_success_rate" in body
