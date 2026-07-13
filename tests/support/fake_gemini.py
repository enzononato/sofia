"""
Shared fake Gemini client for tests that need a SEQUENCE of distinct canned
responses within one logical operation (e.g. the multi-agent orchestrator's
router call, then a specialist call, then maybe a Handoff call).

Distinct from tests/test_ai_retry.py's `_FakeClient`, which intentionally
only supports "fail N times then return one fixed value" — correct for
testing the low-level retry helper, but not for testing code that makes
several DIFFERENT Gemini calls in sequence.

Mirrors the real `google.genai.Client.aio.models.generate_content(model,
contents, config)` call shape and the response attributes actually read by
app/services/ai.py / app/services/agents/*: `response.candidates[0].content.parts`,
`part.function_call.{name,args}`, `part.text`, `response.text`,
`candidate.finish_reason`.
"""

from types import SimpleNamespace
from typing import Any


def fake_text(text: str) -> SimpleNamespace:
    """A response with a single plain-text part — no function call."""
    part = SimpleNamespace(function_call=None, text=text)
    content = SimpleNamespace(parts=[part], role="model")
    candidate = SimpleNamespace(content=content, finish_reason="STOP")
    return SimpleNamespace(candidates=[candidate], text=text)


def fake_function_call(name: str, args: dict[str, Any] | None = None) -> SimpleNamespace:
    """A response whose single part is a function call — no text."""
    fc = SimpleNamespace(name=name, args=dict(args or {}))
    part = SimpleNamespace(function_call=fc, text=None)
    content = SimpleNamespace(parts=[part], role="model")
    candidate = SimpleNamespace(content=content, finish_reason="STOP")
    return SimpleNamespace(candidates=[candidate], text=None)


def fake_empty() -> SimpleNamespace:
    """A response with no usable parts at all (simulates MAX_TOKENS/safety-block)."""
    candidate = SimpleNamespace(content=None, finish_reason="MAX_TOKENS")
    return SimpleNamespace(candidates=[candidate], text=None)


class _SequencedModels:
    def __init__(self, responses: list):
        self._queue = list(responses)
        self.calls: list[dict] = []

    async def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if not self._queue:
            raise AssertionError(
                f"SequencedFakeClient exhausted after {len(self.calls)} call(s) — "
                "the code under test made more Gemini calls than the test scripted. "
                "This usually means an unexpected extra hop (router/specialist/handoff) "
                "happened — the exact failure mode this fake exists to catch."
            )
        item = self._queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _SequencedAio:
    def __init__(self, models: _SequencedModels):
        self.models = models


class SequencedFakeClient:
    """
    A fake `genai.Client` that returns a pre-scripted queue of responses, one
    per call, in order. Raises AssertionError if exhausted (see
    _SequencedModels.generate_content) rather than silently reusing the last
    response — an orchestrator bug that makes an unscripted extra call must
    fail loudly, not be masked.

    `responses` items may be a SimpleNamespace built by fake_text/
    fake_function_call/fake_empty above, or an Exception instance (raised
    instead of returned) to simulate a transient/permanent failure at that
    point in the sequence.

    `client.models.calls` records every call's (model, contents, config) for
    assertions on what was actually sent (e.g. system_instruction, tools).
    """

    def __init__(self, responses: list):
        self.models = _SequencedModels(responses)
        self.aio = _SequencedAio(self.models)
