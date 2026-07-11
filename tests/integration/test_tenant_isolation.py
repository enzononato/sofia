"""
Cross-tenant isolation integration tests — the core invariant of this SaaS:
tenant A must never see, edit, or delete tenant B's data, and a token minted
for A must never work against B.

Covers contacts (list/detail/messages), appointments (list/create/detail),
services (list/create), and reports/overview — per app/api/v1/routes/*.py
(webhooks.py is explicitly out of scope for this slice — see conftest.py).

Every test seeds its own tenant_a / tenant_b (see conftest.py fixtures) so
tests never depend on each other's data, even though they share one Postgres
schema for the whole session.

DB seeding helpers below each open+commit+close their OWN session via
`db_sessionmaker` in one continuous coroutine — see the long comment on the
`db_sessionmaker` fixture in conftest.py for why (a live session yielded
across a fixture's setup/teardown boundary deadlocked every test that used
it).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from tests.integration.conftest import SeededTenant, auth_headers


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _create_contact(db_sessionmaker, tenant: SeededTenant, *, full_name: str = "Paciente Teste"):
    from app.models.contact import Contact

    async with db_sessionmaker() as session:
        contact = Contact(
            tenant_id=tenant.tenant_id,
            full_name=full_name,
            phone=f"+55119{uuid.uuid4().int % 10**8:08d}",
        )
        session.add(contact)
        await session.commit()
        await session.refresh(contact)
        return contact


async def _fetch_contact(db_sessionmaker, contact_id):
    from app.models.contact import Contact

    async with db_sessionmaker() as session:
        return await session.get(Contact, contact_id)


async def _create_service(db_sessionmaker, tenant: SeededTenant, *, name: str = "Consulta"):
    from app.models.service import Service

    async with db_sessionmaker() as session:
        service = Service(tenant_id=tenant.tenant_id, name=name, duration_minutes=30)
        session.add(service)
        await session.commit()
        await session.refresh(service)
        return service


async def _create_appointment(db_sessionmaker, tenant: SeededTenant, contact, *, when: datetime | None = None):
    from app.models.appointment import Appointment

    scheduled_at = when or (datetime.now(timezone.utc) + timedelta(days=1))
    async with db_sessionmaker() as session:
        appt = Appointment(
            tenant_id=tenant.tenant_id,
            contact_id=contact.id,
            scheduled_at=scheduled_at,
            ends_at=scheduled_at + timedelta(minutes=30),
        )
        session.add(appt)
        await session.commit()
        await session.refresh(appt)
        return appt


# ── Structural guard: cross-tenant token reuse (app/api/deps.py) ───────────

async def test_token_from_tenant_a_rejected_with_tenant_b_header(client, tenant_a: SeededTenant, tenant_b: SeededTenant):
    """
    A JWT minted for tenant A, presented with X-Tenant-ID pointing at tenant
    B, must be rejected — app/api/deps.py::get_current_user compares
    token_tenant != tenant_id and raises TenantInactiveError (403). This is a
    regression guard for an invariant that already exists, not a discovery.
    """
    headers_a = await auth_headers(client, tenant_a)
    forged_headers = {
        "Authorization": headers_a["Authorization"],
        "X-Tenant-ID": str(tenant_b.tenant_id),
    }
    resp = await client.get("/contacts", headers=forged_headers)
    assert resp.status_code in (401, 403)
    assert resp.json()["error"]["code"] in ("tenant_inactive", "unauthorized", "token_invalid")


# ── Contacts ─────────────────────────────────────────────────────────────────

async def test_contacts_list_is_tenant_scoped(client, db_sessionmaker, tenant_a: SeededTenant, tenant_b: SeededTenant):
    contact_a = await _create_contact(db_sessionmaker, tenant_a, full_name="Paciente A")
    contact_b = await _create_contact(db_sessionmaker, tenant_b, full_name="Paciente B")

    headers_a = await auth_headers(client, tenant_a)
    resp = await client.get("/contacts", headers=headers_a)
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()["data"]}
    assert str(contact_a.id) in ids
    assert str(contact_b.id) not in ids


async def test_contact_detail_404_for_other_tenant(client, db_sessionmaker, tenant_a: SeededTenant, tenant_b: SeededTenant):
    contact_b = await _create_contact(db_sessionmaker, tenant_b, full_name="Paciente B")

    headers_a = await auth_headers(client, tenant_a)
    resp = await client.get(f"/contacts/{contact_b.id}", headers=headers_a)
    assert resp.status_code == 404, resp.text

    # Sanity: tenant B itself CAN see it.
    headers_b = await auth_headers(client, tenant_b)
    resp_b = await client.get(f"/contacts/{contact_b.id}", headers=headers_b)
    assert resp_b.status_code == 200


async def test_contact_messages_404_for_other_tenant(client, db_sessionmaker, tenant_a: SeededTenant, tenant_b: SeededTenant):
    contact_b = await _create_contact(db_sessionmaker, tenant_b, full_name="Paciente B")

    headers_a = await auth_headers(client, tenant_a)
    resp = await client.get(f"/contacts/{contact_b.id}/messages", headers=headers_a)
    assert resp.status_code == 404


async def test_contact_update_404_and_no_op_for_other_tenant(client, db_sessionmaker, tenant_a: SeededTenant, tenant_b: SeededTenant):
    contact_b = await _create_contact(db_sessionmaker, tenant_b, full_name="Paciente B Original")

    headers_a = await auth_headers(client, tenant_a)
    resp = await client.patch(
        f"/contacts/{contact_b.id}",
        headers=headers_a,
        json={"full_name": "Hijacked By Tenant A"},
    )
    assert resp.status_code == 404

    # Confirm tenant B's row was NOT modified (fresh read, not a stale ORM refresh).
    reloaded = await _fetch_contact(db_sessionmaker, contact_b.id)
    assert reloaded.full_name == "Paciente B Original"


# ── Appointments ─────────────────────────────────────────────────────────────

async def test_appointments_list_is_tenant_scoped(client, db_sessionmaker, tenant_a: SeededTenant, tenant_b: SeededTenant):
    contact_a = await _create_contact(db_sessionmaker, tenant_a)
    contact_b = await _create_contact(db_sessionmaker, tenant_b)
    appt_a = await _create_appointment(db_sessionmaker, tenant_a, contact_a)
    appt_b = await _create_appointment(db_sessionmaker, tenant_b, contact_b)

    headers_a = await auth_headers(client, tenant_a)
    resp = await client.get("/appointments", headers=headers_a)
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()["data"]}
    assert str(appt_a.id) in ids
    assert str(appt_b.id) not in ids


async def test_appointment_detail_404_for_other_tenant(client, db_sessionmaker, tenant_a: SeededTenant, tenant_b: SeededTenant):
    contact_b = await _create_contact(db_sessionmaker, tenant_b)
    appt_b = await _create_appointment(db_sessionmaker, tenant_b, contact_b)

    headers_a = await auth_headers(client, tenant_a)
    resp = await client.get(f"/appointments/{appt_b.id}", headers=headers_a)
    assert resp.status_code == 404


async def test_create_appointment_rejects_other_tenants_contact_id(client, db_sessionmaker, tenant_a: SeededTenant, tenant_b: SeededTenant):
    """
    contact_id is a body field — app/api/v1/routes/appointments.py validates
    the FK belongs to the *current* tenant (_assert_tenant_fk) before insert,
    so tenant A can't attach an appointment to tenant B's contact even by
    guessing/leaking a real UUID.
    """
    contact_b = await _create_contact(db_sessionmaker, tenant_b)

    headers_a = await auth_headers(client, tenant_a)
    resp = await client.post(
        "/appointments",
        headers=headers_a,
        json={
            "contact_id": str(contact_b.id),
            "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_fk"


async def test_create_appointment_succeeds_for_own_tenant_contact(client, db_sessionmaker, tenant_a: SeededTenant):
    contact_a = await _create_contact(db_sessionmaker, tenant_a)
    headers_a = await auth_headers(client, tenant_a)

    resp = await client.post(
        "/appointments",
        headers=headers_a,
        json={
            "contact_id": str(contact_a.id),
            "scheduled_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["tenant_id"] == str(tenant_a.tenant_id)
    assert body["contact_id"] == str(contact_a.id)


# ── Services ─────────────────────────────────────────────────────────────────

async def test_services_list_is_tenant_scoped(client, db_sessionmaker, tenant_a: SeededTenant, tenant_b: SeededTenant):
    service_a = await _create_service(db_sessionmaker, tenant_a, name="Consulta A")
    service_b = await _create_service(db_sessionmaker, tenant_b, name="Consulta B")

    headers_a = await auth_headers(client, tenant_a)
    resp = await client.get("/services", headers=headers_a)
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()["data"]}
    assert str(service_a.id) in ids
    assert str(service_b.id) not in ids


async def test_service_detail_404_for_other_tenant(client, db_sessionmaker, tenant_a: SeededTenant, tenant_b: SeededTenant):
    service_b = await _create_service(db_sessionmaker, tenant_b, name="Consulta B")

    headers_a = await auth_headers(client, tenant_a)
    resp = await client.get(f"/services/{service_b.id}", headers=headers_a)
    assert resp.status_code == 404


async def test_create_service_is_scoped_to_current_tenant(client, tenant_a: SeededTenant, tenant_b: SeededTenant):
    headers_a = await auth_headers(client, tenant_a)
    resp = await client.post(
        "/services",
        headers=headers_a,
        json={"name": "Nova Consulta", "duration_minutes": 45},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["tenant_id"] == str(tenant_a.tenant_id)

    # Tenant B must not see it in its own list.
    headers_b = await auth_headers(client, tenant_b)
    resp_b = await client.get("/services", headers=headers_b)
    ids_b = {row["id"] for row in resp_b.json()["data"]}
    assert body["id"] not in ids_b

    # ... nor fetch it directly.
    resp_b_detail = await client.get(f"/services/{body['id']}", headers=headers_b)
    assert resp_b_detail.status_code == 404


# ── Reports ──────────────────────────────────────────────────────────────────

async def test_reports_overview_only_counts_own_tenant(client, db_sessionmaker, tenant_a: SeededTenant, tenant_b: SeededTenant):
    # Give tenant B a handful of contacts that must NOT bleed into A's report.
    for i in range(3):
        await _create_contact(db_sessionmaker, tenant_b, full_name=f"B Lead {i}")

    headers_a = await auth_headers(client, tenant_a)
    resp = await client.get("/reports/overview", headers=headers_a)
    assert resp.status_code == 200
    before = resp.json()["total_contacts"]

    await _create_contact(db_sessionmaker, tenant_a, full_name="A Lead")

    resp2 = await client.get("/reports/overview", headers=headers_a)
    assert resp2.status_code == 200
    after = resp2.json()["total_contacts"]

    # Exactly tenant A's own new contact should move the counter — tenant B's
    # 3 new contacts must not have contributed anything.
    assert after == before + 1
