"""
Regression tests for "the patient's media message disappeared entirely".

In `_process_inbound_message`, all media handling used to happen BEFORE Phase 1
(persistence), and three paths returned early without ever saving a `Message`:
multimodal disabled, a failed UAZAPI download, and a file over 20 MB. In the
last two nothing was written at all — the clinic never saw in the Inbox that the
patient had sent an audio, and the recovery sweep couldn't pick it up either
(there was no row to find). The patient asked something by voice and, as far as
the clinic was concerned, had never written.

The message is now always persisted (with `media_type` set, `media_url` NULL
when unusable) and the patient gets a short notice instead of silence.

Gemini and all WhatsApp I/O are mocked; Postgres is real.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.integration.conftest import SeededTenant
from tests.integration.test_webhooks import (
    _configure_whatsapp,
    _get_contact_by_phone,
    _get_messages,
    _message_payload,
    _random_phone,
    _wait_until_async,
    _webhook_path,
)


@pytest.fixture(autouse=True)
def _fast_humanization(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "MESSAGE_BATCHING_ENABLED", False)
    monkeypatch.setattr(settings, "TYPING_SIMULATION_ENABLED", False)


@pytest.fixture
def _wa_mocks(monkeypatch):
    import app.services.whatsapp as wa_module
    import app.services.whatsapp_instance as wi_module

    mocks = {
        "send_text_message": AsyncMock(return_value=None),
        "send_presence": AsyncMock(return_value=None),
        "mark_messages_as_read": AsyncMock(return_value=None),
        "fetch_profile_picture": AsyncMock(return_value=None),
        # The failure under test: UAZAPI gives up on the download.
        "download_media_base64": AsyncMock(return_value=None),
    }
    monkeypatch.setattr(wa_module, "send_text_message", mocks["send_text_message"])
    monkeypatch.setattr(wa_module, "send_presence", mocks["send_presence"])
    monkeypatch.setattr(wa_module, "mark_messages_as_read", mocks["mark_messages_as_read"])
    monkeypatch.setattr(wi_module, "fetch_profile_picture", mocks["fetch_profile_picture"])
    monkeypatch.setattr(wi_module, "download_media_base64", mocks["download_media_base64"])
    return mocks


async def _audio_messages(db_sessionmaker, tenant_id, contact_id):
    msgs = await _get_messages(db_sessionmaker, tenant_id, contact_id)
    return [m for m in msgs if m.media_type == "audio"]


async def test_failed_media_download_still_persists_the_message(
    client, db_sessionmaker, tenant_a: SeededTenant, _wa_mocks
):
    secret, _token = await _configure_whatsapp(db_sessionmaker, tenant_a.tenant_id)
    phone = _random_phone()

    resp = await client.post(
        _webhook_path(tenant_a.slug),
        params={"token": secret},
        json=_message_payload(phone=phone, text="", message_type="audioMessage"),
    )
    assert resp.status_code == 200

    async def _saved() -> bool:
        contact = await _get_contact_by_phone(db_sessionmaker, tenant_a.tenant_id, phone)
        if contact is None:
            return False
        return len(await _audio_messages(db_sessionmaker, tenant_a.tenant_id, contact.id)) == 1

    assert await _wait_until_async(_saved), (
        "the inbound audio must be persisted even when the download fails — "
        "otherwise it never reaches the Inbox and is lost for good"
    )

    contact = await _get_contact_by_phone(db_sessionmaker, tenant_a.tenant_id, phone)
    (audio,) = await _audio_messages(db_sessionmaker, tenant_a.tenant_id, contact.id)
    assert audio.direction == "inbound"
    assert audio.media_type == "audio"
    assert audio.media_url is None  # nothing was downloadable
    # And the patient is told, rather than left in silence.
    assert _wa_mocks["send_text_message"].await_count == 1
    sent_text = _wa_mocks["send_text_message"].await_args.kwargs["text"]
    assert "áudio" in sent_text.lower()


async def test_media_is_persisted_when_multimodal_is_disabled(
    client, db_sessionmaker, tenant_a: SeededTenant, _wa_mocks
):
    from app.models.tenant import Tenant

    secret, _token = await _configure_whatsapp(db_sessionmaker, tenant_a.tenant_id)
    async with db_sessionmaker() as session:
        tenant = await session.get(Tenant, tenant_a.tenant_id)
        tenant.ai_config = {**(tenant.ai_config or {}), "multimodal_enabled": False}
        session.add(tenant)
        await session.commit()

    phone = _random_phone()
    resp = await client.post(
        _webhook_path(tenant_a.slug),
        params={"token": secret},
        json=_message_payload(phone=phone, text="", message_type="imageMessage"),
    )
    assert resp.status_code == 200

    async def _saved() -> bool:
        contact = await _get_contact_by_phone(db_sessionmaker, tenant_a.tenant_id, phone)
        if contact is None:
            return False
        msgs = await _get_messages(db_sessionmaker, tenant_a.tenant_id, contact.id)
        return any(m.media_type == "image" for m in msgs)

    assert await _wait_until_async(_saved), (
        "a photo received while multimodal is off must still show up in the Inbox"
    )
    # Never downloaded (feature is off), and the canned notice went out.
    assert _wa_mocks["download_media_base64"].await_count == 0
    assert _wa_mocks["send_text_message"].await_count == 1
