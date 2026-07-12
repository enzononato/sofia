"""
Integration tests for the WhatsApp webhook receiver
(app/api/v1/routes/webhooks.py) — Frente 4.4, the acceptance gate for
Frente 1 (how Sofia actually receives and answers WhatsApp messages). This
behavior had NO automated test coverage before this file (only manual
validation) despite being the single most-edited, most-critical file in the
project.

Exercises the real FastAPI app (all middlewares) + a real Postgres database
via httpx.AsyncClient + ASGITransport, POSTing raw UAZAPI-shaped webhook
bodies at `/webhooks/whatsapp/{tenant_slug}?token=...` — exactly what UAZAPI
sends in production. See tests/integration/conftest.py for the shared
fixtures (`client`, `db_sessionmaker`, `tenant_a`, `tenant_b`); this file
adds its own webhook-specific helpers (conftest.py explicitly called
webhooks.py "out of scope" for the round that built that infra).

────────────────────────────────────────────────────────────────────────────
WHAT'S MOCKED, AND WHERE (module-identity, not string-only patches)
────────────────────────────────────────────────────────────────────────────
Real network calls to Gemini and UAZAPI would cost money/depend on external
services, so every test in this file patches, via monkeypatch, the ACTUAL
service module's attribute (not a re-imported alias) so the patch is visible
through every name that points at the same function object:

  - `app.services.ai.generate_reply`            (webhooks.py: `ai_service.generate_reply`
                                                   — `ai_service` IS `app.services.ai`,
                                                   same module object, so patching the
                                                   module attribute is sufficient)
  - `app.services.whatsapp.send_text_message` / `send_presence` / `mark_messages_as_read`
                                                  (webhooks.py: `wa_service.*`, same story)
  - `app.services.whatsapp_instance.fetch_profile_picture` / `download_media_base64`
                                                  (webhooks.py: `wi.*`, same story)
  - `app.api.v1.routes.webhooks.send_handoff_alert_email` /
    `send_tenant_usage_cap_alert_email`          — these ARE bound directly into the
                                                    webhooks module's own namespace via
                                                    `from app.services.alerts import ...`,
                                                    a *copied* name binding distinct from
                                                    `app.services.alerts.<name>`. Patching
                                                    the alerts module itself would NOT be
                                                    visible from webhooks.py — a classic
                                                    "patched the wrong place" trap this
                                                    file deliberately avoids.

────────────────────────────────────────────────────────────────────────────
BACKGROUND TASK TIMING (read this before adding more tests here)
────────────────────────────────────────────────────────────────────────────
Empirically verified (throwaway probe, not checked in) against this exact
httpx.ASGITransport + FastAPI BackgroundTasks combo:

  1. `BackgroundTasks.add_task(...)` (what the webhook route uses to dispatch
     `_process_inbound_message` / `_process_human_outbound_message`) DOES run
     to completion before `await client.post(...)` returns. Starlette's
     `Response.__call__` awaits `self.background()` in the same coroutine
     chain ASGITransport awaits end-to-end — no extra sleep needed for
     anything that happens directly inside those two functions.

  2. HOWEVER, `_process_inbound_message` — for a normal (non-media) inbound
     text message — ends by calling `message_batcher.schedule()`, which
     (batching enabled OR disabled) always wraps the actual reply work
     (`_generate_and_send`, i.e. the AI call + WhatsApp send) in a bare
     `asyncio.create_task(...)`. That is genuinely fire-and-forget: it is
     NOT awaited by `_process_inbound_message`, so it is NOT covered by
     guarantee #1. By the instant `client.post()` returns, that inner task
     has only been *scheduled*, not necessarily run.

  Consequence for this file:
    - Assertions about what happens INSIDE `_process_inbound_message` /
      `_process_human_outbound_message` themselves (contact created, inbound
      message persisted, early-return guards like ai_paused / historical /
      human-takeover / group-skip / duplicate-id, which all fire BEFORE
      `batcher.schedule()` is ever called) are safe to check IMMEDIATELY
      after `client.post()` returns — no wait needed, and no wait would be
      more correct than a fixed sleep anyway.
    - Assertions about the actual AI reply (`generate_reply` called, a reply
      `Message` saved, `send_text_message` called, a usage-cap pause applied
      inside `_generate_and_send`) MUST wait for that nested task to finish.
      This file uses `_wait_until(predicate, timeout=...)` — a short polling
      loop against an observable side effect (an AsyncMock's `await_count`,
      or a fresh DB read) — instead of a blind `asyncio.sleep(N)`. Combined
      with the `_fast_humanization` autouse fixture (disables the 15-20s
      debounce window and the per-part typing delay), the nested task
      normally completes within a few dozen milliseconds, so the polling
      loop resolves almost immediately in practice; the timeout is only a
      safety net against a genuine regression, not the expected wait time.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from tests.integration.conftest import SeededTenant

# ── Generic helpers ──────────────────────────────────────────────────────


async def _wait_until(predicate, *, timeout: float = 5.0, interval: float = 0.03) -> bool:
    """Poll a cheap, synchronous `predicate()` until it's truthy or `timeout`
    elapses. See the module docstring ("BACKGROUND TASK TIMING") for why this
    is needed instead of relying on BackgroundTasks alone."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def _wait_until_async(async_predicate, *, timeout: float = 5.0, interval: float = 0.03) -> bool:
    """Same as `_wait_until` but for a predicate that itself needs to `await`
    (e.g. a fresh DB read) rather than reading an in-memory mock's counters."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await async_predicate():
            return True
        await asyncio.sleep(interval)
    return await async_predicate()


def _random_phone() -> str:
    return f"55119{uuid.uuid4().int % 10**8:08d}"


def _webhook_path(slug: str) -> str:
    return f"/webhooks/whatsapp/{slug}"


def _message_payload(
    *,
    phone: str,
    text: str = "Olá, gostaria de agendar uma consulta",
    message_id: str | None = None,
    from_me: bool = False,
    was_sent_by_api: bool = False,
    is_group: bool = False,
    ts_ms: int | None = None,
    sender_name: str = "Paciente Teste",
    message_type: str = "conversation",
    chatid: str | None = None,
) -> dict:
    """Build a UAZAPI-shaped webhook body (flat `message` payload under
    `EventType: "messages"` — see the module docstring in webhooks.py)."""
    if ts_ms is None:
        ts_ms = int(time.time() * 1000)
    suffix = "@g.us" if is_group else "@s.whatsapp.net"
    resolved_chatid = chatid if chatid is not None else f"{phone}{suffix}"
    return {
        "EventType": "messages",
        "message": {
            "chatid": resolved_chatid,
            "sender_pn": f"{phone}@s.whatsapp.net",
            "sender": f"{phone}@s.whatsapp.net",
            "sender_lid": "",
            "senderName": sender_name,
            "messageid": message_id or f"wamid.{uuid.uuid4().hex}",
            "messageTimestamp": ts_ms,
            "text": text,
            "messageType": message_type,
            "fromMe": from_me,
            "wasSentByApi": was_sent_by_api,
            "isGroup": is_group,
        },
    }


async def _configure_whatsapp(
    db_sessionmaker, tenant_id, *, secret: str = "wh-secret-123", token: str = "fake-instance-token"
) -> tuple[str, str]:
    """Set tenant.settings.whatsapp = {webhook_secret, token} directly in the
    DB (there's no admin endpoint that exposes webhook_secret — it's a
    server-managed secret, never returned by the API)."""
    from app.models.tenant import Tenant

    async with db_sessionmaker() as session:
        tenant = await session.get(Tenant, tenant_id)
        tenant.settings = {**(tenant.settings or {}), "whatsapp": {"webhook_secret": secret, "token": token}}
        session.add(tenant)
        await session.commit()
    return secret, token


async def _get_contact_by_phone(db_sessionmaker, tenant_id, phone: str):
    from app.models.contact import Contact

    async with db_sessionmaker() as session:
        result = await session.execute(
            select(Contact).where(Contact.tenant_id == tenant_id, Contact.phone == phone)
        )
        return result.scalar_one_or_none()


async def _create_contact(db_sessionmaker, tenant_id, *, phone: str, full_name: str = "Paciente Teste", ai_paused: bool = False):
    from app.models.contact import Contact

    async with db_sessionmaker() as session:
        contact = Contact(tenant_id=tenant_id, full_name=full_name, phone=phone, ai_paused=ai_paused)
        session.add(contact)
        await session.commit()
        await session.refresh(contact)
        return contact


async def _get_messages(db_sessionmaker, tenant_id, contact_id=None):
    from app.models.message import Message

    async with db_sessionmaker() as session:
        stmt = select(Message).where(Message.tenant_id == tenant_id)
        if contact_id is not None:
            stmt = stmt.where(Message.contact_id == contact_id)
        stmt = stmt.order_by(Message.created_at)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def _create_appointment(db_sessionmaker, tenant_id, contact_id, *, when: datetime | None = None):
    from app.models.appointment import Appointment, AppointmentStatus

    scheduled_at = when or (datetime.now(timezone.utc) + timedelta(days=1))
    async with db_sessionmaker() as session:
        appt = Appointment(
            tenant_id=tenant_id,
            contact_id=contact_id,
            scheduled_at=scheduled_at,
            ends_at=scheduled_at + timedelta(minutes=30),
            status=AppointmentStatus.SCHEDULED,
        )
        session.add(appt)
        await session.commit()
        await session.refresh(appt)
        return appt


async def _get_appointment(db_sessionmaker, appointment_id):
    from app.models.appointment import Appointment

    async with db_sessionmaker() as session:
        return await session.get(Appointment, appointment_id)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fast_humanization(monkeypatch):
    """Strip the deliberately slow/random parts of the humanization pipeline
    so tests are fast and deterministic, without changing any decision logic:
      - MESSAGE_BATCHING_ENABLED=False: batcher.schedule() dispatches the
        reply via a bare asyncio.create_task instead of an 8-20s debounce.
      - TYPING_SIMULATION_ENABLED=False: skips the per-part typing sleep.
    AI usage caps are intentionally left at their real defaults (ON, 40/400)
    unless a test overrides them explicitly (see the D3 scenario) — that's
    what production actually runs, and the defaults are high enough that no
    other scenario here comes close to tripping them."""
    from app.config import settings

    monkeypatch.setattr(settings, "MESSAGE_BATCHING_ENABLED", False)
    monkeypatch.setattr(settings, "TYPING_SIMULATION_ENABLED", False)


@pytest.fixture(autouse=True)
def _mock_whatsapp_io(monkeypatch):
    """Never let any test in this file hit real UAZAPI. Applied to every
    test regardless of whether it cares about WhatsApp sends, so a future
    code path change can't silently start making real HTTP calls here."""
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


