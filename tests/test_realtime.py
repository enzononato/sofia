"""
Unit tests for app/services/realtime.py — the in-process SSE pub/sub
registry. Pure asyncio, no DB, no HTTP.
"""

import asyncio
import uuid

from app.services import realtime


def _tid() -> uuid.UUID:
    return uuid.uuid4()


class TestSubscribeUnsubscribe:
    def test_subscribe_registers_a_queue(self):
        tenant = _tid()
        try:
            q = realtime.subscribe(tenant)
            assert realtime.subscriber_count(tenant) == 1
            assert isinstance(q, asyncio.Queue)
        finally:
            realtime.unsubscribe(tenant, q)

    def test_unsubscribe_removes_it(self):
        tenant = _tid()
        q = realtime.subscribe(tenant)
        realtime.unsubscribe(tenant, q)
        assert realtime.subscriber_count(tenant) == 0

    def test_unsubscribe_is_a_noop_if_already_gone(self):
        tenant = _tid()
        q = realtime.subscribe(tenant)
        realtime.unsubscribe(tenant, q)
        realtime.unsubscribe(tenant, q)  # must not raise
        assert realtime.subscriber_count(tenant) == 0

    def test_multiple_subscribers_same_tenant(self):
        tenant = _tid()
        q1 = realtime.subscribe(tenant)
        q2 = realtime.subscribe(tenant)
        try:
            assert realtime.subscriber_count(tenant) == 2
        finally:
            realtime.unsubscribe(tenant, q1)
            realtime.unsubscribe(tenant, q2)
        assert realtime.subscriber_count(tenant) == 0

    def test_subscriber_count_without_tenant_sums_all(self):
        tenant_a, tenant_b = _tid(), _tid()
        qa = realtime.subscribe(tenant_a)
        qb = realtime.subscribe(tenant_b)
        before = realtime.subscriber_count()
        try:
            assert realtime.subscriber_count() >= 2
        finally:
            realtime.unsubscribe(tenant_a, qa)
            realtime.unsubscribe(tenant_b, qb)
        assert realtime.subscriber_count() == before - 2


class TestPublish:
    async def test_publish_delivers_to_subscriber(self):
        tenant = _tid()
        q = realtime.subscribe(tenant)
        try:
            await realtime.publish(tenant, {"type": "message", "contact_id": "abc"})
            event = q.get_nowait()
            assert event == {"type": "message", "contact_id": "abc"}
        finally:
            realtime.unsubscribe(tenant, q)

    async def test_publish_reaches_all_subscribers_of_that_tenant(self):
        tenant = _tid()
        q1 = realtime.subscribe(tenant)
        q2 = realtime.subscribe(tenant)
        try:
            await realtime.publish(tenant, {"type": "contact_updated", "contact_id": "x"})
            assert q1.get_nowait() == {"type": "contact_updated", "contact_id": "x"}
            assert q2.get_nowait() == {"type": "contact_updated", "contact_id": "x"}
        finally:
            realtime.unsubscribe(tenant, q1)
            realtime.unsubscribe(tenant, q2)

    async def test_publish_does_not_leak_across_tenants(self):
        tenant_a, tenant_b = _tid(), _tid()
        qa = realtime.subscribe(tenant_a)
        qb = realtime.subscribe(tenant_b)
        try:
            await realtime.publish(tenant_a, {"type": "message", "contact_id": "only-a"})
            assert qa.get_nowait() == {"type": "message", "contact_id": "only-a"}
            assert qb.empty()
        finally:
            realtime.unsubscribe(tenant_a, qa)
            realtime.unsubscribe(tenant_b, qb)

    async def test_publish_with_no_subscribers_is_a_safe_noop(self):
        tenant = _tid()
        await realtime.publish(tenant, {"type": "message", "contact_id": "nobody-listening"})
        # No assertion beyond "did not raise" — there's nothing to check.

    async def test_publish_drops_silently_when_queue_is_full(self):
        tenant = _tid()
        q = realtime.subscribe(tenant)
        try:
            for i in range(realtime._QUEUE_MAXSIZE):
                await realtime.publish(tenant, {"type": "message", "contact_id": str(i)})
            # Queue is now full — one more publish must not raise.
            await realtime.publish(tenant, {"type": "message", "contact_id": "overflow"})
            assert q.qsize() == realtime._QUEUE_MAXSIZE
        finally:
            realtime.unsubscribe(tenant, q)
