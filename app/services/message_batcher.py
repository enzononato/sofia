"""
In-process message batcher (debounce) for WhatsApp replies.

Goal: when a contact fires several messages in quick succession, wait until they
"stop typing" before replying once — so Sofia answers the whole burst instead of
each fragment separately.

Design:
  - A registry maps contact_id -> the pending asyncio sleeper Task.
  - schedule() (re)starts the debounce: any existing timer for that contact is
    cancelled and a new one is created (so a new inbound resets the window).
  - When the window elapses, the work coroutine runs once. The work re-reads the
    unanswered messages from the DB, so it doesn't matter which inbound's callback
    actually fires — they're all equivalent.
  - flush() runs the work immediately (used for media, which shouldn't wait).

Single-worker assumption: this state is per-process, consistent with the
in-process APScheduler and rate limiter. Multi-worker would need a shared store
(e.g. Redis). Pending timers are lost on restart, but the inbound messages were
already persisted in Phase 1 — only the auto-reply is skipped.
"""

import asyncio
import logging
import time
import uuid
from typing import Awaitable, Callable

from app.config import settings
from app.services.humanizer import batch_window_seconds

logger = logging.getLogger(__name__)

WorkFn = Callable[[], Awaitable[None]]

# contact_id -> sleeper task
_pending: dict[uuid.UUID, asyncio.Task] = {}

# typing_key (e.g. "{tenant_id}:{phone}") -> monotonic deadline until which the
# contact is considered "still typing". Fed by PRESENCE_UPDATE webhook events.
_typing_until: dict[str, float] = {}


def mark_typing(key: str, hold_seconds: float) -> None:
    """Record that a contact is actively composing; the debounce will wait for them
    to stop (capped) before replying. Refreshed on each composing/recording/paused
    event. Never shortens an existing hold — extends to the later deadline."""
    deadline = time.monotonic() + hold_seconds
    current = _typing_until.get(key)
    if current is None or deadline > current:
        _typing_until[key] = deadline


def clear_typing(key: str) -> None:
    """Contact stopped typing / went available — drop any hold."""
    _typing_until.pop(key, None)


def _is_typing(key: str | None) -> bool:
    if not key:
        return False
    until = _typing_until.get(key)
    if until is None:
        return False
    if until <= time.monotonic():
        _typing_until.pop(key, None)
        return False
    return True


def _cancel_existing(contact_id: uuid.UUID) -> None:
    task = _pending.pop(contact_id, None)
    if task is not None and not task.done():
        task.cancel()


async def _debounced_run(
    contact_id: uuid.UUID, work: WorkFn, delay: float, typing_key: str | None
) -> None:
    try:
        await asyncio.sleep(delay)

        # Presence-aware hold: if the contact is still typing (composing/recording
        # events keep refreshing the flag), wait for them to stop before replying,
        # so Sofia answers the whole burst — like a human would. Capped so a stuck
        # "typing" state can never hang the reply indefinitely.
        if settings.PRESENCE_TYPING_ENABLED and _is_typing(typing_key):
            hold_started = time.monotonic()
            while _is_typing(typing_key):
                if time.monotonic() - hold_started > settings.TYPING_MAX_HOLD_SECONDS:
                    break
                await asyncio.sleep(settings.TYPING_POLL_SECONDS)
    except asyncio.CancelledError:
        # Superseded by a newer message — that newer schedule owns the reply.
        return

    # Guard against a race where a newer task replaced us without cancellation.
    if _pending.get(contact_id) is not asyncio.current_task():
        return
    _pending.pop(contact_id, None)

    try:
        await work()
    except Exception:
        logger.exception("batch_work_failed", extra={"contact_id": str(contact_id)})


def schedule(contact_id: uuid.UUID, work: WorkFn, typing_key: str | None = None) -> None:
    """
    Start (or restart) the debounce window for a contact. When the window
    elapses without a new message (and the contact isn't actively typing),
    `work` runs once.

    `typing_key` ties this debounce to PRESENCE_UPDATE events so the reply is
    held while the contact keeps typing. If batching is disabled, `work` is
    dispatched immediately (no debounce).
    """
    if not settings.MESSAGE_BATCHING_ENABLED:
        asyncio.create_task(_run_now(contact_id, work))
        return

    _cancel_existing(contact_id)
    delay = batch_window_seconds()
    task = asyncio.create_task(_debounced_run(contact_id, work, delay, typing_key))
    _pending[contact_id] = task
    logger.debug(
        "batch_scheduled", extra={"contact_id": str(contact_id), "delay_s": round(delay, 2)}
    )


async def flush(contact_id: uuid.UUID, work: WorkFn) -> None:
    """
    Cancel any pending debounce for the contact and run `work` immediately.
    Used for media messages, which should be answered without waiting.
    """
    _cancel_existing(contact_id)
    try:
        await work()
    except Exception:
        logger.exception("batch_flush_failed", extra={"contact_id": str(contact_id)})


async def _run_now(contact_id: uuid.UUID, work: WorkFn) -> None:
    try:
        await work()
    except Exception:
        logger.exception("batch_run_now_failed", extra={"contact_id": str(contact_id)})


def pending_count() -> int:
    """Number of contacts currently waiting in a debounce window (observability)."""
    return sum(1 for t in _pending.values() if not t.done())
