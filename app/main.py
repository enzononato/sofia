"""
FastAPI application factory.

Wiring order matters:
  1. Logging is configured first so every later message uses the JSON formatter.
  2. RequestIdMiddleware is the outermost so request_id is available everywhere
     (including TenantMiddleware errors and exception handlers).
  3. CORS comes next so preflight responses bypass the rest of the stack.
  4. TenantMiddleware runs after CORS so OPTIONS requests aren't rejected.
  5. Exception handlers and routers are attached last.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select

from app.api.v1.router import api_router
from app.config import settings
from app.core.exception_handlers import install_exception_handlers, _envelope, _request_id
from app.core.logging import configure_logging
from app.core.rate_limit import limiter
from app.database import AsyncSessionLocal, engine
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.tenant import TenantMiddleware
from app.models.tenant import Tenant
from app.services.scheduler import shutdown_scheduler, start_scheduler

_lifespan_logger = logging.getLogger(__name__)


async def _warn_tenants_missing_webhook_secret() -> None:
    """
    One-time startup check (item 1.6 of the robustness plan): the WhatsApp
    webhook now fails CLOSED when a tenant has no webhook_secret stored
    (previously that case accepted ANY request unauthenticated). Any tenant
    with a WhatsApp `token` but no matching `webhook_secret` will silently
    stop receiving inbound messages after this change until they reconnect
    WhatsApp (reconnecting regenerates the secret). This is purely an
    operational heads-up logged once at boot — it never blocks/fails startup.
    """
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Tenant).where(Tenant.is_active.is_(True)))
            tenants = result.scalars().all()
    except Exception:
        _lifespan_logger.exception("startup_webhook_secret_check_failed")
        return

    for tenant in tenants:
        wa = (tenant.settings or {}).get("whatsapp", {}) or {}
        if wa.get("token") and not wa.get("webhook_secret"):
            _lifespan_logger.warning(
                "tenant_missing_webhook_secret",
                extra={"tenant_id": str(tenant.id), "tenant_slug": tenant.slug},
            )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    start_scheduler()
    await _warn_tenants_missing_webhook_secret()
    # Post-restart recovery sweep (item 1.8): re-schedule a reply for any
    # contact whose newest message was INBOUND and never got answered because
    # the process restarted mid-debounce. Imported here (not at module level)
    # to keep this file's import surface unchanged outside the lifespan
    # function, which is the only part of app/main.py in scope for this change.
    from app.api.v1.routes.webhooks import run_pending_reply_recovery_sweep
    await run_pending_reply_recovery_sweep()
    try:
        yield
    finally:
        shutdown_scheduler()
        await engine.dispose()


def create_application() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── Rate limiter wiring (must precede the limiter-decorated routes) ────
    app.state.limiter = limiter

    async def _rate_limit_handler(request, exc: RateLimitExceeded):
        return _envelope(
            code="rate_limited",
            message="Too many requests. Please slow down.",
            status_code=429,
            request_id=_request_id(request),
            details={"limit": str(exc.detail)} if getattr(exc, "detail", None) else None,
        )

    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    # ── Middlewares (order: outermost first) ───────────────────────────────
    # Inner middlewares run "closer" to the handler. Starlette adds them in
    # reverse, so the LAST add_middleware call is the OUTERMOST one.
    app.add_middleware(TenantMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)

    # ── Exception handlers ─────────────────────────────────────────────────
    install_exception_handlers(app)

    # ── Routers ────────────────────────────────────────────────────────────
    app.include_router(api_router)

    @app.get("/health", tags=["System"])
    async def health_check():
        return {"status": "ok", "version": settings.APP_VERSION}

    return app


app = create_application()
