"""Custom exceptions and centralized exception handlers.

All errors are returned to clients in a consistent envelope::

    {"error": {"type": "...", "message": "...", "detail": {...}}}
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.auth import AuthError
from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for domain/application errors with an HTTP mapping."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_type: str = "app_error"

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    error_type = "not_found"


class PlanningFailure(AppError):
    """Instruction could not be parsed/grounded into a valid plan."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_type = "planning_failure"


class ValidationFailure(AppError):
    """A submitted plan failed validation against the world."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_type = "validation_failure"


def _envelope(error_type: str, message: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"type": error_type, "message": message, "detail": detail or {}}}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach consistent JSON error handlers to ``app``."""

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning("AppError on %s: %s", request.url.path, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.error_type, exc.message, exc.detail),
        )

    @app.exception_handler(AuthError)
    async def _handle_auth_error(request: Request, exc: AuthError) -> JSONResponse:
        logger.info("AuthError on %s: %s", request.url.path, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.error_type, exc.message),
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_envelope(
                "request_validation_error",
                "Request body failed validation.",
                {"errors": exc.errors()},
            ),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("internal_error", "An unexpected error occurred."),
        )
