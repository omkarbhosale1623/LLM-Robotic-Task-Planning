"""REST routers, one module per resource."""

from fastapi import APIRouter

from app.api.routes import benchmark, capabilities, planning, sessions, world

api_router = APIRouter()
api_router.include_router(world.router, tags=["world"])
api_router.include_router(planning.router, tags=["planning"])
api_router.include_router(benchmark.router, tags=["benchmark"])
api_router.include_router(capabilities.router, tags=["capabilities"])
api_router.include_router(sessions.router, tags=["sessions"])
