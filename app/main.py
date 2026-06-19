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

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.api.v1.router import api_router
from app.config import settings
from app.core.exception_handlers import install_exception_handlers, _envelope, _request_id
from app.core.logging import configure_logging
from app.core.rate_limit import limiter
from app.database import engine
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.tenant import TenantMiddleware
from app.services.scheduler import shutdown_scheduler, start_scheduler


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    start_scheduler()
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
