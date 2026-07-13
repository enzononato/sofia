"""
Real-time Inbox updates via Server-Sent Events (Wave 4).

POST /events/ticket — normal auth (Bearer JWT + X-Tenant-ID, same as every
    other route via CurrentUser/CurrentTenantId). Mints a short-lived ticket
    (a JWT with typ="sse", TTL=SSE_TICKET_EXPIRE_MINUTES) for the SPA to use
    when opening the stream below.
GET  /events/stream — the actual SSE connection. Browsers' native
    EventSource cannot send custom headers, so it can't carry the usual
    Authorization/X-Tenant-ID pair — auth here rides in the `?ticket=` query
    param instead. This exact path (not a shared prefix — see
    app/middleware/tenant.py's _PUBLIC_PREFIXES) is exempted from
    TenantMiddleware; this route resolves and revalidates tenant + user
    itself via get_sse_context() below, including re-checking `is_active` on
    both (TenantMiddleware does this on every normal request; since this
    route bypasses it, the check has to be reimplemented here so deactivating
    a tenant/user takes effect within one ticket TTL instead of never, for a
    connection that stays open across many ticket renewals).

No new dependency: hand-rolled StreamingResponse(media_type="text/event-stream")
rather than adding sse-starlette for a format this simple.
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass

import jwt
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentTenantId, CurrentUser, DBSession
from app.core.errors import TenantInactiveError, TokenExpiredError, TokenInvalidError, UnauthorizedError
from app.core.rate_limit import limiter
from app.core.security import create_access_token, decode_access_token
from app.config import settings
from app.models.tenant import Tenant
from app.models.user import User
from app.services import realtime

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/events", tags=["Realtime"])

# How often the stream sends a keep-alive comment while idle, so proxies/load
# balancers with an idle-connection timeout don't kill the connection.
_KEEPALIVE_INTERVAL_SECONDS = 15.0


@router.post("/ticket")
@limiter.limit(settings.RATE_LIMIT_SSE_TICKET)
async def create_sse_ticket(
    request: Request,  # required positional arg for slowapi's @limiter.limit
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    """Mint a short-lived ticket for GET /events/stream (see module docstring)."""
    ticket = create_access_token(
        subject=current_user.id,
        tenant_id=tenant_id,
        extra={"typ": "sse"},
        expires_minutes=settings.SSE_TICKET_EXPIRE_MINUTES,
    )
    return {"ticket": ticket, "expires_in": settings.SSE_TICKET_EXPIRE_MINUTES * 60}


@dataclass(slots=True)
class SSEContext:
    tenant: Tenant
    user: User


async def get_sse_context(
    db: DBSession,
    ticket: str = Query(..., description="Short-lived ticket from POST /events/ticket"),
) -> SSEContext:
    """
    Validate the ticket and load+revalidate tenant/user. Runs as a normal
    FastAPI dependency, so a bad ticket raises before any StreamingResponse
    is constructed — no special mid-stream error handling needed, and the
    error goes through the same global exception handler as every other
    endpoint (see app/core/exception_handlers.py).
    """
    try:
        payload = decode_access_token(ticket)
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError("SSE ticket has expired.")
    except jwt.InvalidTokenError:
        raise TokenInvalidError("SSE ticket is invalid.")

    if payload.get("typ") != "sse":
        # Rejects a normal 30-min access token used here, and (symmetrically)
        # every other endpoint's get_current_user already rejects an SSE
        # ticket used anywhere else (typ not in (None, "access")).
        raise TokenInvalidError("Token is not a valid SSE ticket.")

    try:
        user_id = uuid.UUID(payload["sub"])
        tenant_id = uuid.UUID(payload["tenant_id"])
    except (KeyError, ValueError, TypeError):
        raise TokenInvalidError("SSE ticket payload is malformed.")

    tenant = await db.get(Tenant, tenant_id)
    if tenant is None or not tenant.is_active:
        raise TenantInactiveError("Tenant is inactive or not found.")

    user = await db.get(User, user_id)
    if user is None or not user.is_active or user.tenant_id != tenant_id:
        raise UnauthorizedError("User not found or inactive.")

    return SSEContext(tenant=tenant, user=user)


async def _event_stream(tenant_id: uuid.UUID, request: Request):
    """
    The actual SSE body. No DB access here (ticket validation already
    happened in the get_sse_context dependency, before this generator was
    ever constructed) — just relays events from the in-process realtime
    registry (app/services/realtime.py) as they're published.

    `finally: unsubscribe()` runs on every exit path — normal generator
    close, client disconnect propagating as GeneratorExit/CancelledError, or
    any exception — so a subscriber can never leak.
    """
    queue = realtime.subscribe(tenant_id)
    logger.info("sse_subscribed", extra={"tenant_id": str(tenant_id)})
    try:
        yield ": connected\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield f"data: {json.dumps(event)}\n\n"
    finally:
        realtime.unsubscribe(tenant_id, queue)
        logger.info("sse_unsubscribed", extra={"tenant_id": str(tenant_id)})


@router.get("/stream")
async def stream_events(request: Request, ctx: SSEContext = Depends(get_sse_context)):
    return StreamingResponse(
        _event_stream(ctx.tenant.id, request),
        media_type="text/event-stream",
        headers={
            # Disable buffering on common reverse proxies (nginx) so events
            # flush immediately instead of waiting for a buffer to fill.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
