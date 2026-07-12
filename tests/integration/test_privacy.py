"""
Integration tests for the LGPD contact export/anonymize endpoints:
  GET  /api/v1/contacts/{id}/export
  POST /api/v1/contacts/{id}/anonymize
(app/api/v1/routes/privacy.py, app/services/privacy.py)

These hit a real Postgres via the real FastAPI app (ASGI transport, no
network socket) — no mocking of the DB layer.

Why this file is fully self-contained (no shared tests/integration/conftest.py):
  At the time this was written, this worktree did not have a
  tests/integration/ directory at all (it's expected from a parallel Wave 1
  lane that hadn't been merged into this branch yet). Rather than invent a
  conftest.py at a path another team is actively building — which would be
  a near-guaranteed merge conflict — this test manages its own schema,
  engine bootstrap, and fixtures inline. If a real tests/integration/conftest.py
  lands later with reusable fixtures, this file can be slimmed down to use
  them; nothing here depends on conftest.py *not* existing.

Isolation strategy:
  Tests run against a **dedicated Postgres schema**, not "public" — so they
  never touch/interfere with whatever the shared dev Postgres's "public"
  schema currently holds (other worktrees/lanes may be migrating it
  concurrently). Set DATABASE_SCHEMA in the environment *before* invoking
  pytest (app/database.py builds its engine — including the search_path —
  at import time, so setting it inside this module would be too late):

      # Windows (PowerShell)
      $env:DATABASE_SCHEMA = "privacy_wave2_test"
      venv\\Scripts\\python -m pytest tests/integration/test_privacy.py -q

      # Windows (Git Bash) / bash
      DATABASE_SCHEMA=privacy_wave2_test venv/Scripts/python -m pytest tests/integration/test_privacy.py -q

  If DATABASE_SCHEMA is left at its default ("public"), every test in this
  module is skipped (not failed) — this keeps `pytest tests/ -q` green even
  though this file lives under tests/ and gets collected by that command.
"""

import datetime
import uuid

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import settings
from app.core.security import create_access_token, hash_password
from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.message import Message, MessageChannel, MessageDirection
from app.models.tenant import Tenant
from app.models.user import User, UserRole

SCHEMA = settings.DATABASE_SCHEMA


# ── Schema bootstrap ─────────────────────────────────────────────────────────

async def _create_schema_and_tables() -> None:
    dsn = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')
    finally:
        await conn.close()
    # create_all is a no-op for tables that already exist (e.g. if `alembic
    # upgrade head` was already run against this schema) and a safety net
    # otherwise, so this file works standalone.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


_schema_ready = False


@pytest.fixture(autouse=True)
async def _setup_schema():
    # Function-scoped (not module-scoped) to match this project's default
    # asyncio fixture loop scope ("function", see pytest.ini) and avoid a
    # pytest-asyncio ScopeMismatch. The actual schema/table creation is
    # memoized so it only runs once per test session despite the fixture
    # itself running per-test.
    if SCHEMA == "public":
        pytest.skip(
            "DATABASE_SCHEMA is 'public' (default) — refusing to run against the "
            "shared dev schema. Set DATABASE_SCHEMA to an isolated schema name to "
            "run this suite (see module docstring)."
        )
    # Each test function gets its own asyncio event loop (function-scoped),
    # but app.database.engine's asyncpg pool is a module-level singleton
    # created once at import time. Pooled connections are bound to whichever
    # loop was running when they were opened, so reusing them from a new
    # test's loop blows up ("Event loop is closed"). Disposing at the start
    # of every test forces fresh connections on the current loop.
    await engine.dispose()
    global _schema_ready
    if not _schema_ready:
        await _create_schema_and_tables()
        _schema_ready = True
    yield


# ── Fixtures / helpers ───────────────────────────────────────────────────────

async def _make_tenant(session, slug: str) -> Tenant:
    tenant = Tenant(name=f"Clinic {slug}", slug=slug, email=f"{slug}@example.com")
    session.add(tenant)
    await session.flush()
    return tenant


