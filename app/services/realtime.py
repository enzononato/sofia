"""
In-process pub/sub registry for the Inbox's Server-Sent Events stream
(Wave 4). Same architectural philosophy as app/services/message_batcher.py:
plain module-level dicts, no lock, no Redis — single-worker-only, consistent
with the rest of this app's in-process state (APScheduler, the message
batcher's debounce registry, the in-memory rate limiter).

Safe without a lock for the same reason message_batcher.py's dicts are:
CPython/asyncio only switches tasks at `await` points, and subscribe()
(append)/unsubscribe() (remove)/publish()'s dispatch loop contain no `await`
in between reading and iterating the list, so one call runs atomically with
respect to concurrent calls from other tasks.

INVARIANT (do not violate when adding new publish() call sites): every
published event is a SIGNAL ONLY — `{"type": ..., "contact_id": ...}` — never
the actual message/contact data. The frontend always re-fetches via the
existing REST endpoints on receipt, which already enforce the correct
per-role scope (e.g. a `professional`-role user's own contacts-only scope).
This is what makes dropping an event on a full queue safe: the worst case is
a slightly stale UI until the next event or the polling safety net, never
data loss — Postgres remains the single source of truth.
"""

import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)

# Bounded per-subscriber queue: a stalled/slow client's queue can fill up
# without holding an unbounded amount of memory. Safe to drop (see the
# module-level invariant above) rather than block publish() or grow forever.
_QUEUE_MAXSIZE = 100

# tenant_id -> list of subscriber queues (one per open SSE connection for
# that tenant, possibly across several staff members / browser tabs).
_subscribers: dict[uuid.UUID, list[asyncio.Queue]] = {}


def subscribe(tenant_id: uuid.UUID) -> asyncio.Queue:
    """Register a new subscriber for a tenant. Caller must unsubscribe() in a
    `finally` block to avoid leaking the queue once the connection ends."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    _subscribers.setdefault(tenant_id, []).append(queue)
    return queue


def unsubscribe(tenant_id: uuid.UUID, queue: asyncio.Queue) -> None:
    """Remove a subscriber. No-op if it's already gone (defensive — this may
    be called from a `finally` after an error path that already cleaned up)."""
    queues = _subscribers.get(tenant_id)
    if not queues:
        return
    try:
        queues.remove(queue)
    except ValueError:
        return
    if not queues:
        _subscribers.pop(tenant_id, None)


async def publish(tenant_id: uuid.UUID, event: dict) -> None:
    """
    Fan out `event` to every open subscriber for `tenant_id`. Never raises —
    a full queue is logged and dropped (see module docstring), never blocks
    the caller (this is called from hot paths like the webhook handler).

    Snapshot-copies the subscriber list before iterating so a future change
    that adds an `await` inside this loop (e.g. richer logging) can never
    reintroduce a mutate-during-iterate bug if a subscribe()/unsubscribe()
    happens to interleave.
    """
    for queue in list(_subscribers.get(tenant_id, [])):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(
                "realtime_queue_full_dropping_event",
                extra={"tenant_id": str(tenant_id), "event_type": event.get("type")},
            )


def subscriber_count(tenant_id: uuid.UUID | None = None) -> int:
    """Observability + test hook. Total subscribers across all tenants, or
    just `tenant_id` if given."""
    if tenant_id is not None:
        return len(_subscribers.get(tenant_id, []))
    return sum(len(queues) for queues in _subscribers.values())
