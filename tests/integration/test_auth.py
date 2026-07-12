"""
Integration tests for app/api/v1/routes/auth.py against a real Postgres DB.

Covers: login success/failure (no email-enumeration leak), expired access
token rejection, refresh-token rotation + replay detection, and the login
rate limiter. See tests/integration/conftest.py for how to run this suite.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from tests.integration.conftest import SeededTenant, login


async def test_login_with_correct_credentials_returns_token_pair(client, tenant_a: SeededTenant):
    resp = await client.post(
        "/auth/login",
        json={"email": tenant_a.owner_email, "password": tenant_a.owner_password},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_login_with_wrong_password_is_401_and_generic(client, tenant_a: SeededTenant):
    resp = await client.post(
        "/auth/login",
        json={"email": tenant_a.owner_email, "password": "definitely-not-the-password"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "invalid_credentials"
    wrong_password_message = body["error"]["message"]

    # Same message/code for a non-existent email — must not leak whether the
    # account exists.
    resp2 = await client.post(
        "/auth/login",
        json={"email": f"no-such-user-{uuid.uuid4().hex}@example.com", "password": "whatever123"},
    )
    assert resp2.status_code == 401
    body2 = resp2.json()
    assert body2["error"]["code"] == "invalid_credentials"
    assert body2["error"]["message"] == wrong_password_message


async def test_expired_access_token_is_rejected(client, tenant_a: SeededTenant):
    import jwt

    from app.config import settings

    expired_payload = {
        "sub": str(tenant_a.owner_id),
        "tenant_id": str(tenant_a.tenant_id),
        "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
        "iat": datetime.now(timezone.utc) - timedelta(minutes=35),
        "jti": str(uuid.uuid4()),
        "typ": "access",
    }
    expired_token = jwt.encode(expired_payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    resp = await client.get(
        "/contacts",
        headers={
            "Authorization": f"Bearer {expired_token}",
            "X-Tenant-ID": str(tenant_a.tenant_id),
        },
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "token_expired"


async def test_missing_token_is_401(client, tenant_a: SeededTenant):
    resp = await client.get("/contacts", headers={"X-Tenant-ID": str(tenant_a.tenant_id)})
    assert resp.status_code == 401


async def test_refresh_token_rotation_and_replay_detection(client, tenant_a: SeededTenant):
    tokens = await login(client, tenant_a)
    refresh_1 = tokens["refresh_token"]

    # First rotation succeeds and returns a brand-new pair.
    resp = await client.post("/auth/refresh", json={"refresh_token": refresh_1})
    assert resp.status_code == 200
    tokens_2 = resp.json()
    refresh_2 = tokens_2["refresh_token"]
    assert refresh_2 != refresh_1

    # The new access token works against a protected endpoint.
    check = await client.get(
        "/contacts",
        headers={
            "Authorization": f"Bearer {tokens_2['access_token']}",
            "X-Tenant-ID": str(tenant_a.tenant_id),
        },
    )
    assert check.status_code == 200

    # Reusing the already-rotated (now revoked) refresh_1 must fail — replay.
    replay = await client.post("/auth/refresh", json={"refresh_token": refresh_1})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "token_invalid"


async def test_replay_detection_revokes_the_whole_token_family(client, tenant_a: SeededTenant):
    """
    Regression test for a real bug found while building this suite: replay
    detection in tokens.py::rotate_refresh_token() only flushed the family-wide
    revocation before raising TokenInvalidError, so get_db()'s rollback-on-
    exception silently discarded it, leaving the attacker's own sibling token
    valid. Fixed by committing the revocation before raising — see
    app/services/tokens.py.
    """
    tokens = await login(client, tenant_a)
    refresh_1 = tokens["refresh_token"]

    resp = await client.post("/auth/refresh", json={"refresh_token": refresh_1})
    assert resp.status_code == 200
    refresh_2 = resp.json()["refresh_token"]

    # Replay the already-rotated refresh_1 — triggers family-wide revocation.
    replay = await client.post("/auth/refresh", json={"refresh_token": refresh_1})
    assert replay.status_code == 401

    # The documented contract: replay revokes the *whole family*, so the
    # sibling token minted just before the replay must be dead too.
    now_also_dead = await client.post("/auth/refresh", json={"refresh_token": refresh_2})
    assert now_also_dead.status_code == 401


async def test_login_rate_limit_returns_429_eventually(client, tenant_a: SeededTenant):
    """
    Hits POST /auth/login repeatedly from a single (fake, per-test-unique) IP
    — see conftest.py's `client` fixture — until slowapi's RATE_LIMIT_LOGIN
    kicks in. Because every test gets its own fake source IP, this cannot
    contaminate any other test's rate-limit bucket.
    """
    from app.config import settings

    limit_count = int(settings.RATE_LIMIT_LOGIN.split("/")[0])

    statuses = []
    for _ in range(limit_count + 5):
        resp = await client.post(
            "/auth/login",
            json={"email": tenant_a.owner_email, "password": "wrong-password"},
        )
        statuses.append(resp.status_code)
        if resp.status_code == 429:
            break

    assert 429 in statuses, f"Never hit 429 within {limit_count + 5} attempts: {statuses}"
    # Everything before the 429 should be a normal auth failure, not something
    # unrelated blowing up.
    pre_429 = statuses[: statuses.index(429)]
    assert all(s == 401 for s in pre_429), statuses
