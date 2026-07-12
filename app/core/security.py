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

import bcrypt
import jwt

from app.config import settings


# ── Passwords ───────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed/corrupt hash — never let this become a 500 on login.
        return False


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
    """Decode + validate signature + exp. Raises jwt.PyJWTError (ExpiredSignatureError /
    InvalidTokenError, etc.) on any failure."""
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
