"""
`Contact.human_takeover_until` must be VISIBLE to the panel and NOT settable by it.

Why this exists: a real production incident. Staff replied to a patient straight
from their own phone, which correctly silenced Sofia for 60 minutes
(webhook_human_takeover_active in the logs), but the Inbox header still read
"Secretária IA: Ativa" because the field never left the API. From the outside it
looked like Sofia had simply stopped answering that contact, and the only way to
find out was reading server logs.

Two properties are pinned here:
  1. GET returns the field, so the UI can explain the silence;
  2. PATCH cannot set or clear it — it's a server-owned, self-expiring window
     (ContactUpdate doesn't declare it, so FastAPI drops it).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from tests.integration.conftest import SeededTenant


async def _seed_contact(db_sessionmaker, tenant_id, *, takeover_until=None) -> uuid.UUID:
    from app.models.contact import Contact

    async with db_sessionmaker() as session:
        contact = Contact(
            tenant_id=tenant_id,
            full_name="Paciente Takeover",
            phone=f"+55119{uuid.uuid4().int % 100000000:08d}",
            human_takeover_until=takeover_until,
        )
        session.add(contact)
        await session.commit()
        return contact.id


async def test_get_contact_exposes_the_takeover_window(
    client, db_sessionmaker, tenant_a: SeededTenant, auth_headers_a
):
    until = datetime.now(timezone.utc) + timedelta(minutes=45)
    contact_id = await _seed_contact(db_sessionmaker, tenant_a.tenant_id, takeover_until=until)

    resp = await client.get(f"/contacts/{contact_id}", headers=auth_headers_a)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "human_takeover_until" in body, (
        "the panel needs this field to explain why Sofia is silent"
    )
    assert body["human_takeover_until"] is not None
    # ai_paused is a different mechanism and must remain untouched by it.
    assert body["ai_paused"] is False


async def test_field_is_null_when_no_takeover_is_active(
    client, db_sessionmaker, tenant_a: SeededTenant, auth_headers_a
):
    contact_id = await _seed_contact(db_sessionmaker, tenant_a.tenant_id)

    resp = await client.get(f"/contacts/{contact_id}", headers=auth_headers_a)
    assert resp.status_code == 200, resp.text
    assert resp.json()["human_takeover_until"] is None


async def test_patch_cannot_forge_a_takeover_window(
    client, db_sessionmaker, tenant_a: SeededTenant, auth_headers_a
):
    from app.models.contact import Contact

    contact_id = await _seed_contact(db_sessionmaker, tenant_a.tenant_id)
    forged = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    resp = await client.patch(
        f"/contacts/{contact_id}",
        headers=auth_headers_a,
        json={"full_name": "Nome Novo", "human_takeover_until": forged},
    )
    # The legitimate part of the payload still applies...
    assert resp.status_code == 200, resp.text
    assert resp.json()["full_name"] == "Nome Novo"

    # ...but the server-owned window was ignored, in the response and in the DB.
    assert resp.json()["human_takeover_until"] is None
    async with db_sessionmaker() as session:
        contact = await session.scalar(select(Contact).where(Contact.id == contact_id))
    assert contact.human_takeover_until is None


async def test_reactivating_sofia_clears_the_takeover_window(
    client, db_sessionmaker, tenant_a: SeededTenant, auth_headers_a
):
    """The Inbox toggle is one switch to staff: turning Sofia back ON must make
    her answer NOW, not in up to 60 minutes."""
    from app.models.contact import Contact

    until = datetime.now(timezone.utc) + timedelta(minutes=45)
    contact_id = await _seed_contact(db_sessionmaker, tenant_a.tenant_id, takeover_until=until)

    resp = await client.patch(
        f"/contacts/{contact_id}", headers=auth_headers_a, json={"ai_paused": False}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["human_takeover_until"] is None
    assert resp.json()["ai_paused"] is False

    async with db_sessionmaker() as session:
        contact = await session.scalar(select(Contact).where(Contact.id == contact_id))
    assert contact.human_takeover_until is None
    assert contact.ai_paused is False


async def test_pausing_sofia_does_not_touch_the_takeover_window(
    client, db_sessionmaker, tenant_a: SeededTenant, auth_headers_a
):
    """Only the reactivation path clears it — pausing is a different intent."""
    from app.models.contact import Contact

    until = datetime.now(timezone.utc) + timedelta(minutes=45)
    contact_id = await _seed_contact(db_sessionmaker, tenant_a.tenant_id, takeover_until=until)

    resp = await client.patch(
        f"/contacts/{contact_id}", headers=auth_headers_a, json={"ai_paused": True}
    )
    assert resp.status_code == 200, resp.text

    async with db_sessionmaker() as session:
        contact = await session.scalar(select(Contact).where(Contact.id == contact_id))
    assert contact.human_takeover_until is not None


async def test_unrelated_patch_does_not_clear_the_takeover_window(
    client, db_sessionmaker, tenant_a: SeededTenant, auth_headers_a
):
    """Renaming a contact must not silently wake Sofia up mid-takeover."""
    from app.models.contact import Contact

    until = datetime.now(timezone.utc) + timedelta(minutes=45)
    contact_id = await _seed_contact(db_sessionmaker, tenant_a.tenant_id, takeover_until=until)

    resp = await client.patch(
        f"/contacts/{contact_id}", headers=auth_headers_a, json={"full_name": "Outro Nome"}
    )
    assert resp.status_code == 200, resp.text

    async with db_sessionmaker() as session:
        contact = await session.scalar(select(Contact).where(Contact.id == contact_id))
    assert contact.human_takeover_until is not None