@pytest.fixture
def mock_ai(monkeypatch):
    """Default AI double: always returns a canned reply, never touches Gemini.
    Tests that need custom behavior (e.g. simulating a tool call) override
    `.side_effect` on the returned mock."""
    import app.services.ai as ai_module

    mock = AsyncMock(return_value=("Olá! Recebi sua mensagem, um momento.", "gemini-mock"))
    monkeypatch.setattr(ai_module, "generate_reply", mock)
    return mock


@pytest.fixture
def mock_alerts(monkeypatch):
    from app.api.v1.routes import webhooks as webhooks_module

    handoff = AsyncMock(return_value=True)
    tenant_cap = AsyncMock(return_value=True)
    monkeypatch.setattr(webhooks_module, "send_handoff_alert_email", handoff)
    monkeypatch.setattr(webhooks_module, "send_tenant_usage_cap_alert_email", tenant_cap)
    return {"handoff": handoff, "tenant_cap": tenant_cap}


# ── 1. Fail-closed webhook secret ───────────────────────────────────────────


async def test_webhook_rejects_when_tenant_has_no_secret_configured(client, db_sessionmaker, tenant_a: SeededTenant, mock_ai):
    # Deliberately do NOT call _configure_whatsapp — tenant.settings has no
    # "whatsapp" key at all, matching a tenant that never connected WhatsApp.
    phone = _random_phone()
    resp = await client.post(
        _webhook_path(tenant_a.slug),
        params={"token": "whatever-token"},
        json=_message_payload(phone=phone),
    )
    assert resp.status_code == 200  # always opaque 200 — see webhooks.py docstring
    assert resp.json() == {"received": True}

    contact = await _get_contact_by_phone(db_sessionmaker, tenant_a.tenant_id, phone)
    assert contact is None
    assert mock_ai.await_count == 0


