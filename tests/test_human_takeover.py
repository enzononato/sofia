"""
Unit tests for the D4 human-takeover auto-pause: when staff reply to a
patient directly from their own phone/WhatsApp Web (fromMe=true,
wasSentByApi=false — app.api.v1.routes.webhooks._process_human_outbound_message),
Sofia auto-pauses herself for that contact for HUMAN_TAKEOVER_PAUSE_MINUTES,
renewing (not stacking) on every new human message, and expiring on its own.

Covers, without a real DB session (fake AsyncSessionLocal/session doubles):
  - `app.services.takeover.in_human_takeover()`: the pure predicate gating every
    AI-reply decision point (future timestamp = paused, past/None = not paused);
  - `_process_human_outbound_message` sets `contact.human_takeover_until` to
    ~now + HUMAN_TAKEOVER_PAUSE_MINUTES, and a SECOND human message RESETS it
    (proven by pre-seeding an absurd far-future value that would survive an
    "extend if later" bug but not a plain overwrite);
  - `_generate_and_send` bails out before doing anything else (no AI call, no
    WhatsApp send) when the contact is currently in the takeover window.

The full flow (real Contact row, real renew-then-expire timeline) was ALSO
verified manually end-to-end against the local dev Postgres — see the final
summary for the exact scenarios exercised.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.api.v1.routes import webhooks as webhooks_module
from app.services.takeover import in_human_takeover


# ---------------------------------------------------------------------------
# in_human_takeover — predicado puro (agora em app/services/takeover.py)
# ---------------------------------------------------------------------------

def test_in_human_takeover_true_when_timestamp_is_in_the_future():
    contact = SimpleNamespace(
        human_takeover_until=datetime.now(timezone.utc) + timedelta(minutes=30)
    )
    assert in_human_takeover(contact, datetime.now(timezone.utc)) is True


def test_in_human_takeover_false_when_timestamp_is_in_the_past():
    contact = SimpleNamespace(
        human_takeover_until=datetime.now(timezone.utc) - timedelta(minutes=1)
    )
    assert in_human_takeover(contact, datetime.now(timezone.utc)) is False


def test_in_human_takeover_false_when_none():
    assert in_human_takeover(
        SimpleNamespace(human_takeover_until=None), datetime.now(timezone.utc)
    ) is False


def test_in_human_takeover_false_when_attribute_missing():
    assert in_human_takeover(SimpleNamespace(), datetime.now(timezone.utc)) is False


# ---------------------------------------------------------------------------
# _process_human_outbound_message — set/renew (not stack)
# ---------------------------------------------------------------------------

class _FakeSessionCM:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _RecordingDB:
    """Fake AsyncSession good enough for _process_human_outbound_message:
    no duplicate found (scalar -> None), records add()/commit()."""

    def __init__(self):
        self.added = []
        self.commits = 0

    async def scalar(self, *args, **kwargs):
        return None

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


def _session_factory(session):
    def _factory():
        return _FakeSessionCM(session)
    return _factory


@pytest.fixture
def _human_outbound_env(monkeypatch):
    """Wires a fake AsyncSessionLocal + a fixed contact double (bypassing
    _find_or_create_contact's own DB/HTTP work) so
    _process_human_outbound_message can run fully offline."""
    contact = SimpleNamespace(id="33333333-3333-3333-3333-333333333333", human_takeover_until=None)

    async def _fake_find_or_create(db, tenant, phone, push_name=""):
        return contact

    db = _RecordingDB()
    monkeypatch.setattr(webhooks_module, "_find_or_create_contact", _fake_find_or_create)
    monkeypatch.setattr(webhooks_module, "AsyncSessionLocal", _session_factory(db))
    monkeypatch.setattr(webhooks_module.settings, "HUMAN_TAKEOVER_PAUSE_MINUTES", 60)
    return contact, db


async def test_human_outbound_message_sets_takeover_window(_human_outbound_env):
    contact, db = _human_outbound_env
    tenant = SimpleNamespace(id="tid", settings={})
    data = {"chatid": "5511999999999@s.whatsapp.net", "text": "cheguei", "messageType": "conversation"}

    before = datetime.now(timezone.utc)
    await webhooks_module._process_human_outbound_message(tenant, data, request_id=None)

    assert contact.human_takeover_until is not None
    delta = contact.human_takeover_until - before
    assert timedelta(minutes=59) < delta < timedelta(minutes=61)
    assert db.commits == 1


async def test_second_human_message_renews_instead_of_stacking(_human_outbound_env):
    contact, db = _human_outbound_env
    tenant = SimpleNamespace(id="tid", settings={})
    data = {"chatid": "5511999999999@s.whatsapp.net", "text": "oi de novo", "messageType": "conversation"}

    # Pre-seed an absurd far-future value. An "extend if later" bug would
    # leave this untouched (it's already way later than now+60min); a
    # correct RENEW (plain overwrite) must reset it close to now+60min.
    stale = datetime.now(timezone.utc) + timedelta(days=30)
    contact.human_takeover_until = stale

    await webhooks_module._process_human_outbound_message(tenant, data, request_id=None)

    assert contact.human_takeover_until < stale - timedelta(days=1)
    assert contact.human_takeover_until < datetime.now(timezone.utc) + timedelta(minutes=61)


async def test_human_outbound_message_ignores_empty_text_without_touching_pause(_human_outbound_env):
    contact, db = _human_outbound_env
    tenant = SimpleNamespace(id="tid", settings={})
    data = {"chatid": "5511999999999@s.whatsapp.net", "text": "", "messageType": ""}

    await webhooks_module._process_human_outbound_message(tenant, data, request_id=None)

    assert contact.human_takeover_until is None
    assert db.commits == 0


# ---------------------------------------------------------------------------
# _generate_and_send — bails out early while in the takeover window
# ---------------------------------------------------------------------------

class _SingleScalarDB:
    def __init__(self, value):
        self._value = value

    async def scalar(self, *args, **kwargs):
        return self._value

    async def commit(self):
        pass

    async def rollback(self):
        pass


async def test_generate_and_send_skips_when_in_human_takeover(monkeypatch):
    future = datetime.now(timezone.utc) + timedelta(minutes=30)
    contact = SimpleNamespace(id="cid", ai_paused=False, human_takeover_until=future)
    db = _SingleScalarDB(contact)
    monkeypatch.setattr(webhooks_module, "AsyncSessionLocal", _session_factory(db))

    async def _boom(*args, **kwargs):
        raise AssertionError("must not be called while a human is in takeover for this contact")

    monkeypatch.setattr(webhooks_module.ai_service, "generate_reply", _boom)
    monkeypatch.setattr(webhooks_module.wa_service, "send_text_message", _boom)
    monkeypatch.setattr(webhooks_module.wa_service, "mark_messages_as_read", _boom)
    monkeypatch.setattr(webhooks_module, "_collect_unanswered", _boom)

    tenant = SimpleNamespace(id="tid", settings={})

    # No exception means the early return fired before any of the poisoned
    # calls above could be reached.
    await webhooks_module._generate_and_send(
        tenant=tenant,
        contact_id="cid",
        phone="5511999999999",
        instance_token="tok",
        request_id=None,
    )
