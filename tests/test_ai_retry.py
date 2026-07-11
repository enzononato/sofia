"""
Unit tests for app.services.ai._generate_content_with_retry() — the short
retry added around the Gemini generate_content call (item 1.2 of the
robustness plan) so a transient network/5xx blip doesn't immediately break
Sofia's persona with a robotic "problema técnico" message, and so a fully
exhausted retry raises AIGenerationError instead of returning fallback text
(the caller must stay silent — see AIGenerationError's docstring in ai.py).

Uses a fake Gemini client double (no real network/DB) so this is a true unit
test, matching the "double do cliente Gemini" verification asked for in the
plan.
"""

from types import SimpleNamespace

import pytest

from app.services import ai as ai_module
from app.services.ai import AIGenerationError, _generate_content_with_retry


class _FakeModels:
    """Fake `client.aio.models` — raises `exc_cls` the first `fail_times`
    calls, then returns `success_value`. Records call count."""

    def __init__(self, fail_times: int, exc_cls=RuntimeError, success_value="ok"):
        self.fail_times = fail_times
        self.exc_cls = exc_cls
        self.success_value = success_value
        self.calls = 0

    async def generate_content(self, model, contents, config):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc_cls("transient failure")
        return self.success_value


class _FakeAio:
    def __init__(self, models: _FakeModels):
        self.models = models


class _FakeClient:
    def __init__(self, fail_times: int, exc_cls=RuntimeError, success_value="ok"):
        self.models = _FakeModels(fail_times, exc_cls, success_value)
        self.aio = _FakeAio(self.models)


def _tenant_contact():
    tenant = SimpleNamespace(id="11111111-1111-1111-1111-111111111111")
    contact = SimpleNamespace(id="22222222-2222-2222-2222-222222222222")
    return tenant, contact


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    # Keep tests fast and deterministic regardless of the real default config.
    monkeypatch.setattr(ai_module.settings, "GEMINI_CALL_MAX_RETRIES", 2)
    monkeypatch.setattr(ai_module.settings, "GEMINI_CALL_RETRY_BACKOFF_SECONDS", 0.0)


async def test_transient_failure_recovers_within_retry_budget():
    """Fails once, succeeds on the 2nd attempt — well within the 2-retry budget."""
    client = _FakeClient(fail_times=1, success_value="recovered")
    tenant, contact = _tenant_contact()

    result = await _generate_content_with_retry(
        client, "gemini-2.5-flash", [], object(), tenant, contact, iteration=0
    )

    assert result == "recovered"
    assert client.models.calls == 2


async def test_persistent_failure_raises_ai_generation_error_not_fallback_text():
    """Every attempt fails — must raise AIGenerationError, never return a string
    fallback (that would be sent to the patient as a robotic message)."""
    client = _FakeClient(fail_times=999)  # always raises
    tenant, contact = _tenant_contact()

    with pytest.raises(AIGenerationError):
        await _generate_content_with_retry(
            client, "gemini-2.5-flash", [], object(), tenant, contact, iteration=0
        )

    # max_retries=2 → 3 total attempts (initial + 2 retries), then give up.
    assert client.models.calls == 3


async def test_exhausted_retry_preserves_original_exception_as_cause():
    class _CustomTransientError(RuntimeError):
        pass

    client = _FakeClient(fail_times=999, exc_cls=_CustomTransientError)
    tenant, contact = _tenant_contact()

    with pytest.raises(AIGenerationError) as exc_info:
        await _generate_content_with_retry(
            client, "gemini-2.5-flash", [], object(), tenant, contact, iteration=0
        )

    assert isinstance(exc_info.value.__cause__, _CustomTransientError)


async def test_immediate_success_makes_a_single_call():
    client = _FakeClient(fail_times=0, success_value="first-try")
    tenant, contact = _tenant_contact()

    result = await _generate_content_with_retry(
        client, "gemini-2.5-flash", [], object(), tenant, contact, iteration=0
    )

    assert result == "first-try"
    assert client.models.calls == 1
