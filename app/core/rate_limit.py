"""
Rate limiting using slowapi (limits-backed, in-memory by default).

Key strategy:
  - For unauthenticated routes (login, signup, refresh) we key on client IP.
  - For authenticated routes we'd key on user_id; not currently applied —
    add `@limiter.limit("...", key_func=user_id_key)` on those endpoints later.

Production note:
  Swap STORAGE_URI to a Redis URL (e.g. redis://...) so limits survive
  process restarts and are shared across replicas.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings


limiter = Limiter(
    key_func=get_remote_address,
    enabled=settings.RATE_LIMIT_ENABLED,
    storage_uri="memory://",
    default_limits=[],
)
