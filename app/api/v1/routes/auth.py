"""
Auth routes — public endpoints.

POST /auth/signup    — create a new Tenant + owner User
POST /auth/login     — exchange email+password for an access+refresh pair
POST /auth/refresh   — rotate a refresh token, issuing a new pair
POST /auth/logout    — revoke a refresh token
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from sqlalchemy import func

from app.api.deps import DBSession
from app.core.errors import (
    ConflictError,
    ForbiddenError,
    InvalidCredentialsError,
    UnprocessableEntityError,
)
from app.core.rate_limit import limiter
from app.core.security import hash_password, hash_refresh_token, verify_password
from app.config import settings
from app.models.invitation import Invitation
from app.models.tenant import Tenant, TenantPlan
from app.models.user import User, UserRole
from app.schemas.invitation import AcceptInviteRequest
from app.services.tokens import (
    issue_token_pair,
    revoke_refresh_token,
    rotate_refresh_token,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Auth"])


# ── Request / response schemas ──────────────────────────────────────────────

class SignupRequest(BaseModel):
    clinic_name: str = Field(..., min_length=2, max_length=255)
    clinic_slug: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    clinic_email: EmailStr
    owner_name: str = Field(..., min_length=2, max_length=255)
    owner_email: EmailStr
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=16)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(..., min_length=16)


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_minutes: int = settings.ACCESS_TOKEN_EXPIRE_MINUTES


# ── POST /auth/signup ───────────────────────────────────────────────────────

@router.post(
    "/signup",
    response_model=TokenPairResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(settings.RATE_LIMIT_SIGNUP)
async def signup(payload: SignupRequest, request: Request, db: DBSession):
    """
    Register a new clinic. Creates Tenant + owner User + first refresh token
    in a single transaction.
    """
    existing = await db.execute(select(Tenant).where(Tenant.slug == payload.clinic_slug))
    if existing.scalar_one_or_none():
        raise ConflictError(
            f"Slug '{payload.clinic_slug}' is already taken.",
            code="slug_taken",
        )

    tenant = Tenant(
        name=payload.clinic_name,
        slug=payload.clinic_slug,
        email=str(payload.clinic_email),
        plan=TenantPlan.FREE,
    )
    db.add(tenant)
    await db.flush()

    owner = User(
        tenant_id=tenant.id,
        full_name=payload.owner_name,
        email=str(payload.owner_email),
        hashed_password=hash_password(payload.password),
        role=UserRole.OWNER,
    )
    db.add(owner)

    try:
        await db.flush()
        pair = await issue_token_pair(
            db,
            owner,
            user_agent=request.headers.get("user-agent"),
            ip_address=_client_ip(request),
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictError(
            "Slug or email already exists.",
            code="duplicate_signup",
        )

    logger.info(
        "tenant_signup",
        extra={"tenant_id": str(tenant.id), "user_id": str(owner.id), "slug": tenant.slug},
    )
    return TokenPairResponse(access_token=pair.access_token, refresh_token=pair.refresh_token)


# ── POST /auth/login ────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenPairResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login(payload: LoginRequest, request: Request, db: DBSession):
    """
    Authenticate by email + password. Email is globally unique, so we resolve
    the tenant from the user record itself — no tenant header required.
    """
    result = await db.execute(select(User).where(User.email == str(payload.email)))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.hashed_password):
        # Same message for both cases — don't leak whether the email exists
        raise InvalidCredentialsError("Invalid credentials.")

    if not user.is_active:
        raise ForbiddenError("User account is deactivated.", code="user_deactivated")

    user.last_login_at = datetime.now(timezone.utc)

    pair = await issue_token_pair(
        db,
        user,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
    )
    await db.commit()

    logger.info(
        "user_login",
        extra={"user_id": str(user.id), "tenant_id": str(user.tenant_id)},
    )
    return TokenPairResponse(access_token=pair.access_token, refresh_token=pair.refresh_token)


# ── POST /auth/refresh ──────────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenPairResponse)
@limiter.limit(settings.RATE_LIMIT_REFRESH)
async def refresh(payload: RefreshRequest, request: Request, db: DBSession):
    """
    Rotate a refresh token. The presented token is consumed and a new pair
    is issued under the same family. Replay is detected and revokes the
    entire family.
    """
    pair = await rotate_refresh_token(
        db,
        payload.refresh_token,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
    )
    await db.commit()
    return TokenPairResponse(access_token=pair.access_token, refresh_token=pair.refresh_token)


# ── POST /auth/logout ───────────────────────────────────────────────────────

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: LogoutRequest, db: DBSession):
    """Revoke the presented refresh token. Idempotent."""
    await revoke_refresh_token(db, payload.refresh_token)
    await db.commit()


# ── POST /auth/accept-invite ──────────────────────────────────────────────────

@router.post("/accept-invite", response_model=TokenPairResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_SIGNUP)
async def accept_invite(payload: AcceptInviteRequest, request: Request, db: DBSession):
    """
    Public: redeem an invitation token to create the invited user in the
    inviting tenant and log them in. The tenant comes from the invitation row,
    never from a header — so this route bypasses the tenant middleware.
    """
    token_hash = hash_refresh_token(payload.token)
    invitation = await db.scalar(
        select(Invitation).where(Invitation.token_hash == token_hash)
    )
    now = datetime.now(timezone.utc)
    if invitation is None or invitation.accepted_at is not None or invitation.expires_at <= now:
        raise UnprocessableEntityError("Convite inválido ou expirado.", code="invalid_invite")

    existing = await db.scalar(
        select(func.count()).select_from(User).where(User.email == invitation.email)
    )
    if existing:
        raise ConflictError("Já existe um usuário com este e-mail.", code="email_taken")

    user = User(
        tenant_id=invitation.tenant_id,
        full_name=payload.full_name,
        email=invitation.email,
        hashed_password=hash_password(payload.password),
        role=UserRole(invitation.role),
        is_active=True,
        last_login_at=now,
    )
    db.add(user)
    invitation.accepted_at = now

    try:
        await db.flush()
        pair = await issue_token_pair(
            db,
            user,
            user_agent=request.headers.get("user-agent"),
            ip_address=_client_ip(request),
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictError("Não foi possível concluir o cadastro.", code="duplicate_user")

    logger.info(
        "invite_accepted",
        extra={"tenant_id": str(invitation.tenant_id), "user_id": str(user.id)},
    )
    return TokenPairResponse(access_token=pair.access_token, refresh_token=pair.refresh_token)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None
