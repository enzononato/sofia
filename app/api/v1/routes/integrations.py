"""
Integrations — Google Calendar (per-professional OAuth).

Flow:
  1. GET  /integrations/google/connect   (auth) → returns an authorization_url
     with a short-lived signed `state` carrying the user_id + tenant_id.
  2. GET  /integrations/google/callback   (PUBLIC — Google redirects here) →
     exchanges the code, stores the encrypted refresh token, redirects to the
     frontend settings page.
  3. GET  /integrations/google/status     (auth) → { connected, configured }.
  4. DELETE /integrations/google           (auth) → disconnect.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from jose import jwt
from sqlalchemy import select

from app.api.deps import CurrentTenantId, CurrentUser, DBSession
from app.config import settings
from app.core.crypto import encrypt
from app.core.errors import ForbiddenError
from app.models.google_credentials import GoogleCalendarCredential
from app.services import google_calendar as gcal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations", tags=["Integrations"])

_STATE_PURPOSE = "google_oauth"


@router.get("/google/connect")
async def google_connect(
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    """Return the Google consent URL for the current user to connect their calendar."""
    if not gcal.is_configured():
        raise ForbiddenError(
            "Integração com Google Calendar não está configurada no servidor.",
            code="google_not_configured",
        )
    state = jwt.encode(
        {
            "sub": str(current_user.id),
            "tenant_id": str(tenant_id),
            "purpose": _STATE_PURPOSE,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    url = await asyncio.to_thread(gcal.build_auth_url, state)
    return {"authorization_url": url}


@router.get("/google/callback")
async def google_callback(
    db: DBSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Public OAuth redirect target. Validates state, stores the refresh token."""
    redirect_base = f"{settings.FRONTEND_BASE_URL}/dashboard/calendar"

    if error or not code or not state:
        return RedirectResponse(f"{redirect_base}?google=error")

    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("purpose") != _STATE_PURPOSE:
            raise ValueError("bad purpose")
        user_id = uuid.UUID(payload["sub"])
        tenant_id = uuid.UUID(payload["tenant_id"])
    except Exception:
        logger.warning("google_callback_bad_state")
        return RedirectResponse(f"{redirect_base}?google=error")

    try:
        refresh_token, scope = await asyncio.to_thread(gcal.exchange_code, code)
    except Exception:
        logger.exception("google_callback_exchange_failed")
        return RedirectResponse(f"{redirect_base}?google=error")

    if not refresh_token:
        # Google only returns a refresh token on first consent; prompt=consent forces it.
        return RedirectResponse(f"{redirect_base}?google=norefresh")

    cred = await db.scalar(
        select(GoogleCalendarCredential).where(GoogleCalendarCredential.user_id == user_id)
    )
    now = datetime.now(timezone.utc)
    if cred is None:
        cred = GoogleCalendarCredential(
            tenant_id=tenant_id,
            user_id=user_id,
            encrypted_refresh_token=encrypt(refresh_token),
            scope=scope,
            connected_at=now,
        )
        db.add(cred)
    else:
        cred.encrypted_refresh_token = encrypt(refresh_token)
        cred.scope = scope
        cred.connected_at = now
    await db.commit()

    logger.info("google_calendar_connected", extra={"user_id": str(user_id), "tenant_id": str(tenant_id)})
    return RedirectResponse(f"{redirect_base}?google=connected")


@router.get("/google/status")
async def google_status(
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    cred = await db.scalar(
        select(GoogleCalendarCredential).where(
            GoogleCalendarCredential.user_id == current_user.id,
            GoogleCalendarCredential.tenant_id == tenant_id,
        )
    )
    return {
        "configured": gcal.is_configured(),
        "connected": cred is not None,
        "connected_at": cred.connected_at.isoformat() if cred and cred.connected_at else None,
    }


@router.delete("/google", status_code=204)
async def google_disconnect(
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    cred = await db.scalar(
        select(GoogleCalendarCredential).where(
            GoogleCalendarCredential.user_id == current_user.id,
            GoogleCalendarCredential.tenant_id == tenant_id,
        )
    )
    if cred is not None:
        await db.delete(cred)
        await db.commit()