async def test_webhook_rejects_wrong_token(client, db_sessionmaker, tenant_a: SeededTenant, mock_ai):
    await _configure_whatsapp(db_sessionmaker, tenant_a.tenant_id, secret="correct-secret")
    phone = _random_phone()

    resp = await client.post(
        _webhook_path(tenant_a.slug),
        params={"token": "wrong-secret"},
        json=_message_payload(phone=phone),
    )
    assert resp.status_code == 200

    contact = await _get_contact_by_phone(db_sessionmaker, tenant_a.tenant_id, phone)
    assert contact is None
    assert mock_ai.await_count == 0


async def test_webhook_accepts_correct_token_and_processes_message(client, db_sessionmaker, tenant_a: SeededTenant, mock_ai, _mock_whatsapp_io):
    secret, _token = await _configure_whatsapp(db_sessionmaker, tenant_a.tenant_id, secret="correct-secret")
    phone = _random_phone()

    resp = await client.post(
        _webhook_path(tenant_a.slug),
        params={"token": secret},
        json=_message_payload(phone=phone, text="Oi, quero marcar uma consulta"),
    )
    assert resp.status_code == 200

    # Contact + inbound message are saved synchronously (Phase 1) inside the
    # awaited BackgroundTask — safe to assert immediately, no wait needed.
    contact = await _get_contact_by_phone(db_sessionmaker, tenant_a.tenant_id, phone)
    assert contact is not None

    # The actual AI reply runs via a detached asyncio task — wait for it.
    assert await _wait_until(lambda: mock_ai.await_count >= 1)
    assert await _wait_until(lambda: _mock_whatsapp_io["send_text_message"].await_count >= 1)


