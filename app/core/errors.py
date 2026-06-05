"""
Standardized error envelope + domain exception hierarchy.

Every error response served by the API conforms to:

    {
      "error": {
        "code": "machine_readable_code",
        "message": "Human-readable explanation.",
        "details": <optional, list/dict>,
        "request_id": "<uuid for log correlation>"
      }
    }

Route handlers should raise APIError subclasses (or generic exceptions) — the
global handler in app.main converts them to this envelope.

Backwards compatibility:
  - Any code still raising fastapi.HTTPException is also caught and translated
    into the same envelope, mapping `detail` → `message`.
"""

from typing import Any


class APIError(Exception):
    """Base class for any error the API explicitly raises to the client."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details


class BadRequestError(APIError):
    status_code = 400
    code = "bad_request"


class UnauthorizedError(APIError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(APIError):
    status_code = 403
    code = "forbidden"


class NotFoundError(APIError):
    status_code = 404
    code = "not_found"


class ConflictError(APIError):
    status_code = 409
    code = "conflict"


class UnprocessableEntityError(APIError):
    status_code = 422
    code = "unprocessable_entity"


class RateLimitError(APIError):
    status_code = 429
    code = "rate_limited"


class InvalidCredentialsError(UnauthorizedError):
    code = "invalid_credentials"


class TokenExpiredError(UnauthorizedError):
    code = "token_expired"


class TokenInvalidError(UnauthorizedError):
    code = "token_invalid"


class TenantInactiveError(ForbiddenError):
    code = "tenant_inactive"


class TenantNotResolvedError(UnauthorizedError):
    code = "tenant_not_resolved"
