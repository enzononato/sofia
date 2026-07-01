import logging
from functools import lru_cache
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

_INSECURE_SECRET = "change-me-in-production"


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
    DATABASE_SCHEMA: str = "public"          # PostgreSQL schema (e.g. "sofia")
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
    DEFAULT_AI_MODEL: str = "gemini-2.5-flash"
    AI_HISTORY_LIMIT: int = 20

    # ── Conversation humanization (batching, partitioned replies, typing) ─────
    # These shape how Sofia replies on WhatsApp so it feels human. All in-process
    # (single worker). Disable any layer independently via the *_ENABLED flags.
    #
    # Batching: accumulate rapid-fire messages from the same contact before
    # replying once. A new inbound resets the timer (debounce). Media flushes
    # the batch immediately.
    MESSAGE_BATCHING_ENABLED: bool = True
    BATCH_WINDOW_MIN_SECONDS: float = 8.0      # lower bound of the debounce window
    BATCH_WINDOW_MAX_SECONDS: float = 10.0     # upper bound (random within [min, max])

    # Partitioned replies: the model splits long answers with a delimiter; we
    # send each part as its own WhatsApp message.
    RESPONSE_SPLIT_ENABLED: bool = True
    RESPONSE_SPLIT_MAX_CHARS: int = 320        # fallback split size when the model omits the delimiter

    # Human typing simulation: "composing" presence + delay proportional to the
    # part length, with random jitter (never a fixed delay).
    TYPING_SIMULATION_ENABLED: bool = True
    TYPING_CHARS_PER_SECOND: float = 25.0      # simulated typing speed
    TYPING_MIN_SECONDS: float = 1.2            # floor per part
    TYPING_MAX_SECONDS: float = 6.0            # ceiling per part
    TYPING_JITTER: float = 0.15                # ±15% random variation

    # Read receipt: mark the patient's messages as read before replying.
    READ_RECEIPT_ENABLED: bool = True

    # Presence-aware waiting: hold Sofia's reply while the contact is actively
    # "typing" (UAZAPI presence = composing/recording), so she answers the whole
    # burst like a human would. Requires the webhook to subscribe to the `presence`
    # event; degrades to plain debounce if the provider never sends it.
    PRESENCE_TYPING_ENABLED: bool = True
    TYPING_HOLD_SECONDS: float = 12.0       # a composing/recording/paused event keeps us waiting this long
    TYPING_MAX_HOLD_SECONDS: float = 45.0   # absolute cap so a stuck "typing" never hangs the reply
    TYPING_POLL_SECONDS: float = 1.0        # how often we re-check the typing flag while holding

    # ── UAZAPI (provider-managed — credentials never exposed to tenants) ─────────
    # One UAZAPI server hosts all clinics. UAZAPI_URL is the server base; the
    # admin token creates/lists instances. Each clinic gets its own instance whose
    # per-instance token (returned on create) is the auth used for that clinic's
    # sends — stored in tenant.settings["whatsapp"]["token"] and never serialized.
    UAZAPI_URL: Optional[str] = None
    UAZAPI_ADMIN_TOKEN: Optional[str] = None
    APP_BASE_URL: str = "http://localhost:8000"      # used to build webhook URLs sent to UAZAPI

    # ── Email (transactional, for staff invites) ─────────────────────────────
    # If RESEND_API_KEY is unset, invites still work: the API returns the invite
    # link so the admin can send it manually (no email is dispatched).
    RESEND_API_KEY: Optional[str] = None
    MAIL_FROM: str = "Sofia <onboarding@resend.dev>"
    FRONTEND_BASE_URL: str = "http://localhost:3000"  # builds invite/accept links
    INVITE_EXPIRE_HOURS: int = 168                    # 7 days

    # ── Encryption at rest (Fernet) ──────────────────────────────────────────
    # Used to encrypt Google OAuth refresh tokens. If unset, a key is derived
    # deterministically from SECRET_KEY (fine for single-server; set explicitly
    # for rotation/multi-server).
    ENCRYPTION_KEY: Optional[str] = None

    # ── Background scheduler (in-process APScheduler) ─────────────────────────
    SCHEDULER_ENABLED: bool = True
    REMINDER_JOB_MINUTES: int = 15                    # how often the reminder job runs
    REENGAGE_JOB_HOURS: int = 6                       # how often the re-engagement job runs
    REENGAGE_AFTER_DAYS: int = 3                      # silence before a re-engagement nudge
    REENGAGE_COOLDOWN_DAYS: int = 7                   # min gap between nudges to the same contact

    # ── Google Calendar (per-professional OAuth) ─────────────────────────────
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/integrations/google/callback"

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

    # extra="ignore": tolerate stray/legacy env vars instead of crashing on boot.
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }

    @model_validator(mode="after")
    def _validate_secrets(self) -> "Settings":
        """Fail fast on an insecure SECRET_KEY in production; warn loudly in dev."""
        if self.SECRET_KEY == _INSECURE_SECRET or len(self.SECRET_KEY) < 32:
            msg = (
                "SECRET_KEY is missing, too short (<32 chars), or still the default "
                "placeholder. Set a strong random SECRET_KEY in the environment."
            )
            if not self.DEBUG:
                raise ValueError(msg)
            logger.warning("INSECURE CONFIG: %s", msg)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
