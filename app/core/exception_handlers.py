"""
Global exception handlers wired into the FastAPI app.

Translates every raised exception into the standard envelope defined in
app.core.errors so the frontend has a single shape to parse.
"""

import logging
import uuid

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, MultipleResultsFound, NoResultFound, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import APIError

logger = logging.getLogger(__name__)


def _envelope(
    *,
    code: str,
    message: str,
    status_code: int,
    request_id: str,
    details=None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }
    if details is not None:
        body["error"]["details"] = jsonable_encoder(details)
    return JSONResponse(status_code=status_code, content=body)


def _request_id(request: Request) -> str:
    """Reuse the request_id set by the middleware, fall back to a fresh UUID."""
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    rid = _request_id(request)
    logger.warning(
        "api_error",
        extra={
            "request_id": rid,
            "code": exc.code,
            "status_code": exc.status_code,
            "path": request.url.path,
            "method": request.method,
        },
    )
    return _envelope(
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        request_id=rid,
        details=exc.details,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Catch fastapi.HTTPException raised by older code paths or internal libs."""
    rid = _request_id(request)
    code = _http_code_to_machine_code(exc.status_code)
    message = str(exc.detail) if exc.detail else _http_code_to_message(exc.status_code)
    return _envelope(
        code=code,
        message=message,
        status_code=exc.status_code,
        request_id=rid,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    rid = _request_id(request)
    return _envelope(
        code="validation_error",
        message="Request validation failed.",
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        request_id=rid,
        details=exc.errors(),
    )


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """Unique violations, FK violations, etc. — usually surface as 409."""
    rid = _request_id(request)
    logger.warning(
        "integrity_error",
        extra={"request_id": rid, "path": request.url.path},
        exc_info=True,
    )
    return _envelope(
        code="integrity_violation",
        message="The operation conflicts with existing data.",
        status_code=status.HTTP_409_CONFLICT,
        request_id=rid,
    )


async def db_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """Catch-all for database errors that escape route handlers."""
    rid = _request_id(request)
    logger.exception(
        "database_error",
        extra={"request_id": rid, "path": request.url.path},
    )
    return _envelope(
        code="database_error",
        message="A database error occurred while processing the request.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        request_id=rid,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler — never let raw stack traces leak to the client."""
    rid = _request_id(request)
    logger.exception(
        "unhandled_exception",
        extra={"request_id": rid, "path": request.url.path},
    )
    return _envelope(
        code="internal_error",
        message="An unexpected error occurred. Please try again.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        request_id=rid,
    )


def install_exception_handlers(app: FastAPI) -> None:
    """Register handlers in order from most specific to least specific."""
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(MultipleResultsFound, db_error_handler)
    app.add_exception_handler(NoResultFound, db_error_handler)
    app.add_exception_handler(SQLAlchemyError, db_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)


# ── Internal helpers ────────────────────────────────────────────────────────

_HTTP_CODE_MAP = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "unprocessable_entity",
    429: "rate_limited",
    500: "internal_error",
    502: "bad_gateway",
    503: "service_unavailable",
}


def _http_code_to_machine_code(status_code: int) -> str:
    return _HTTP_CODE_MAP.get(status_code, f"http_{status_code}")


def _http_code_to_message(status_code: int) -> str:
    return _HTTP_CODE_MAP.get(status_code, f"HTTP {status_code}").replace("_", " ").capitalize()
