"""Prometheus domain metrics for the planner.

All metric objects are created lazily and guarded behind a try/except so the app
boots and the full test suite passes even when ``prometheus_client`` (pulled in
transitively by ``prometheus-fastapi-instrumentator``) is not installed. The
public helpers — :func:`record_plan` and :func:`set_benchmark_success_rate` —
are always safe to call; they become no-ops when the dependency is absent.

Metrics exposed (in addition to the default HTTP metrics from the FastAPI
instrumentator):

* ``plan_requests_total{mode}`` — counter of planning requests, labelled by the
  planner that actually produced the plan (``heuristic`` / ``llm`` / ``client``).
* ``plan_actions`` — histogram of plan length (number of primitive steps).
* ``benchmark_success_rate`` — gauge of the most recent benchmark completion
  rate (0..1), labelled by the benchmark ``mode``.
"""

from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger(__name__)

# Whether the prometheus_client backend is available. Set during import below.
METRICS_ENABLED = False

# Module-level metric handles; populated only when the import succeeds.
PLAN_REQUESTS_TOTAL = None
PLAN_ACTIONS = None
BENCHMARK_SUCCESS_RATE = None

try:  # pragma: no cover - exercised only when the optional dep is installed
    from prometheus_client import Counter, Gauge, Histogram

    PLAN_REQUESTS_TOTAL = Counter(
        "plan_requests_total",
        "Total planning requests, labelled by the planner that produced the plan.",
        ["mode"],
    )
    PLAN_ACTIONS = Histogram(
        "plan_actions",
        "Number of primitive actions in a produced plan.",
        buckets=(0, 1, 2, 4, 6, 8, 12, 16, 24),
    )
    BENCHMARK_SUCCESS_RATE = Gauge(
        "benchmark_success_rate",
        "Most recent benchmark task-completion rate (0..1), labelled by mode.",
        ["mode"],
    )
    METRICS_ENABLED = True
except Exception:  # pragma: no cover - metrics are optional
    logger.warning("prometheus_client unavailable; custom planner metrics disabled")


def record_plan(planner_used: str, action_count: int) -> None:
    """Record a single planning outcome. No-op when metrics are unavailable."""

    if not METRICS_ENABLED:  # pragma: no cover - depends on optional dep
        return
    try:  # pragma: no cover - exercised only with the optional dep installed
        PLAN_REQUESTS_TOTAL.labels(mode=planner_used or "unknown").inc()
        PLAN_ACTIONS.observe(max(0, int(action_count)))
    except Exception:  # pragma: no cover - never let metrics break a request
        logger.debug("failed to record plan metrics", exc_info=True)


def set_benchmark_success_rate(mode: str, rate: float) -> None:
    """Update the benchmark success-rate gauge. No-op when unavailable."""

    if not METRICS_ENABLED:  # pragma: no cover - depends on optional dep
        return
    try:  # pragma: no cover - exercised only with the optional dep installed
        BENCHMARK_SUCCESS_RATE.labels(mode=mode or "unknown").set(float(rate))
    except Exception:  # pragma: no cover - never let metrics break a request
        logger.debug("failed to set benchmark gauge", exc_info=True)