# ── 2. Idempotency (duplicate delivery) ─────────────────────────────────────


async def test_duplicate_webhook_delivery_is_idempotent(client, db_sessionmaker, tenant_a: SeededTenant, mock_ai):
    secret, _token = await _configure_whatsapp(db_sessionmaker, tenant_a.tenant_id)
    phone = _random_phone()
    message_id = f"wamid.dup.{uuid.uuid4().hex}"
    payload = _message_payload(phone=phone, message_id=message_id, text="Oi, tudo bem?")

    resp1 = await client.post(_webhook_path(tenant_a.slug), params={"token": secret}, json=payload)
    assert resp1.status_code == 200
    assert await _wait_until(lambda: mock_ai.await_count >= 1)

    contact = await _get_contact_by_phone(db_sessionmaker, tenant_a.tenant_id, phone)
    assert contact is not None

    # Re-deliver the EXACT same payload (UAZAPI retry semantics).
    resp2 = await client.post(_webhook_path(tenant_a.slug), params={"token": secret}, json=payload)
    assert resp2.status_code == 200

    # The dup-id fast path returns before ever scheduling a reply — safe to
    # assert immediately (no nested task is created on this delivery).
    assert mock_ai.await_count == 1

    inbound = [
        m for m in await _get_messages(db_sessionmaker, tenant_a.tenant_id, contact.id)
        if m.direction == "inbound" and m.whatsapp_message_id == message_id
    ]
    assert len(inbound) == 1


# ── 3. Group messages ignored by default ────────────────────────────────────


async def test_group_message_ignored_by_default(client, db_sessionmaker, tenant_a: SeededTenant, mock_ai):
    secret, _token = await _configure_whatsapp(db_sessionmaker, tenant_a.tenant_id)
    phone = _random_phone()

    resp = await client.post(
        _webhook_path(tenant_a.slug),
        params={"token": secret},
        json=_message_payload(phone=phone, is_group=True, text="Mensagem de grupo"),
    )
    assert resp.status_code == 200

    # The group check happens synchronously in the route handler itself,
    # BEFORE background_tasks.add_task is even called — no wait needed.
    contact = await _get_contact_by_phone(db_sessionmaker, tenant_a.tenant_id, phone)
    assert contact is None
    assert mock_ai.await_count == 0


# ── 4. Historical message saved but does not trigger a reply ───────────────


async def test_historical_message_saved_but_ai_not_triggered(client, db_sessionmaker, tenant_a: SeededTenant, mock_ai):
    secret, _token = await _configure_whatsapp(db_sessionmaker, tenant_a.tenant_id)
    phone = _random_phone()
    ten_minutes_ago_ms = int((time.time() - 600) * 1000)  # > 300s threshold

    resp = await client.post(
        _webhook_path(tenant_a.slug),
        params={"token": secret},
        json=_message_payload(phone=phone, ts_ms=ten_minutes_ago_ms, text="Mensagem antiga"),
    )
    assert resp.status_code == 200

    contact = await _get_contact_by_phone(db_sessionmaker, tenant_a.tenant_id, phone)
    assert contact is not None
    messages = await _get_messages(db_sessionmaker, tenant_a.tenant_id, contact.id)
    assert len(messages) == 1
    assert messages[0].direction == "inbound"

    # is_historical returns before batcher.schedule() is ever reached —
    # deterministic immediately, no wait needed.
    assert mock_ai.await_count == 0


