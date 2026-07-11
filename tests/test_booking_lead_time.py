"""
Unit tests for the "never offer/accept a past time slot" rules in
app.services.ai_tools:
  - _generate_day_slots(): pure slot-grid generator (capacity mode).
  - _slots_in_blocks(): pure slot-grid generator (per-professional mode).
  - _earliest_bookable_start(): today needs a lead-time floor, future dates don't.
  - _reject_if_past(): booking creation/reschedule can't target a past instant.

All pure functions — no DB, no Gemini, no wall-clock reliance (a fixed
`now_local` is always passed in), matching the pattern used in
test_history_markers.py / test_ai_stages.py.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.ai_tools import (
    _earliest_bookable_start,
    _generate_day_slots,
    _reject_if_past,
    _slots_in_blocks,
)

_TZ = ZoneInfo("America/Sao_Paulo")


def _dt(hour, minute=0, day=6):
    return datetime(2026, 7, day, hour, minute, tzinfo=_TZ)


# ── _earliest_bookable_start ─────────────────────────────────────────────────

def test_earliest_bookable_start_none_for_future_date():
    today = _dt(16, 0).date()
    future_date = _dt(16, 0, day=8).date()
    now_local = _dt(16, 0)
    assert _earliest_bookable_start(future_date, now_local, 30) is None


def test_earliest_bookable_start_adds_lead_time_for_today():
    now_local = _dt(16, 0)
    earliest = _earliest_bookable_start(now_local.date(), now_local, 30)
    assert earliest == now_local + timedelta(minutes=30)


# ── _generate_day_slots (capacity mode) ──────────────────────────────────────

def test_generate_day_slots_no_earliest_returns_full_grid():
    day_open = _dt(8, 0)
    day_close = _dt(12, 0)
    slots = _generate_day_slots(
        day_open, day_close, None, [], timedelta(hours=1), timedelta(hours=1), capacity=1,
    )
    assert slots == ["08:00", "09:00", "10:00", "11:00"]


def test_generate_day_slots_hides_past_slots_today():
    # It's 16:00 — a same-day availability check must not return 09:00/10:00.
    day_open = _dt(8, 0)
    day_close = _dt(18, 0)
    now_local = _dt(16, 0)
    earliest = now_local + timedelta(minutes=30)  # 16:30
    slots = _generate_day_slots(
        day_open, day_close, None, [], timedelta(hours=1), timedelta(hours=1), capacity=1,
        earliest=earliest,
    )
    assert "09:00" not in slots
    assert "10:00" not in slots
    assert "16:00" not in slots  # starts before the 16:30 lead-time floor
    assert "17:00" in slots


def test_generate_day_slots_future_date_unaffected_by_earliest_none():
    day_open = _dt(8, 0, day=10)
    day_close = _dt(12, 0, day=10)
    slots = _generate_day_slots(
        day_open, day_close, None, [], timedelta(hours=1), timedelta(hours=1), capacity=1,
        earliest=None,
    )
    assert slots == ["08:00", "09:00", "10:00", "11:00"]


def test_generate_day_slots_respects_capacity_and_lunch():
    day_open = _dt(8, 0)
    day_close = _dt(14, 0)
    lunch = (_dt(12, 0), _dt(13, 0))
    booked = [(_dt(9, 0), _dt(10, 0))]
    slots = _generate_day_slots(
        day_open, day_close, lunch, booked, timedelta(hours=1), timedelta(hours=1), capacity=1,
    )
    assert "09:00" not in slots  # booked
    assert "12:00" not in slots  # lunch
    assert "13:00" in slots


# ── _slots_in_blocks (per-professional mode) ─────────────────────────────────

def test_slots_in_blocks_hides_past_slots_today():
    now_local = _dt(16, 0)
    earliest = now_local + timedelta(minutes=30)
    blocks = [(_dt(8, 0), _dt(18, 0))]
    slots = _slots_in_blocks(blocks, [], timedelta(hours=1), timedelta(hours=1), earliest=earliest)
    hhmm = [s.strftime("%H:%M") for s in slots]
    assert "09:00" not in hhmm
    assert "16:00" not in hhmm
    assert "17:00" in hhmm


def test_slots_in_blocks_no_earliest_full_grid():
    blocks = [(_dt(8, 0), _dt(11, 0))]
    slots = _slots_in_blocks(blocks, [], timedelta(hours=1), timedelta(hours=1))
    hhmm = [s.strftime("%H:%M") for s in slots]
    assert hhmm == ["08:00", "09:00", "10:00"]


# ── _reject_if_past (booking creation / reschedule) ──────────────────────────

def test_reject_if_past_rejects_clearly_past_start():
    now_local = _dt(16, 0)
    start = _dt(9, 0)
    msg = _reject_if_past(start, now_local)
    assert msg is not None
    assert "passou" in msg.lower()


def test_reject_if_past_allows_future_start():
    now_local = _dt(16, 0)
    start = _dt(17, 0)
    assert _reject_if_past(start, now_local) is None


def test_reject_if_past_tolerates_small_clock_skew():
    # Start is 2 minutes "in the past" — within the default 5-minute tolerance.
    now_local = _dt(16, 0)
    start = now_local - timedelta(minutes=2)
    assert _reject_if_past(start, now_local) is None


def test_reject_if_past_rejects_beyond_tolerance():
    now_local = _dt(16, 0)
    start = now_local - timedelta(minutes=10)
    assert _reject_if_past(start, now_local) is not None
