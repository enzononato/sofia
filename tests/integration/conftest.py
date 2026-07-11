"""
Integration test infra — exercises the *real* FastAPI app (all middlewares,
including TenantMiddleware) against a *real* Postgres database via
httpx.AsyncClient + ASGITransport. No mocks of the DB layer.

────────────────────────────────────────────────────────────────────────────
HOW TO RUN
────────────────────────────────────────────────────────────────────────────
1. Make sure a Postgres server is reachable at DATABASE_URL (default:
   postgresql+asyncpg://postgres:postgres@localhost:5432/clinic_saas — the
   same one docker-compose.yml starts). From the repo root:

       docker compose up -d

   If you're in a worktree and a Postgres container is already listening on
   localhost:5432 (e.g. started from another worktree/checkout), you do NOT
   need to start a second one — these tests only need *a* reachable Postgres,
   not a dedicated container. `docker ps` to check first.

2. Run only the integration suite:

       venv\\Scripts\\python -m pytest tests/integration -q

   This is also the ONLY way these tests run — tests/integration is excluded
   from the default `pytest tests/` / bare `pytest` invocation via
   `addopts = --ignore=tests/integration` in pytest.ini, so the pure/in-memory
   suite (tests/) is 100% unaffected by this package even existing.

3. A single-file run works too:

       venv\\Scripts\\python -m pytest tests/integration/test_auth.py -q

Override the DB via a real DATABASE_URL env var if your Postgres isn't at the
default host/port/credentials (standard pydantic-settings: OS env vars win
over the .env file).

────────────────────────────────────────────────────────────────────────────
MECHANISM
────────────────────────────────────────────────────────────────────────────
Every test session:
  - picks a throwaway schema name `test_<uuid8>`
  - sets the `DATABASE_SCHEMA` env var to it *before* anything under `app.*`
    is imported anywhere in this process (this module is always the first
    thing pytest imports for this package, so this ordering is safe) — this
    mirrors the exact mechanism app/database.py and alembic/env.py already
    use in production (`search_path` via `connect_args`), no invented
    machinery
  - runs `python -m alembic upgrade head` (subprocess, same interpreter) so
    the schema gets the real, current migration history
  - imports app.main lazily (only after the above), builds an
    httpx.AsyncClient bound to the in-memory ASGI app
  - drops the schema at teardown

LIMITATIONS FOR FUTURE ROUNDS (read this before adding tests for new behavior
being merged from the other 3 workstreams):
  - webhooks.py is intentionally NOT covered here (out of scope for this
    slice) — a future round needs its own fixtures for UAZAPI's webhook
    token/query-param auth (see app/api/v1/routes/webhooks.py).
  - The whole integration test session shares ONE Postgres schema and ONE
    asyncio event loop (see `loop_scope="session"` below) — tests do not get
    a fresh DB per test, only fresh rows (every seeded Tenant/User/Contact
    uses a random uuid suffix). Don't assume table-level isolation between
    tests; if a future test needs to assert exact row counts, filter by the
    tenant_id it created itself.
  - The FastAPI `lifespan` (APScheduler start/stop) is deliberately never
    triggered — ASGITransport doesn't invoke it unless you wrap the app with
    asgi-lifespan's LifespanManager, and none of the routes under test need
    it. SCHEDULER_ENABLED=false is set regardless as a second guard. If a
    future round needs the scheduler running, add that wiring explicitly.
  - Each test's httpx.AsyncClient is bound to a per-test **fake source IP**
    (derived from the test's nodeid) precisely so slowapi's IP-keyed rate
    limiter doesn't leak state between tests. The one test that deliberately
    exhausts the login rate limit relies on this (same IP for all its
    requests, unique vs. every other test).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

# ── 1. Env vars MUST be set before any `app.*` import happens ──────────────
_TEST_SCHEMA = f"test_{uuid.uuid4().hex[:10]}"
os.environ["DATABASE_SCHEMA"] = _TEST_SCHEMA
os.environ.setdefault("SECRET_KEY", "integration-tests-only-secret-key-0123456789abcdef")
os.environ["SCHEDULER_ENABLED"] = "false"
# pool_pre_ping issues a ping (a real await) on connection checkout. Combined
# with Starlette's BaseHTTPMiddleware (TenantMiddleware) spawning call_next in
# its own anyio task, this occasionally races against httpx's ASGITransport
# event loop bookkeeping and raises a spurious "attached to a different loop"
# from asyncpg. Harmless to disable for a short-lived, definitely-alive local
# test Postgres.
os.environ["DATABASE_POOL_PRE_PING"] = "false"


def _force_null_pool_for_async_engine() -> None:
    """
    app/database.py builds `engine` as a *pooled* AsyncEngine (pool_size,
    pool_pre_ping, ...) — correct for production. Under test, that pool
    interacts badly with Starlette's BaseHTTPMiddleware (TenantMiddleware
    spawns `call_next` in its own anyio task) + SQLAlchemy's greenlet-based
    async bridge: a pooled asyncpg connection checked out by one task and
    handed to another intermittently corrupts ("attached to a different
    loop" / "another operation is in progress" from asyncpg).

    NullPool opens a brand-new asyncpg connection on every checkout and
    drops it on checkin — no connection is ever shared across task/loop
    boundaries, which sidesteps this whole class of bug. Fine for a
    short-lived test session against a local Postgres; would be wasteful in
    production, which is why this is patched here rather than in
    app/database.py itself.

    This monkeypatches `sqlalchemy.ext.asyncio.create_async_engine` — it
    MUST run before `app.database` (which does
    `from sqlalchemy.ext.asyncio import create_async_engine`) is imported
    anywhere in this process, hence it runs at conftest module import time.
    """
    import sqlalchemy.ext.asyncio as sa_asyncio
    from sqlalchemy.pool import NullPool

    _original_create_async_engine = sa_asyncio.create_async_engine

    def _patched(*args, **kwargs):
        for key in ("pool_size", "max_overflow", "pool_timeout", "pool_recycle"):
            kwargs.pop(key, None)
        kwargs["poolclass"] = NullPool
        return _original_create_async_engine(*args, **kwargs)

    sa_asyncio.create_async_engine = _patched


_force_null_pool_for_async_engine()

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Collection: mark every test in this package `integration` + pin them to
#    a single session-scoped asyncio event loop (required so the SQLAlchemy
#    async engine's connection pool isn't handed connections across
#    incompatible event loops between test functions). ─────────────────────

def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(pytest.mark.integration)
        item.add_marker(pytest.mark.asyncio(loop_scope="session"))


# ── 2. One-time schema create + migrate + (at the very end) drop ───────────

@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def _integration_database() -> AsyncIterator[None]:
    import asyncpg

    from app.config import settings

    assert settings.DATABASE_SCHEMA == _TEST_SCHEMA, (
        "settings.DATABASE_SCHEMA does not match the schema this fixture created — "
        "something imported app.config before conftest.py set the env var."
    )

    admin_dsn = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn=admin_dsn)
    try:
        await conn.execute(f'CREATE SCHEMA "{_TEST_SCHEMA}"')
    finally:
        await conn.close()

    try:
        _run_alembic_upgrade()
        yield
    finally:
        from app.database import engine

        await engine.dispose()
        conn = await asyncpg.connect(dsn=admin_dsn)
        try:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{_TEST_SCHEMA}" CASCADE')
        finally:
            await conn.close()


def _run_alembic_upgrade() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(_REPO_ROOT),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "alembic upgrade head failed for the integration test schema "
            f"{_TEST_SCHEMA!r}:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


# ── 3. ASGI app + httpx client (real HTTP semantics, in-memory transport) ──

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def fastapi_app(_integration_database: None):
    from app.main import app as application

    return application


def _fake_ip_for(key: str) -> str:
    """Deterministic-but-unique fake source IP per test, so slowapi's
    IP-keyed rate limiter never leaks state across tests."""
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return f"10.{digest[0]}.{digest[1]}.{digest[2]}"


@pytest_asyncio.fixture(loop_scope="session")
async def client(request: pytest.FixtureRequest, fastapi_app) -> AsyncIterator["httpx.AsyncClient"]:
    import httpx

    ip = _fake_ip_for(request.node.nodeid)
    transport = httpx.ASGITransport(app=fastapi_app, client=(ip, 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver/api/v1") as ac:
        yield ac


# ── 4. Tenant / user seeding ────────────────────────────────────────────────

@dataclass(slots=True)
class SeededTenant:
    tenant_id: uuid.UUID
    slug: str
    owner_id: uuid.UUID
    owner_email: str
    owner_password: str


@pytest_asyncio.fixture(loop_scope="session")
async def db_sessionmaker(_integration_database: None):
    """
    The `AsyncSessionLocal` sessionmaker itself — NOT a live session. Tests
    that need to seed rows the HTTP API can't create directly (e.g. Contact —
    there's no POST /contacts route) call `async with db_sessionmaker() as
    session:` themselves, inside their own test body, and open/commit/close
    it in one continuous coroutine.

    This is deliberately NOT a generator fixture that opens a session and
    `yield`s it across the fixture's setup/teardown boundary (i.e. NOT
    `async with AsyncSessionLocal() as session: yield session`). Tried that
    first — pytest-asyncio bridges each fixture phase (setup, teardown) via
    its own separate `event_loop.run_until_complete(...)` call, and handing a
    *live* SQLAlchemy AsyncSession across that boundary deadlocked the
    underlying asyncpg connection's greenlet bridge: every test using it hung
    forever (confirmed by bisecting test-by-test with a hard timeout — every
    test that touched that fixture hung, every test that didn't passed).
    Keeping a session's whole lifecycle inside ONE uninterrupted coroutine —
    same pattern `_seed_tenant_with_owner` below already uses successfully —
    avoids that class of bug entirely.
    """
    from app.database import AsyncSessionLocal

    return AsyncSessionLocal


async def _seed_tenant_with_owner(*, name_prefix: str = "Clinic") -> SeededTenant:
    from app.core.security import hash_password
    from app.database import AsyncSessionLocal
    from app.models.tenant import Tenant, TenantPlan
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:10]
    password = "Sup3r-Secret-Pw!"

    async with AsyncSessionLocal() as session:
        tenant = Tenant(
            name=f"{name_prefix} {suffix}",
            slug=f"clinic-{suffix}",
            email=f"clinic-{suffix}@example.com",
            plan=TenantPlan.FREE,
            is_active=True,
        )
        session.add(tenant)
        await session.flush()

        owner = User(
            tenant_id=tenant.id,
            full_name="Owner Test",
            email=f"owner-{suffix}@example.com",
            hashed_password=hash_password(password),
            role=UserRole.OWNER,
            is_active=True,
        )
        session.add(owner)
        await session.commit()

        return SeededTenant(
            tenant_id=tenant.id,
            slug=tenant.slug,
            owner_id=owner.id,
            owner_email=owner.email,
            owner_password=password,
        )


@pytest_asyncio.fixture(loop_scope="session")
async def tenant_a(_integration_database: None) -> SeededTenant:
    return await _seed_tenant_with_owner(name_prefix="Tenant A Clinic")


@pytest_asyncio.fixture(loop_scope="session")
async def tenant_b(_integration_database: None) -> SeededTenant:
    return await _seed_tenant_with_owner(name_prefix="Tenant B Clinic")


async def login(client, tenant: SeededTenant) -> dict:
    """POST /auth/login for the seeded tenant owner; returns the raw token pair JSON."""
    resp = await client.post(
        "/auth/login",
        json={"email": tenant.owner_email, "password": tenant.owner_password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def auth_headers(client, tenant: SeededTenant) -> dict[str, str]:
    """Login + build ready-to-use headers (Authorization + X-Tenant-ID)."""
    tokens = await login(client, tenant)
    return {
        "Authorization": f"Bearer {tokens['access_token']}",
        "X-Tenant-ID": str(tenant.tenant_id),
    }


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers_a(client, tenant_a: SeededTenant) -> dict[str, str]:
    return await auth_headers(client, tenant_a)


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers_b(client, tenant_b: SeededTenant) -> dict[str, str]:
    return await auth_headers(client, tenant_b)