# ── 5 & 6. Human takeover (D4): fromMe outbound recorded + auto-pauses Sofia ─


async def test_human_outbound_message_recorded_and_auto_pauses_then_blocks_next_inbound(
    client, db_sessionmaker, tenant_a: SeededTenant, mock_ai
):
    secret, _token = await _configure_whatsapp(db_sessionmaker, tenant_a.tenant_id)
    phone = _random_phone()

    # (5) Staff replies directly from their own phone — fromMe=true, NOT sent
    # via our API (wasSentByApi=false). chatid (not sender_pn) is the patient.
    resp = await client.post(
        _webhook_path(tenant_a.slug),
        params={"token": secret},
        json=_message_payload(
            phone=phone,
            chatid=f"{phone}@s.whatsapp.net",
            text="Oi! Já te encaixei aqui, pode vir às 15h",
            from_me=True,
            was_sent_by_api=False,
        ),
    )
    assert resp.status_code == 200

    contact = await _get_contact_by_phone(db_sessionmaker, tenant_a.tenant_id, phone)
    assert contact is not None, "human outbound must still create the contact"
    assert contact.human_takeover_until is not None
    now = datetime.now(timezone.utc)
    assert now < contact.human_takeover_until < now + timedelta(minutes=61)

    messages = await _get_messages(db_sessionmaker, tenant_a.tenant_id, contact.id)
    assert len(messages) == 1
    assert messages[0].direction == "outbound"
    assert messages[0].ai_model_used is None  # a human typed it, not Sofia

    # _process_human_outbound_message never touches ai_service at all.
    assert mock_ai.await_count == 0

    # (6) A genuine inbound message from the same patient, still inside the
    # takeover window, must be saved but must NOT trigger an AI reply.
    resp2 = await client.post(
        _webhook_path(tenant_a.slug),
        params={"token": secret},
        json=_message_payload(phone=phone, text="Combinado, obrigado!"),
    )
    assert resp2.status_code == 200

    messages_after = await _get_messages(db_sessionmaker, tenant_a.tenant_id, contact.id)
    assert len(messages_after) == 2
    assert messages_after[1].direction == "inbound"

    # The human-takeover check happens synchronously before batcher.schedule()
    # — deterministic immediately, no wait needed.
    assert mock_ai.await_count == 0


# ── 7. New contact created correctly ────────────────────────────────────────


async def test_first_inbound_message_creates_new_contact_scoped_to_tenant(
    client, db_sessionmaker, tenant_a: SeededTenant, mock_ai
):
    secret, _token = await _configure_whatsapp(db_sessionmaker, tenant_a.tenant_id)
    phone = _random_phone()

    resp = await client.post(
        _webhook_path(tenant_a.slug),
        params={"token": secret},
        json=_message_payload(phone=phone, text="Primeira mensagem", sender_name="Fulano da Silva"),
    )
    assert resp.status_code == 200

    contact = await _get_contact_by_phone(db_sessionmaker, tenant_a.tenant_id, phone)
    assert contact is not None
    assert contact.tenant_id == tenant_a.tenant_id
    assert contact.phone == phone
    assert contact.whatsapp_name == "Fulano da Silva"
    assert contact.full_name == "Fulano da Silva"
    assert contact.ai_paused is False

    # Full pipeline sanity: the new contact also gets a reply.
    assert await _wait_until(lambda: mock_ai.await_count >= 1)


# ── 8. ai_paused blocks the reply ───────────────────────────────────────────


async def test_ai_paused_contact_blocks_reply_but_still_saves_message(
    client, db_sessionmaker, tenant_a: SeededTenant, mock_ai
):
    secret, _token = await _configure_whatsapp(db_sessionmaker, tenant_a.tenant_id)
    phone = _random_phone()
    contact = await _create_contact(db_sessionmaker, tenant_a.tenant_id, phone=phone, ai_paused=True)

    resp = await client.post(
        _webhook_path(tenant_a.slug),
        params={"token": secret},
        json=_message_payload(phone=phone, text="Alguém aí?"),
    )
    assert resp.status_code == 200

    messages = await _get_messages(db_sessionmaker, tenant_a.tenant_id, contact.id)
    assert len(messages) == 1
    assert messages[0].direction == "inbound"

    # ai_paused is checked synchronously before batcher.schedule() — safe to
    # assert immediately.
    assert mock_ai.await_count == 0


