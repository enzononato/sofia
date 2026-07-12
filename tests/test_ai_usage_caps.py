"""
Unit tests for app.api.v1.routes.webhooks._ai_usage_caps_allow_reply() (item
1.7 / D3 of the robustness plan — daily AI usage caps, ON by default since D3
via AI_USAGE_LIMITS_ENABLED).

Covers, without a real DB session (a fake session that returns queued
`scalar()` values and counts `commit()` calls):
  - the disabled fast path (flag off): returns True without touching the DB;
  - the per-contact cap: trips `contact.ai_paused` and fires
    `send_handoff_alert_email` (fire-and-forget via asyncio.create_task) with
    a clear reason, exactly once per pause episode (not on every subsequent
    capped message);
  - the per-tenant cap: trips `tenant.settings["ai_paused"]` and fires the
    dedicated `send_tenant_usage_cap_alert_email` (no single Contact applies
    tenant-wide — see app/services/alerts.py for why that's a separate
    function rather than widening send_handoff_alert_email's signature);
  - the allow path when both counts are under their caps.

The full enabled path was ALSO verified manually end-to-end against the local
dev Postgres (real Tenant/Contact/Message rows, real commits, mocked email
senders) — see the final summary for the exact scenarios exercised.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.api.v1.routes import webhooks as webhooks_module


class _ExplodingDB:
    """Any DB access here is a bug — the disabled fast path must never query."""

    async def scalar(self, *args, **kwargs):
        raise AssertionError("must not query the DB when AI_USAGE_LIMITS_ENABLED is False")

    async def commit(self, *args, **kwargs):
        raise AssertionError("must not commit when AI_USAGE_LIMITS_ENABLED is False")


class _QueueDB:
    """Fake AsyncSession: `scalar()` returns the next queued value in order
    (matching the two sequential calls _ai_usage_caps_allow_reply makes —
    contact count first, tenant count second, when it gets that far).
    Counts commit() calls; never actually touches a DB."""

    def __init__(self, values):
        self._values = list(values)
        self.commits = 0

    async def scalar(self, *args, **kwargs):
        return self._values.pop(0)

    async def commit(self):
        self.commits += 1


def _tenant(**overrides):
    defaults = dict(
        id="11111111-1111-1111-1111-111111111111",
        name="Clinica Teste",
        email="clinica@example.com",
        settings={},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _contact(**overrides):
    defaults = dict(
        id="22222222-2222-2222-2222-222222222222",
        ai_paused=False,
        full_name="Paciente Teste",
        phone="5511999999999",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture(autouse=True)
def _disabled_by_default(monkeypatch):
    # Baseline for every test in this file; tests that exercise the enabled
    # path override this explicitly (see below) — monkeypatch lets later
    # setattr calls in the test body win, and always restores after the test.
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_LIMITS_ENABLED", False)


async def test_disabled_by_default_allows_reply_without_touching_db():
    allowed = await webhooks_module._ai_usage_caps_allow_reply(
        _ExplodingDB(), _tenant(), _contact(), {}
    )
    assert allowed is True


def test_tenant_ai_paused_reads_settings_flag():
    assert webhooks_module._tenant_ai_paused(SimpleNamespace(settings={"ai_paused": True})) is True
    assert webhooks_module._tenant_ai_paused(SimpleNamespace(settings={"ai_paused": False})) is False
    assert webhooks_module._tenant_ai_paused(SimpleNamespace(settings={})) is False
    assert webhooks_module._tenant_ai_paused(SimpleNamespace(settings=None)) is False


async def test_contact_cap_exceeded_pauses_contact_and_dispatches_alert(monkeypatch):
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_LIMITS_ENABLED", True)
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_CAP_PER_CONTACT_DAILY", 2)
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_CAP_PER_TENANT_DAILY", 999)

    calls = []

    async def _fake_alert(tenant, contact, reason):
        calls.append((tenant, contact, reason))

    monkeypatch.setattr(webhooks_module, "send_handoff_alert_email", _fake_alert)

    tenant = _tenant()
    contact = _contact()
    db = _QueueDB([2])  # contact_count = 2 >= cap(2) — trips before any tenant query

    allowed = await webhooks_module._ai_usage_caps_allow_reply(db, tenant, contact, {})

    assert allowed is False
    assert contact.ai_paused is True
    assert db.commits == 1

    await asyncio.sleep(0)  # let the fire-and-forget asyncio.create_task run
    assert len(calls) == 1
    got_tenant, got_contact, got_reason = calls[0]
    assert got_tenant is tenant
    assert got_contact is contact
    assert "Limite diário" in got_reason


async def test_contact_cap_exceeded_does_not_re_alert_once_already_paused(monkeypatch):
    # A contact already paused by a previous cap trip must not fire a second
    # email (or a second commit) on every subsequent message that day.
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_LIMITS_ENABLED", True)
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_CAP_PER_CONTACT_DAILY", 2)
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_CAP_PER_TENANT_DAILY", 999)

    calls = []

    async def _fake_alert(tenant, contact, reason):
        calls.append((tenant, contact, reason))

    monkeypatch.setattr(webhooks_module, "send_handoff_alert_email", _fake_alert)

    contact = _contact(ai_paused=True)
    db = _QueueDB([5])

    allowed = await webhooks_module._ai_usage_caps_allow_reply(db, _tenant(), contact, {})

    assert allowed is False
    assert db.commits == 0
    await asyncio.sleep(0)
    assert calls == []


async def test_tenant_cap_exceeded_pauses_tenant_and_dispatches_alert(monkeypatch):
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_LIMITS_ENABLED", True)
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_CAP_PER_CONTACT_DAILY", 999)
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_CAP_PER_TENANT_DAILY", 3)

    calls = []

    async def _fake_tenant_alert(tenant, count, cap):
        calls.append((tenant, count, cap))

    monkeypatch.setattr(webhooks_module, "send_tenant_usage_cap_alert_email", _fake_tenant_alert)

    tenant = _tenant()
    contact = _contact()
    db = _QueueDB([0, 3])  # contact_count under cap, tenant_count = 3 >= cap(3)

    allowed = await webhooks_module._ai_usage_caps_allow_reply(db, tenant, contact, {})

    assert allowed is False
    assert contact.ai_paused is False  # only the TENANT is paused, not this contact
    assert tenant.settings.get("ai_paused") is True
    assert db.commits == 1

    await asyncio.sleep(0)
    assert len(calls) == 1
    got_tenant, got_count, got_cap = calls[0]
    assert got_tenant is tenant
    assert got_count == 3
    assert got_cap == 3


async def test_tenant_cap_exceeded_does_not_re_alert_once_already_paused(monkeypatch):
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_LIMITS_ENABLED", True)
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_CAP_PER_CONTACT_DAILY", 999)
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_CAP_PER_TENANT_DAILY", 3)

    calls = []

    async def _fake_tenant_alert(tenant, count, cap):
        calls.append((tenant, count, cap))

    monkeypatch.setattr(webhooks_module, "send_tenant_usage_cap_alert_email", _fake_tenant_alert)

    tenant = _tenant(settings={"ai_paused": True})
    db = _QueueDB([0, 10])

    allowed = await webhooks_module._ai_usage_caps_allow_reply(db, tenant, _contact(), {})

    assert allowed is False
    assert db.commits == 0
    await asyncio.sleep(0)
    assert calls == []


async def test_under_both_caps_allows_reply_without_pausing_or_alerting(monkeypatch):
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_LIMITS_ENABLED", True)
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_CAP_PER_CONTACT_DAILY", 40)
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_CAP_PER_TENANT_DAILY", 400)

    tenant = _tenant()
    contact = _contact()
    db = _QueueDB([1, 10])

    allowed = await webhooks_module._ai_usage_caps_allow_reply(db, tenant, contact, {})

    assert allowed is True
    assert contact.ai_paused is False
    assert db.commits == 0
