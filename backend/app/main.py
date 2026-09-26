"""FastAPI application factory.

Wires together configuration, logging, error handling, CORS/GZip middleware, the
versioned ``/api/v1`` router (protected by always-enforced Supabase JWT auth), the
``/ws/execution`` WebSocket (also authenticated), and public ``/health`` +
``/metrics`` endpoints.

Process-wide collaborators (the persistence repository, the per-user/session
:class:`~app.services.session_registry.SessionRegistry`, the benchmark runner) are
created in the lifespan and stored on ``app.state``. Each user gets their own
world + executor per session via the registry — there is no shared mutable world.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app import __version__
from app.api import ws
from app.api.deps import build_state, make_require_user
from app.api.routes import api_router
from app.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.schemas.models import HealthResponse

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    app.state.app_state = build_state(settings)
    await app.state.app_state.repository.init()
    logger.info(
        "%s v%s started (scene=%s, persistence=%s, auth_required=%s, %s)",
        settings.app_name,
        __version__,
        settings.default_scene,
        app.state.app_state.repository.backend,
        settings.auth_required,
        app.state.app_state.planning.availability_note(),
    )
    yield
    await app.state.app_state.repository.close()
    logger.info("shutting down")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application."""

    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "LLM-powered robotic task-planning agent. Decomposes natural-language "
            "instructions into validated primitive-action plans and executes them in "
            "a simulated tabletop world. Runs with no GPU via a deterministic "
            "heuristic planner; a real Mistral (default) / Anthropic LLM planner is "
            "gated behind a provider key. All /api/v1 and /ws routes require a "
            "Supabase JWT; /health and /metrics are public."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=512)

    register_exception_handlers(app)

    # Prometheus instrumentation. Guarded so the app still boots if the optional
    # `prometheus-fastapi-instrumentator` package is not installed. When present,
    # it adds default HTTP metrics (request rate, latency histogram, status codes)
    # and exposes them at /metrics in Prometheus text format. /metrics is public.
    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator().instrument(app).expose(
            app, endpoint="/metrics", include_in_schema=False
        )
    except Exception:  # pragma: no cover - metrics are optional
        logger.warning("prometheus instrumentation unavailable; /metrics disabled")

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        st = app.state.app_state
        return HealthResponse(
            status="ok",
            app=settings.app_name,
            version=__version__,
            llm_available=st.planning.llm_available(),
            llm_note=st.planning.availability_note(),
        )

    # Always-enforced Supabase JWT auth on every business route. /health and
    # /metrics stay public (declared outside this router).
    require_user = make_require_user(settings)
    app.include_router(api_router, prefix="/api/v1", dependencies=[Depends(require_user)])
    app.include_router(ws.router)

    return app


app = create_app()
