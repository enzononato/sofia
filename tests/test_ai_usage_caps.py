"""
Unit test for the disabled-by-default fast path of
app.api.v1.routes.webhooks._ai_usage_caps_allow_reply() (item 1.7 of the
robustness plan — AI usage caps, OFF by default via AI_USAGE_LIMITS_ENABLED).

This is the one behavior of that function testable without a real DB session:
when the feature flag is off (the shipped default), the function must return
True WITHOUT touching the database at all — proven here with a fake session
that raises if any of its methods are called. The counting/pausing logic
itself (enabled path) needs a real AsyncSession and was verified manually
against the local dev Postgres — see the final summary for the exact
scenarios exercised (contact cap trips ai_paused, tenant cap trips the
tenant-wide flag, cleanup afterward).
"""

from types import SimpleNamespace

import pytest

from app.api.v1.routes import webhooks as webhooks_module


class _ExplodingDB:
    """Any DB access here is a bug — the disabled fast path must never query."""

    async def scalar(self, *args, **kwargs):
        raise AssertionError("must not query the DB when AI_USAGE_LIMITS_ENABLED is False")

    async def commit(self, *args, **kwargs):
        raise AssertionError("must not commit when AI_USAGE_LIMITS_ENABLED is False")


@pytest.fixture(autouse=True)
def _disabled(monkeypatch):
    monkeypatch.setattr(webhooks_module.settings, "AI_USAGE_LIMITS_ENABLED", False)


async def test_disabled_by_default_allows_reply_without_touching_db():
    tenant = SimpleNamespace(id="11111111-1111-1111-1111-111111111111", settings={})
    contact = SimpleNamespace(id="22222222-2222-2222-2222-222222222222", ai_paused=False)

    allowed = await webhooks_module._ai_usage_caps_allow_reply(
        _ExplodingDB(), tenant, contact, {}
    )

    assert allowed is True


def test_tenant_ai_paused_reads_settings_flag():
    assert webhooks_module._tenant_ai_paused(SimpleNamespace(settings={"ai_paused": True})) is True
    assert webhooks_module._tenant_ai_paused(SimpleNamespace(settings={"ai_paused": False})) is False
    assert webhooks_module._tenant_ai_paused(SimpleNamespace(settings={})) is False
    assert webhooks_module._tenant_ai_paused(SimpleNamespace(settings=None)) is False
