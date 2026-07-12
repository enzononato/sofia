"""
FastAPI dependency functions.

Usage in route handlers:
    @router.get("/contacts")
    async def list_contacts(
        db: DBSession,
        tenant_id: CurrentTenantId,
        current_user: CurrentUser,
    ):
        ...

All authentication failures raise typed APIError subclasses so the global
handler emits a consistent error envelope (no raw HTTPException leaks).
"""

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    TenantInactiveError,
    TenantNotResolvedError,
    TokenExpiredError,
    TokenInvalidError,
    UnauthorizedError,
)
from app.core.security import decode_access_token
from app.database import get_db
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)


# ── Database session ────────────────────────────────────────────────────────

DBSession = Annotated[AsyncSession, Depends(get_db)]


# ── Tenant isolation ────────────────────────────────────────────────────────

async def get_current_tenant_id(request: Request) -> uuid.UUID:
    """
    Returns the tenant_id resolved by TenantMiddleware.
    Raises 401 if the middleware did not populate it (e.g., a public route
    leaked into protected territory).
    """
    tenant_id: uuid.UUID | None = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise TenantNotResolvedError("Tenant context is missing for this request.")
    return tenant_id


CurrentTenantId = Annotated[uuid.UUID, Depends(get_current_tenant_id)]


# ── Authentication ──────────────────────────────────────────────────────────

async def get_current_user(
    db: DBSession,
    tenant_id: CurrentTenantId,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    """
    Validate the access token AND ensure it matches the resolved tenant.
    Cross-tenant token reuse is structurally blocked here.
    """
    if credentials is None:
        raise UnauthorizedError("Not authenticated.")

    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError("Access token has expired.")
    except jwt.InvalidTokenError:
        raise TokenInvalidError("Access token is invalid.")

    try:
        user_id = uuid.UUID(payload["sub"])
        token_tenant = uuid.UUID(payload["tenant_id"])
    except (KeyError, ValueError, TypeError):
        raise TokenInvalidError("Access token payload is malformed.")

    if payload.get("typ") not in (None, "access"):
        # Refresh tokens never reach this dependency — but be defensive.
        raise TokenInvalidError("Wrong token type for this endpoint.")

    # Cross-tenant guard — the token's tenant must match the resolved tenant
    if token_tenant != tenant_id:
        raise TenantInactiveError("Access token tenant does not match the resolved tenant.")

    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise UnauthorizedError("User not found or inactive.")

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
