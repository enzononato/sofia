"""
Symmetric encryption for secrets stored at rest (Fernet / AES-128-CBC + HMAC).

Currently used for per-professional Google OAuth refresh tokens. The key comes
from ENCRYPTION_KEY when set (a urlsafe-base64 32-byte Fernet key); otherwise it
is derived deterministically from SECRET_KEY so the feature works out of the box
on a single server. Set ENCRYPTION_KEY explicitly for key rotation / multi-server.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import settings


@lru_cache
def _fernet() -> Fernet:
    if settings.ENCRYPTION_KEY:
        key = settings.ENCRYPTION_KEY.encode()
    else:
        # Derive a valid 32-byte urlsafe-base64 Fernet key from SECRET_KEY.
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