# ── 9. AI usage caps (D3) ────────────────────────────────────────────────────


async def test_ai_usage_cap_per_contact_pauses_contact_and_fires_alert(
    client, db_sessionmaker, tenant_a: SeededTenant, mock_ai, mock_alerts, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "AI_USAGE_LIMITS_ENABLED", True)
    monkeypatch.setattr(settings, "AI_USAGE_CAP_PER_CONTACT_DAILY", 2)
    monkeypatch.setattr(settings, "AI_USAGE_CAP_PER_TENANT_DAILY", 999)

    secret, _token = await _configure_whatsapp(db_sessionmaker, tenant_a.tenant_id)
    phone = _random_phone()

    async def _ai_outbound_count(contact_id) -> int:
        msgs = await _get_messages(db_sessionmaker, tenant_a.tenant_id, contact_id)
        return sum(1 for m in msgs if m.direction == "outbound" and m.ai_model_used)

    def _reached(contact_id, n: int):
        async def _check() -> bool:
            return await _ai_outbound_count(contact_id) >= n
        return _check

    # Message #1 — under cap, gets a real AI reply. Wait for the OUTBOUND row
    # to actually be committed (not just generate_reply having been awaited —
    # _save_outbound commits in its own session slightly afterward), since
    # that committed row is what the cap-counting query itself reads.
    await client.post(
        _webhook_path(tenant_a.slug), params={"token": secret},
        json=_message_payload(phone=phone, text="Mensagem 1"),
    )
    contact = await _get_contact_by_phone(db_sessionmaker, tenant_a.tenant_id, phone)
    assert contact is not None
    assert await _wait_until_async(_reached(contact.id, 1))

    # Message #2 — still under cap (1 < cap 2), gets a reply too.
    await client.post(
        _webhook_path(tenant_a.slug), params={"token": secret},
        json=_message_payload(phone=phone, text="Mensagem 2"),
    )
    assert await _wait_until_async(_reached(contact.id, 2))

    assert mock_ai.await_count == 2
    assert await _ai_outbound_count(contact.id) == 2  # cap (2) reached exactly

    # Message #3 — the cap check now sees 2 AI replies today >= cap(2) and
    # must pause the contact WITHOUT calling generate_reply for this turn.
    await client.post(
        _webhook_path(tenant_a.slug), params={"token": secret},
        json=_message_payload(phone=phone, text="Mensagem 3"),
    )

    async def _contact_is_paused() -> bool:
        fresh = await _get_contact_by_phone(db_sessionmaker, tenant_a.tenant_id, phone)
        return bool(fresh and fresh.ai_paused)

    assert await _wait_until_async(_contact_is_paused), (
        "contact.ai_paused must become True once the per-contact daily cap is hit"
    )

    # generate_reply must NOT have been called a 3rd time — the cap blocked
    # it before _generate_and_send ever reaches _collect_unanswered/generate_reply.
    assert mock_ai.await_count == 2
    assert await _ai_outbound_count(contact.id) == 2  # no 3rd AI reply was ever saved

    # The handoff alert fires fire-and-forget (asyncio.create_task) — wait for it.
    assert await _wait_until(lambda: mock_alerts["handoff"].await_count >= 1)
    got_tenant, got_contact, got_reason = mock_alerts["handoff"].await_args.args
    assert got_tenant.id == tenant_a.tenant_id
    assert got_contact.phone == phone
    assert "Limite diário" in got_reason


# ── 10. confirm_appointment tool works end-to-end through the webhook ──────


