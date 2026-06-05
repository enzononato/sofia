"""
Security primitives: password hashing, JWT issuance, opaque refresh tokens.

JWTs (access tokens) are short-lived and stateless. Refresh tokens are opaque
random strings persisted (hashed) in the DB so they can be revoked at will.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Passwords ───────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── Access JWT (short-lived) ────────────────────────────────────────────────

def create_access_token(
    subject: Any,
    tenant_id: uuid.UUID,
    extra: dict | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(subject),
        "tenant_id": str(tenant_id),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": str(uuid.uuid4()),
        "typ": "access",
        **(extra or {}),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode + validate signature + exp. Raises jose.JWTError on any failure."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


# ── Refresh tokens (opaque, persisted hashed) ───────────────────────────────

def generate_refresh_token() -> str:
    """Cryptographically-strong opaque token; URL-safe so it fits anywhere."""
    return secrets.token_urlsafe(settings.REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    """SHA-256 hex digest. Constant-time comparison is performed by lookup-by-hash."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
