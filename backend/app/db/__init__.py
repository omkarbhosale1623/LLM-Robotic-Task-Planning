"""Persistence layer: abstract repository, in-memory + SQL implementations.

The SQL implementation is import-guarded — SQLAlchemy/asyncpg are only imported
when ``DATABASE_URL`` is set *and* the libraries import successfully. The
in-memory implementation is the default and is what the offline test-suite uses.
"""

from app.db.repository import (
    PlanMemoryRecord,
    Repository,
    RunRecord,
    SessionRecord,
    get_repository,
)

__all__ = [
    "PlanMemoryRecord",
    "Repository",
    "RunRecord",
    "SessionRecord",
    "get_repository",
]
