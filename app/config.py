from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Application ──────────────────────────────────────────────────────────
    APP_NAME: str = "Clinic SaaS"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"

    # JWT lifetimes — short access, long refresh (rotation enforced server-side)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30          # short — minimizes impact of theft
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14            # long — UX continuity
    REFRESH_TOKEN_BYTES: int = 64                  # entropy of the opaque refresh token

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/clinic_saas"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_POOL_TIMEOUT: int = 30                # seconds before raising on pool exhaustion
    DATABASE_POOL_RECYCLE: int = 1800              # recycle connections every 30 min
    DATABASE_POOL_PRE_PING: bool = True            # detect dead connections before use

    # ── Tenant resolution ────────────────────────────────────────────────────
    TENANT_RESOLUTION_STRATEGY: str = "header"     # header | subdomain | jwt
    TENANT_HEADER_NAME: str = "X-Tenant-ID"

    # ── CORS ─────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]

    # ── AI / Gemini ──────────────────────────────────────────────────────────
    GEMINI_API_KEY: Optional[str] = None
    DEFAULT_AI_MODEL: str = "gemini-2.0-flash"
    AI_HISTORY_LIMIT: int = 20

    # ── Evolution API (provider-managed — credentials never exposed to tenants) ─
    EVOLUTION_API_URL: Optional[str] = None
    EVOLUTION_API_KEY: Optional[str] = None
    APP_BASE_URL: str = "http://localhost:8000"      # used to build webhook URLs sent to Evolution

    # ── Rate limiting (in-memory, per-process) ───────────────────────────────
    # Production should swap the limiter backend to Redis; the limiter abstraction
    # already supports this via slowapi/limits storage URI.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_LOGIN: str = "10/minute"            # auth/login
    RATE_LIMIT_SIGNUP: str = "5/hour"              # auth/signup
    RATE_LIMIT_REFRESH: str = "30/minute"          # auth/refresh

    # ── Logging ──────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"                       # json | text

    # ── Pagination defaults ──────────────────────────────────────────────────
    DEFAULT_PAGE_LIMIT: int = 50
    MAX_PAGE_LIMIT: int = 200

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "case_sensitive": True}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