async def _make_user(session, tenant: Tenant, role: UserRole) -> User:
    user = User(
        tenant_id=tenant.id,
        full_name=f"User {role.value}",
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("x"),
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_contact(session, tenant: Tenant, **overrides) -> Contact:
    defaults = dict(
        full_name="Paciente Teste",
        email="paciente@example.com",
        phone=f"+55119{uuid.uuid4().int % 100000000:08d}",
        date_of_birth=datetime.date(1990, 1, 1),
        address="Rua Teste, 123",
        medical_notes={"alergias": "dipirona"},
        whatsapp_name="Pac Teste",
    )
    defaults.update(overrides)
    contact = Contact(tenant_id=tenant.id, **defaults)
    session.add(contact)
    await session.flush()
    return contact


def _auth_headers(tenant: Tenant, user: User) -> dict:
    token = create_access_token(subject=user.id, tenant_id=tenant.id)
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": str(tenant.id)}


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Export ────────────────────────────────────────────────────────────────────

async def test_export_returns_full_structured_data(client):
    async with AsyncSessionLocal() as session:
        tenant = await _make_tenant(session, f"export-{uuid.uuid4().hex[:8]}")
        owner = await _make_user(session, tenant, UserRole.OWNER)
        contact = await _make_contact(session, tenant)
        session.add(Message(
            tenant_id=tenant.id, contact_id=contact.id,
            direction=MessageDirection.INBOUND, channel=MessageChannel.WHATSAPP,
            content="Oi, quero agendar uma consulta",
        ))
        session.add(Message(
            tenant_id=tenant.id, contact_id=contact.id,
            direction=MessageDirection.OUTBOUND, channel=MessageChannel.WHATSAPP,
            content="Claro! Qual dia prefere?", media_url="data:audio/ogg;base64,AAAA",
            media_type="audio", media_mime_type="audio/ogg", media_size_bytes=1234,
        ))
        session.add(Appointment(
            tenant_id=tenant.id, contact_id=contact.id,
            scheduled_at=datetime.datetime.now(datetime.timezone.utc),
            status=AppointmentStatus.SCHEDULED,
        ))
        await session.commit()
        contact_id = contact.id

    resp = await client.get(
        f"/api/v1/contacts/{contact_id}/export", headers=_auth_headers(tenant, owner)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["profile"]["full_name"] == "Paciente Teste"
    assert data["profile"]["medical_notes"] == {"alergias": "dipirona"}
    assert data["profile"]["address"] == "Rua Teste, 123"

    assert data["meta"]["message_count"] == 2
    assert len(data["messages"]) == 2
    contents = {m["content"] for m in data["messages"]}
    assert "Oi, quero agendar uma consulta" in contents
    # raw media data URIs are never included in the export (size guard) —
    # only metadata about the media is.
    media_msg = next(m for m in data["messages"] if m["has_media"])
    assert "media_url" not in media_msg
    assert media_msg["media_type"] == "audio"
    assert media_msg["media_size_bytes"] == 1234

    assert data["meta"]["appointment_count"] == 1
    assert len(data["appointments"]) == 1
    assert data["appointments"][0]["status"] == "scheduled"

    assert data["crm"]["crm_stage"] == "new_lead"
    assert data["meta"]["exported_by_user_id"] == str(owner.id)


async def test_export_is_tenant_scoped(client):
    async with AsyncSessionLocal() as session:
        tenant_a = await _make_tenant(session, f"tena-{uuid.uuid4().hex[:8]}")
        tenant_b = await _make_tenant(session, f"tenb-{uuid.uuid4().hex[:8]}")
        owner_b = await _make_user(session, tenant_b, UserRole.OWNER)
        contact_a = await _make_contact(session, tenant_a, full_name="Paciente do Tenant A")
        await session.commit()
        contact_a_id = contact_a.id

    # Tenant B's owner, authenticated as tenant B, tries to export tenant A's contact.
    resp = await client.get(
        f"/api/v1/contacts/{contact_a_id}/export", headers=_auth_headers(tenant_b, owner_b)
    )
    assert resp.status_code == 404


async def test_export_forbidden_for_professional_role(client):
    async with AsyncSessionLocal() as session:
        tenant = await _make_tenant(session, f"prof-{uuid.uuid4().hex[:8]}")
        professional = await _make_user(session, tenant, UserRole.PROFESSIONAL)
        contact = await _make_contact(session, tenant)
        await session.commit()
        contact_id = contact.id

    resp = await client.get(
        f"/api/v1/contacts/{contact_id}/export", headers=_auth_headers(tenant, professional)
    )
    assert resp.status_code == 403


# ── Anonymize ────────────────────────────────────────────────────────────────

async def test_anonymize_scrubs_pii_and_messages(client):
    async with AsyncSessionLocal() as session:
        tenant = await _make_tenant(session, f"anon-{uuid.uuid4().hex[:8]}")
        admin = await _make_user(session, tenant, UserRole.ADMIN)
        contact = await _make_contact(session, tenant, full_name="Fulano de Tal")
        original_phone = contact.phone
        msg = Message(
            tenant_id=tenant.id, contact_id=contact.id,
            direction=MessageDirection.INBOUND, channel=MessageChannel.WHATSAPP,
            content="Meu CPF é 123.456.789-00", whatsapp_message_id="wamid.abc123",
        )
        session.add(msg)
        await session.commit()
        contact_id = contact.id
        msg_id = msg.id

    resp = await client.post(
        f"/api/v1/contacts/{contact_id}/anonymize", headers=_auth_headers(tenant, admin)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["messages_scrubbed"] == 1
    assert body["anonymized_by_user_id"] == str(admin.id)

    async with AsyncSessionLocal() as session:
        contact = (await session.execute(select(Contact).where(Contact.id == contact_id))).scalar_one()
        assert contact.full_name == "Paciente anonimizado"
        assert contact.email is None
        assert contact.phone is None
        assert contact.date_of_birth is None
        assert contact.address is None
        assert contact.medical_notes is None
        assert contact.whatsapp_name is None
        assert contact.anonymized_at is not None
        assert contact.anonymized_by_user_id == admin.id

        message = (await session.execute(select(Message).where(Message.id == msg_id))).scalar_one()
        assert message.content == ""
        assert message.whatsapp_message_id is None
        # direction/channel/created_at are preserved for aggregate reporting
        assert message.direction == MessageDirection.INBOUND
        assert message.channel == MessageChannel.WHATSAPP

        # phone cleared => a new inbound message from the same number will no
        # longer match this contact (webhooks.py::_find_or_create_contact
        # looks up by (tenant_id, phone) — this is the "forget me" behavior).
        by_old_phone = await session.execute(
            select(Contact).where(Contact.tenant_id == tenant.id, Contact.phone == original_phone)
        )
        assert by_old_phone.scalar_one_or_none() is None


async def test_anonymize_is_idempotent(client):
    async with AsyncSessionLocal() as session:
        tenant = await _make_tenant(session, f"idem-{uuid.uuid4().hex[:8]}")
        admin = await _make_user(session, tenant, UserRole.ADMIN)
        contact = await _make_contact(session, tenant)
        await session.commit()
        contact_id = contact.id

    resp1 = await client.post(
        f"/api/v1/contacts/{contact_id}/anonymize", headers=_auth_headers(tenant, admin)
    )
    assert resp1.status_code == 200
    first_anonymized_at = resp1.json()["anonymized_at"]

    # Second call must not error and must remain scrubbed.
    resp2 = await client.post(
        f"/api/v1/contacts/{contact_id}/anonymize", headers=_auth_headers(tenant, admin)
    )
    assert resp2.status_code == 200, resp2.text
    body2 = resp2.json()
    assert body2["detail"].startswith("Contact was already anonymized")

    async with AsyncSessionLocal() as session:
        contact = (await session.execute(select(Contact).where(Contact.id == contact_id))).scalar_one()
        assert contact.full_name == "Paciente anonimizado"
        assert contact.email is None
        assert contact.anonymized_at is not None


async def test_anonymize_forbidden_for_receptionist(client):
    async with AsyncSessionLocal() as session:
        tenant = await _make_tenant(session, f"recep-{uuid.uuid4().hex[:8]}")
        receptionist = await _make_user(session, tenant, UserRole.RECEPTIONIST)
        contact = await _make_contact(session, tenant)
        await session.commit()
        contact_id = contact.id

    resp = await client.post(
        f"/api/v1/contacts/{contact_id}/anonymize", headers=_auth_headers(tenant, receptionist)
    )
    assert resp.status_code == 403

    async with AsyncSessionLocal() as session:
        contact = (await session.execute(select(Contact).where(Contact.id == contact_id))).scalar_one()
        # Untouched — the forbidden request must not have mutated anything.
        assert contact.anonymized_at is None
        assert contact.full_name == "Paciente Teste"


async def test_anonymize_is_tenant_scoped(client):
    async with AsyncSessionLocal() as session:
        tenant_a = await _make_tenant(session, f"tena2-{uuid.uuid4().hex[:8]}")
        tenant_b = await _make_tenant(session, f"tenb2-{uuid.uuid4().hex[:8]}")
        admin_b = await _make_user(session, tenant_b, UserRole.ADMIN)
        contact_a = await _make_contact(session, tenant_a, full_name="Paciente do Tenant A")
        await session.commit()
        contact_a_id = contact_a.id

    resp = await client.post(
        f"/api/v1/contacts/{contact_a_id}/anonymize", headers=_auth_headers(tenant_b, admin_b)
    )
    assert resp.status_code == 404

    async with AsyncSessionLocal() as session:
        contact = (await session.execute(select(Contact).where(Contact.id == contact_a_id))).scalar_one()
        assert contact.anonymized_at is None
        assert contact.full_name == "Paciente do Tenant A"
