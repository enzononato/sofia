"""
Tests for the SSE real-time Inbox stream (Wave 4,
app/api/v1/routes/events.py + app/services/realtime.py).

────────────────────────────────────────────────────────────────────────────
WHY THE EVENT-DELIVERY TESTS DON'T GO THROUGH client.stream(...)
────────────────────────────────────────────────────────────────────────────
Discovered while writing this file: `httpx.ASGITransport.handle_async_request`
(venv/Lib/site-packages/httpx/_transports/asgi.py) does `await self.app(scope,
receive, send)` and only returns a `Response` once that call fully completes
— it accumulates every `http.response.body` chunk and asserts
`response_complete.is_set()` (set only when a message with `more_body=False`
arrives) before constructing the `Response` object. In other words:
**ASGITransport cannot expose partial/incremental output from a still-running
ASGI call — it buffers until the app is completely done.**

Our SSE generator (`_event_stream`) runs an intentional `while True` loop and
only finishes when the client disconnects. Over ASGITransport that's a
deadlock: the transport won't return ANY data (not even the first
": connected" line) until the app returns, and the app won't return until the
transport tells it the client disconnected — which it never does mid-call.
Confirmed empirically: a `client.stream(...)` reader hung indefinitely on
`connected.wait()` even though a real end-to-end manual test (uvicorn +
curl, see the commit introducing this file) proved the real server handles
subscribe → publish → disconnect cleanup correctly in ~1-3s.

This is a genuine limitation of this test transport, not of the SSE
implementation — so the event-delivery/tenant-isolation/cleanup-on-disconnect
tests below exercise `_event_stream()` (the exact async generator the real
route uses) DIRECTLY, driven by a minimal fake Request whose
`is_disconnected()` we control, bypassing only the HTTP/ASGI transport layer
(never bypassing the actual production code under test). The ticket-auth
tests (fail fast, no streaming) DO go through the real HTTP layer via
`client` — those complete quickly since the ASGI call returns immediately on
a 401, which ASGITransport handles fine.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from app.api.v1.routes.events import _event_stream
from app.services import realtime


class _FakeRequest:
    """Minimal stand-in for fastapi.Request — _event_stream only calls
    `await request.is_disconnected()`."""

    def __init__(self) -> None:
        self.disconnected = False

    async def is_disconnected(self) -> bool:
        return self.disconnected


async def test_event_stream_delivers_published_event():
    tenant_id = uuid.uuid4()
    gen = _event_stream(tenant_id, _FakeRequest())

    connected = asyncio.Event()
    received: dict = {}

    async def _consume():
        async for line in gen:
            if line.startswith(": connected"):
                connected.set()
                continue
            if line.startswith("data:"):
                received["event"] = json.loads(line.removeprefix("data:").strip())
                return

    task = asyncio.create_task(_consume())
    await asyncio.wait_for(connected.wait(), timeout=2)

    await realtime.publish(tenant_id, {"type": "message", "contact_id": "abc-123"})

    await asyncio.wait_for(task, timeout=2)
    assert received["event"] == {"type": "message", "contact_id": "abc-123"}
    await gen.aclose()  # _consume() returned early (didn't exhaust the generator)


async def test_event_stream_isolates_tenants():
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    gen_a = _event_stream(tenant_a, _FakeRequest())
    gen_b = _event_stream(tenant_b, _FakeRequest())

    connected_a, connected_b = asyncio.Event(), asyncio.Event()
    received_a: dict = {}

    async def _consume(gen, connected_evt, sink: dict | None):
        async for line in gen:
            if line.startswith(": connected"):
                connected_evt.set()
                continue
            if line.startswith("data:") and sink is not None:
                sink["event"] = json.loads(line.removeprefix("data:").strip())
                return

    task_a = asyncio.create_task(_consume(gen_a, connected_a, received_a))
    task_b = asyncio.create_task(_consume(gen_b, connected_b, None))
    await asyncio.wait_for(connected_a.wait(), timeout=2)
    await asyncio.wait_for(connected_b.wait(), timeout=2)

    await realtime.publish(tenant_a, {"type": "message", "contact_id": "only-a"})

    await asyncio.wait_for(task_a, timeout=2)
    assert received_a["event"] == {"type": "message", "contact_id": "only-a"}
    await gen_a.aclose()  # _consume() returned early (didn't exhaust the generator)

    # Tenant B's reader must NOT have received anything — assert it's still
    # running rather than waiting for it to time out (cheaper, and doesn't
    # depend on picking a "long enough" timeout for a negative assertion).
    assert not task_b.done()
    task_b.cancel()
    try:
        await task_b
    except asyncio.CancelledError:
        pass
    await gen_b.aclose()


async def test_event_stream_unsubscribes_on_disconnect():
    tenant_id = uuid.uuid4()
    fake_request = _FakeRequest()
    gen = _event_stream(tenant_id, fake_request)
    baseline = realtime.subscriber_count(tenant_id)

    connected = asyncio.Event()

    async def _consume():
        async for line in gen:
            if line.startswith(": connected"):
                connected.set()
            # Keep reading until cancelled — simulates a client holding the
            # connection open until it disconnects.

    task = asyncio.create_task(_consume())
    await asyncio.wait_for(connected.wait(), timeout=2)
    assert realtime.subscriber_count(tenant_id) == baseline + 1

    # Cancelling the consuming task injects CancelledError at the generator's
    # current suspension point (inside _event_stream's `await queue.get()`),
    # which propagates through its `finally: unsubscribe()` — the same code
    # path that fires on a real client disconnect.
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    for _ in range(50):
        if realtime.subscriber_count(tenant_id) == baseline:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("subscriber was not cleaned up after disconnect within ~2.5s")


async def test_event_stream_rejects_missing_or_invalid_ticket(client):
    resp = await client.get("/events/stream", params={"ticket": "not-a-real-ticket"})
    assert resp.status_code == 401


async def test_ticket_endpoint_requires_normal_auth(client):
    """POST /events/ticket is NOT in the tenant-middleware bypass list — only
    the exact GET /events/stream path is — so it must still require the usual
    Authorization + X-Tenant-ID headers."""
    resp = await client.post("/events/ticket")
    assert resp.status_code == 401
