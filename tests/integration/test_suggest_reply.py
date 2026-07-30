"""
Integration test for the staff "Sugerir resposta" copilot endpoint
(POST /api/v1/contacts/{id}/suggest-reply) through the real FastAPI app +
Postgres. Only the network call to Gemini is faked (SequencedFakeClient
injected at app.services.ai._get_client), so the real route, auth/tenant
scoping, DB reads, and the read-only generation path all run.

The load-bearing assertion is that a suggestion has ZERO side effects: no
outbound message is persisted and the contact's ai_paused stays untouched —
the draft only comes back in the response body for the human to edit/send.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from tests.integration.conftest import SeededTenant
from tests.support.fake_gemini import SequencedFakeClient, fake_text


async def _seed_contact_with_inbound(db_sessionmaker, tenant_id) -> uuid.UUID:
    from app.models.contact import Contact
    from app.models.message import Message, MessageChannel, MessageDirection

    async with db_sessionmaker() as session:
        contact = Contact(
            tenant_id=tenant_id,
            full_name="Paciente Sugestão",
            phone=f"+55119{uuid.uuid4().int % 100000000:08d}",
            ai_paused=False,
        )
        session.add(contact)
        await session.flush()
        session.add(Message(
            tenant_id=tenant_id,
            contact_id=contact.id,
            direction=MessageDirection.INBOUND,
            channel=MessageChannel.WHATSAPP,
            content="Oi, queria saber se tem horário pra limpeza de pele quinta",
        ))
        await session.commit()
        return contact.id


async def _count_messages(db_sessionmaker, tenant_id, contact_id) -> int:
    from app.models.message import Message

    async with db_sessionmaker() as session:
        return await session.scalar(
            select(func.count(Message.id)).where(
                Message.tenant_id == tenant_id, Message.contact_id == contact_id
            )
        )


async def _contact_paused(db_sessionmaker, tenant_id, contact_id) -> bool:
    from app.models.contact import Contact

    async with db_sessionmaker() as session:
        contact = await session.scalar(
            select(Contact).where(Contact.tenant_id == tenant_id, Contact.id == contact_id)
        )
        return bool(contact and contact.ai_paused)


async def test_suggest_reply_returns_draft_without_side_effects(
    client, db_sessionmaker, tenant_a: SeededTenant, auth_headers_a, monkeypatch
):
    contact_id = await _seed_contact_with_inbound(db_sessionmaker, tenant_a.tenant_id)

    import app.services.ai as ai_module

    draft = "Oi! Consigo sim, tenho quinta às 14h ou 16h, qual fica melhor pra você?"
    fake = SequencedFakeClient([fake_text(draft)])
    monkeypatch.setattr(ai_module, "_get_client", lambda: fake)

    resp = await client.post(
        f"/contacts/{contact_id}/suggest-reply", headers=auth_headers_a
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["suggestion"] == draft

    # Zero side effects: no outbound message was persisted (still just the one
    # seeded inbound), and the contact was NOT paused by asking for a draft.
    assert await _count_messages(db_sessionmaker, tenant_a.tenant_id, contact_id) == 1
    assert await _contact_paused(db_sessionmaker, tenant_a.tenant_id, contact_id) is False


async def test_suggest_reply_unknown_contact_is_404(
    client, tenant_a: SeededTenant, auth_headers_a
):
    resp = await client.post(
        f"/contacts/{uuid.uuid4()}/suggest-reply", headers=auth_headers_a
    )
    assert resp.status_code == 404, resp.text
