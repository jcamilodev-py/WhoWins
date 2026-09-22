import logging
from datetime import UTC, datetime

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.shared.exception.errors import (
    AuthenticationRequiredException,
    BusinessException,
    DuplicateResourceException,
    PermissionDeniedException,
    ResourceNotFoundException,
)
from app.shared.exception.schemas import ErrorResponse

logger = logging.getLogger(__name__)


def _error_body(status_code: int, reason: str, message: str, request: Request) -> dict:
    return ErrorResponse(
        timestamp=datetime.now(UTC),
        status=status_code,
        error=reason,
        message=message,
        path=request.url.path,
    ).model_dump(mode="json")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ResourceNotFoundException)
    async def handle_resource_not_found(request: Request, exc: ResourceNotFoundException):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=_error_body(status.HTTP_404_NOT_FOUND, "Not Found", exc.message, request),
        )

    @app.exception_handler(DuplicateResourceException)
    async def handle_duplicate_resource(request: Request, exc: DuplicateResourceException):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_error_body(status.HTTP_409_CONFLICT, "Conflict", exc.message, request),
        )

    @app.exception_handler(BusinessException)
    async def handle_business_exception(request: Request, exc: BusinessException):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_error_body(status.HTTP_400_BAD_REQUEST, "Bad Request", exc.message, request),
        )

    @app.exception_handler(PermissionDeniedException)
    async def handle_permission_denied(request: Request, exc: PermissionDeniedException):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=_error_body(status.HTTP_403_FORBIDDEN, "Forbidden", exc.message, request),
        )

    @app.exception_handler(AuthenticationRequiredException)
    async def handle_authentication_required(request: Request, exc: AuthenticationRequiredException):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=_error_body(
                status.HTTP_401_UNAUTHORIZED,
                "Unauthorized",
                "Authentication is required to access this resource",
                request,
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception):
        # Se registra entero para poder depurarlo, pero al cliente solo le llega
        # un mensaje generico: nada de tracebacks ni detalles internos.
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "Internal Server Error",
                "An unexpected error occurred",
                request,
            ),
        )
