"""
One end-to-end test proving the Wave 3 multi-agent path (AI_MULTI_AGENT_ENABLED
/ tenant.ai_config["multi_agent_enabled"]) survives the REAL webhook pipeline
unmodified: batching dispatch, [[BREAK]] message splitting, WhatsApp sends,
read receipts, and the handoff email alert all still fire correctly when the
reply was produced by Router -> specialist(s) instead of the single legacy
agent.

Unlike every test in test_webhooks.py, this file does NOT monkeypatch
app.services.ai.generate_reply wholesale — that would bypass the very code
this Wave adds. Instead it injects a SequencedFakeClient at the exact point
app/services/agents/orchestrator.py resolves its Gemini client
(orchestrator._get_client), so a real multi-hop reply flows through the real
orchestrator, the real humanizer, the real webhook dispatch — only the actual
network call to Gemini is faked.

Reuses tests/integration/conftest.py's `client`/`db_sessionmaker`/`tenant_a`
fixtures and test_webhooks.py's payload/polling helpers (imported, not
duplicated).
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from tests.integration.conftest import SeededTenant
from tests.integration.test_webhooks import (
    _configure_whatsapp,
    _get_messages,
    _message_payload,
    _random_phone,
    _wait_until,
    _wait_until_async,
    _webhook_path,
)
from tests.support.fake_gemini import SequencedFakeClient, fake_function_call, fake_text


async def _enable_multi_agent(db_sessionmaker, tenant_id) -> None:
    from app.models.tenant import Tenant

    async with db_sessionmaker() as session:
        tenant = await session.get(Tenant, tenant_id)
        tenant.ai_config = {**(tenant.ai_config or {}), "multi_agent_enabled": True}
        session.add(tenant)
        await session.commit()


@pytest.fixture(autouse=True)
def _fast_humanization(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "MESSAGE_BATCHING_ENABLED", False)
    monkeypatch.setattr(settings, "TYPING_SIMULATION_ENABLED", False)


@pytest.fixture(autouse=True)
def _mock_whatsapp_io(monkeypatch):
    import app.services.whatsapp as wa_module
    import app.services.whatsapp_instance as wi_module

    mocks = {
        "send_text_message": AsyncMock(return_value=None),
        "send_presence": AsyncMock(return_value=None),
        "mark_messages_as_read": AsyncMock(return_value=None),
        "fetch_profile_picture": AsyncMock(return_value=None),
        "download_media_base64": AsyncMock(return_value=None),
    }
    monkeypatch.setattr(wa_module, "send_text_message", mocks["send_text_message"])
    monkeypatch.setattr(wa_module, "send_presence", mocks["send_presence"])
    monkeypatch.setattr(wa_module, "mark_messages_as_read", mocks["mark_messages_as_read"])
    monkeypatch.setattr(wi_module, "fetch_profile_picture", mocks["fetch_profile_picture"])
    monkeypatch.setattr(wi_module, "download_media_base64", mocks["download_media_base64"])
    return mocks


async def test_multi_agent_reply_flows_through_full_humanization_pipeline(
    client, db_sessionmaker, tenant_a: SeededTenant, _mock_whatsapp_io
):
    await _enable_multi_agent(db_sessionmaker, tenant_a.tenant_id)
    secret, _token = await _configure_whatsapp(db_sessionmaker, tenant_a.tenant_id)

    import app.services.agents.orchestrator as orchestrator_module

    fake_client = SequencedFakeClient([
        fake_function_call("classify", {"agents": ["sales"]}),  # router hop
        # Sales' reply uses [[BREAK]] itself — proves humanizer.split_reply
        # still splits a multi-hop-produced reply into separate WhatsApp sends.
        fake_text("A Limpeza de Pele custa R$180.[[BREAK]]Quer que eu te passe mais detalhes?"),
    ])
    orchestrator_module._get_client = lambda: fake_client  # noqa: SLF001 — see module docstring

    phone = _random_phone()
    resp = await client.post(
        _webhook_path(tenant_a.slug),
        params={"token": secret},
        json=_message_payload(phone=phone, text="quanto custa a limpeza de pele?"),
    )
    assert resp.status_code == 200

    # Wait for the fire-and-forget batcher task (see test_webhooks.py's
    # module docstring on BACKGROUND TASK TIMING) to save both outbound parts.
    async def _has_two_outbound() -> bool:
        msgs = await _get_messages(db_sessionmaker, tenant_a.tenant_id)
        outbound = [m for m in msgs if m.direction == "outbound"]
        return len(outbound) == 2

    assert await _wait_until_async(_has_two_outbound)

    msgs = await _get_messages(db_sessionmaker, tenant_a.tenant_id)
    outbound = [m for m in msgs if m.direction == "outbound"]
    assert outbound[0].content == "A Limpeza de Pele custa R$180."
    assert outbound[1].content == "Quer que eu te passe mais detalhes?"
    assert all(m.ai_model_used for m in outbound)

    # Router + 1 specialist = 2 Gemini calls total for this turn.
    assert len(fake_client.models.calls) == 2

    # Humanization pipeline fired for real: 2 WhatsApp sends (one per part),
    # read receipt sent.
    assert _mock_whatsapp_io["send_text_message"].await_count == 2
    assert _mock_whatsapp_io["mark_messages_as_read"].await_count == 1


async def test_multi_agent_handoff_still_fires_email_alert(
    client, db_sessionmaker, tenant_a: SeededTenant, _mock_whatsapp_io, monkeypatch
):
    """
    Proves the handoff alert wiring (app/services/agents/base.py's
    run_specialist_loop, added specifically because it was missing when
    first written) fires through the real webhook pipeline when the
    multi-agent Handoff specialist is the one calling request_human_handoff
    — not just in unit tests.
    """
    await _enable_multi_agent(db_sessionmaker, tenant_a.tenant_id)
    secret, _token = await _configure_whatsapp(db_sessionmaker, tenant_a.tenant_id)

    from app.api.v1.routes import webhooks as webhooks_module

    handoff_alert = AsyncMock(return_value=True)
    monkeypatch.setattr(webhooks_module, "send_handoff_alert_email", handoff_alert)
    # base.py imports send_handoff_alert_email directly into its own
    # namespace — patch it there too (same "patch where it's looked up"
    # rule documented throughout this test suite).
    import app.services.agents.base as agents_base_module

    monkeypatch.setattr(agents_base_module, "send_handoff_alert_email", handoff_alert)

    import app.services.agents.orchestrator as orchestrator_module

    fake_client = SequencedFakeClient([
        fake_function_call("classify", {"agents": ["handoff"], "handoff_reason": "quer atendente"}),  # router
        fake_function_call("request_human_handoff", {"reason": "quer atendente"}),  # handoff's real tool call
        fake_text("Vou te passar pra alguém da equipe, já já continuam por aqui 😊"),  # handoff's goodbye
    ])
    orchestrator_module._get_client = lambda: fake_client  # noqa: SLF001

    phone = _random_phone()
    resp = await client.post(
        _webhook_path(tenant_a.slug),
        params={"token": secret},
        json=_message_payload(phone=phone, text="quero falar com um atendente"),
    )
    assert resp.status_code == 200

    async def _has_outbound() -> bool:
        msgs = await _get_messages(db_sessionmaker, tenant_a.tenant_id)
        return any(m.direction == "outbound" for m in msgs)

    assert await _wait_until_async(_has_outbound)
    assert await _wait_until(lambda: handoff_alert.await_count >= 1)

    # Contact must actually be paused (ai_paused=True) — the real DB write
    # from ai_tools._request_human_handoff, unaffected by any of this.
    from app.models.contact import Contact

    async def _contact_paused() -> bool:
        async with db_sessionmaker() as session:
            result = await session.execute(
                select(Contact).where(Contact.tenant_id == tenant_a.tenant_id, Contact.phone == phone)
            )
            contact = result.scalar_one_or_none()
            return bool(contact and contact.ai_paused)

    assert await _wait_until_async(_contact_paused)
