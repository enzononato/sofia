"""
Tenant resolution middleware.

Resolves the current tenant from the incoming request and stores it in
request.state.tenant_id so all downstream dependencies can read it without
re-hitting the database on each call.

Strategies (configured via TENANT_RESOLUTION_STRATEGY env var):
  - "header"    — reads X-Tenant-ID (or custom header) — default
  - "subdomain" — extracts subdomain from Host header
  - "jwt"       — reads tenant_id claim from Bearer token

Security guarantees:
  - Public paths bypass resolution but never reach business handlers that
    require CurrentTenantId (those raise 401 if state.tenant_id is missing).
  - Inactive tenants are blocked at the middleware layer (403).
  - Errors are returned in the standard envelope shape.
"""

import logging
import uuid
from typing import Callable, Literal

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

# Paths that bypass tenant resolution (public/system routes)
_PUBLIC_PATHS = {
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/favicon.ico",
    "/api/v1/auth/signup",   # tenant doesn't exist yet
    "/api/v1/auth/login",    # tenant resolved internally from email lookup
    "/api/v1/auth/refresh",  # tenant resolved from the refresh token row
}

# Path prefixes that bypass middleware (tenant resolved internally by handlers)
_PUBLIC_PREFIXES = ("/api/v1/webhooks/", "/static")


_LookupBy = Literal["id", "slug", "id_or_slug"]


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        # Always strip whatever may be on request.state — never trust the previous request
        request.state.tenant_id = None
        request.state.tenant = None

        rid = getattr(request.state, "request_id", None)

        strategy = settings.TENANT_RESOLUTION_STRATEGY
        if strategy == "header":
            tenant_ref = request.headers.get(settings.TENANT_HEADER_NAME)
            lookup_by: _LookupBy = "id_or_slug"
        elif strategy == "subdomain":
            host = request.headers.get("host", "")
            parts = host.split(".")
            tenant_ref = parts[0] if len(parts) >= 2 else None
            lookup_by = "slug"
        elif strategy == "jwt":
            tenant_ref = _extract_tenant_from_jwt(request)
            lookup_by = "id"
        else:
            logger.error("invalid_tenant_strategy", extra={"request_id": rid, "strategy": strategy})
            return _err(500, "internal_error", "Tenant resolution misconfigured.", rid)

        if not tenant_ref:
            return _err(401, "tenant_not_resolved", "Tenant could not be identified.", rid)

        tenant = await _resolve_tenant(tenant_ref, lookup_by)

        if tenant is None:
            return _err(401, "tenant_not_resolved", "Tenant not found.", rid)

        if not tenant.is_active:
            return _err(403, "tenant_inactive", "Tenant is inactive.", rid)

        request.state.tenant_id = tenant.id
        request.state.tenant = tenant
        return await call_next(request)


def _err(status_code: int, code: str, message: str, request_id: str | None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if request_id:
        body["error"]["request_id"] = request_id
    return JSONResponse(status_code=status_code, content=body)


def _extract_tenant_from_jwt(request: Request) -> str | None:
    """Extract tenant_id claim from Bearer token without full auth validation."""
    from jose import JWTError, jwt as jose_jwt
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.removeprefix("Bearer ").strip()
    try:
        payload = jose_jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload.get("tenant_id")
    except JWTError:
        return None


async def _resolve_tenant(ref: str, lookup_by: _LookupBy) -> Tenant | None:
    """
    Lookup the tenant by the given strategy. Uses a short-lived isolated session
    so we don't share state with the request-scoped DB session.
    """
    async with AsyncSessionLocal() as session:
        if lookup_by == "id":
            try:
                tid = uuid.UUID(ref)
            except ValueError:
                return None
            stmt = select(Tenant).where(Tenant.id == tid)
        elif lookup_by == "slug":
            stmt = select(Tenant).where(Tenant.slug == ref)
        else:  # id_or_slug
            try:
                tid = uuid.UUID(ref)
                stmt = select(Tenant).where(Tenant.id == tid)
            except ValueError:
                stmt = select(Tenant).where(Tenant.slug == ref)

        result = await session.execute(stmt)
        return result.scalar_one_or_none()
