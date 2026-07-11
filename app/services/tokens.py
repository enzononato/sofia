"""
Token issuance / rotation / revocation.

This is the *only* place that knows how access + refresh pairs are minted.
Routes call into here and never touch the storage primitives directly.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import TokenInvalidError
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    refresh_token_expiry,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TokenPair:
    access_token: str
    refresh_token: str


async def issue_token_pair(
    db: AsyncSession,
    user: User,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
    family_id: uuid.UUID | None = None,
) -> TokenPair:
    """
    Mint a fresh (access, refresh) pair. New `family_id` for fresh logins;
    callers pass the existing one when rotating.
    """
    access = create_access_token(
        subject=user.id,
        tenant_id=user.tenant_id,
        extra={"role": user.role, "email": user.email},
    )

    refresh_plain = generate_refresh_token()
    db.add(RefreshToken(
        token_hash=hash_refresh_token(refresh_plain),
        user_id=user.id,
        tenant_id=user.tenant_id,
        family_id=family_id or uuid.uuid4(),
        expires_at=refresh_token_expiry(),
        user_agent=user_agent,
        ip_address=ip_address,
    ))
    await db.flush()

    return TokenPair(access_token=access, refresh_token=refresh_plain)


async def rotate_refresh_token(
    db: AsyncSession,
    presented_token: str,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> TokenPair:
    """
    Validate the presented refresh token, revoke it, and mint a new pair.

    Replay protection:
      If the presented token is already revoked, treat it as a stolen-token
      replay and revoke the entire family — forcing every device on this
      family to re-authenticate.
    """
    token_hash = hash_refresh_token(presented_token)
    row = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    rt = row.scalar_one_or_none()

    if rt is None:
        raise TokenInvalidError("Refresh token is not recognized.")

    now = datetime.now(timezone.utc)

    if rt.revoked_at is not None:
        # Replay attack — revoke the whole family for safety. This must be
        # committed here, not just flushed: the caller (POST /auth/refresh)
        # raises TokenInvalidError right after this, and get_db()'s exception
        # handler rolls back the session on ANY exception — a flush-only
        # revocation would be silently discarded, leaving every sibling
        # token in the family still valid despite the "revoked" log line.
        await _revoke_family(db, rt.family_id, reason="replay_detected")
        await db.commit()
        logger.warning(
            "refresh_token_replay_detected",
            extra={
                "user_id": str(rt.user_id),
                "tenant_id": str(rt.tenant_id),
                "family_id": str(rt.family_id),
            },
        )
        raise TokenInvalidError("Refresh token has been revoked.")

    if rt.expires_at <= now:
        raise TokenInvalidError("Refresh token has expired.")

    # Load the user fresh — captures status / role changes since issuance
    user_row = await db.execute(select(User).where(User.id == rt.user_id))
    user = user_row.scalar_one_or_none()
    if user is None or not user.is_active:
        raise TokenInvalidError("User is no longer active.")

    # Mark the presented token as consumed
    rt.revoked_at = now

    # Mint the next link in this family
    return await issue_token_pair(
        db,
        user,
        user_agent=user_agent,
        ip_address=ip_address,
        family_id=rt.family_id,
    )


async def revoke_refresh_token(db: AsyncSession, presented_token: str) -> None:
    """Logout: silently no-ops if the token is unknown or already revoked."""
    token_hash = hash_refresh_token(presented_token)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


async def revoke_all_user_tokens(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Sign-out-everywhere — typically called on password change or admin action."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


async def _revoke_family(db: AsyncSession, family_id: uuid.UUID, *, reason: str) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    logger.warning("refresh_token_family_revoked", extra={"family_id": str(family_id), "reason": reason})