async def test_confirm_appointment_tool_call_through_webhook_updates_appointment(
    client, db_sessionmaker, tenant_a: SeededTenant, monkeypatch
):
    from app.models.appointment import AppointmentStatus
    import app.services.ai as ai_module

    secret, _token = await _configure_whatsapp(db_sessionmaker, tenant_a.tenant_id)
    phone = _random_phone()
    contact = await _create_contact(db_sessionmaker, tenant_a.tenant_id, phone=phone)
    appt = await _create_appointment(db_sessionmaker, tenant_a.tenant_id, contact.id)
    assert appt.status == AppointmentStatus.SCHEDULED

    async def _fake_generate_reply(*, tenant, contact, new_message, history, db, media=None):
        # Simulate Gemini having decided to call confirm_appointment — drives
        # the REAL tool executor (real DB write, real tenant/contact scoping)
        # instead of hand-rolling the appointment update in the test, without
        # making a real Gemini API call.
        from app.services.ai_tools import execute_tool

        result = await execute_tool(
            "confirm_appointment",
            {"appointment_id": str(appt.id)},
            db=db,
            tenant_id=tenant.id,
            contact_id=contact.id,
        )
        assert result.get("success") is True, result
        return ("Perfeito, presença confirmada! Te esperamos.", "gemini-mock-tool")

    mock = AsyncMock(side_effect=_fake_generate_reply)
    monkeypatch.setattr(ai_module, "generate_reply", mock)

    resp = await client.post(
        _webhook_path(tenant_a.slug),
        params={"token": secret},
        json=_message_payload(phone=phone, text="Sim, confirmado! Vou sim"),
    )
    assert resp.status_code == 200
    assert await _wait_until(lambda: mock.await_count >= 1)

    async def _appt_confirmed() -> bool:
        fresh = await _get_appointment(db_sessionmaker, appt.id)
        return fresh is not None and fresh.status == AppointmentStatus.CONFIRMED

    assert await _wait_until_async(_appt_confirmed), (
        "the tool's DB write must have committed via Phase 2's transaction"
    )


# ── 11. Tenant isolation in the webhook ─────────────────────────────────────


async def test_webhook_isolates_same_phone_number_across_tenants(
    client, db_sessionmaker, tenant_a: SeededTenant, tenant_b: SeededTenant, mock_ai
):
    secret_a, _ = await _configure_whatsapp(db_sessionmaker, tenant_a.tenant_id, secret="secret-a")
    secret_b, _ = await _configure_whatsapp(db_sessionmaker, tenant_b.tenant_id, secret="secret-b")

    # Same phone number for both tenants — phone is NOT globally unique, only
    # scoped per tenant (see _find_or_create_contact).
    phone = _random_phone()

    resp_a = await client.post(
        _webhook_path(tenant_a.slug), params={"token": secret_a},
        json=_message_payload(phone=phone, text="Mensagem para a clínica A", sender_name="Paciente A"),
    )
    assert resp_a.status_code == 200

    resp_b = await client.post(
        _webhook_path(tenant_b.slug), params={"token": secret_b},
        json=_message_payload(phone=phone, text="Mensagem para a clínica B", sender_name="Paciente B"),
    )
    assert resp_b.status_code == 200

    contact_a = await _get_contact_by_phone(db_sessionmaker, tenant_a.tenant_id, phone)
    contact_b = await _get_contact_by_phone(db_sessionmaker, tenant_b.tenant_id, phone)
    assert contact_a is not None
    assert contact_b is not None
    assert contact_a.id != contact_b.id
    assert contact_a.tenant_id == tenant_a.tenant_id
    assert contact_b.tenant_id == tenant_b.tenant_id
    assert contact_a.whatsapp_name == "Paciente A"
    assert contact_b.whatsapp_name == "Paciente B"

    # Inbound rows are saved synchronously (Phase 1) — safe to assert right away.
    inbound_a = [m for m in await _get_messages(db_sessionmaker, tenant_a.tenant_id, contact_a.id) if m.direction == "inbound"]
    inbound_b = [m for m in await _get_messages(db_sessionmaker, tenant_b.tenant_id, contact_b.id) if m.direction == "inbound"]
    assert len(inbound_a) == 1
    assert len(inbound_b) == 1
    assert inbound_a[0].tenant_id == tenant_a.tenant_id
    assert inbound_b[0].tenant_id == tenant_b.tenant_id

    # The AI reply for each tenant runs via its own detached asyncio task —
    # wait for both, then confirm each tenant only ever got ITS OWN reply
    # (never leaked the other tenant's outbound message).
    assert await _wait_until(lambda: mock_ai.await_count >= 2)

    all_a = await _get_messages(db_sessionmaker, tenant_a.tenant_id, contact_a.id)
    all_b = await _get_messages(db_sessionmaker, tenant_b.tenant_id, contact_b.id)
    assert len(all_a) == 2  # 1 inbound + 1 AI outbound
    assert len(all_b) == 2
    assert all(m.tenant_id == tenant_a.tenant_id for m in all_a)
    assert all(m.tenant_id == tenant_b.tenant_id for m in all_b)
