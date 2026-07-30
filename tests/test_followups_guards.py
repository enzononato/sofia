"""
Pure unit tests for the proactive-send guards in app/services/followups.py —
the module that fires REAL WhatsApp messages from the scheduler and had zero
test coverage until now.

Covers the two failure modes found in the audit:
  1. reminders/re-engagement talking over a paused contact or a human who is
     mid-conversation, and firing outside the clinic's opening hours (the job
     interval is anchored to process boot, so a 21h deploy lands at 03h local);
  2. a reminder addressing the patient by their raw phone number, because
     `Contact.full_name` falls back to the phone when WhatsApp exposes no push
     name — and picking a "bom dia!" template at 3pm.

No DB and no network: every function under test is pure.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.services import followups

SP = ZoneInfo("America/Sao_Paulo")


def _tenant(**settings_overrides):
    settings = {
        "schedule": {
            "open_time": "08:00",
            "close_time": "18:00",
            "working_days": [1, 2, 3, 4, 5],
        }
    }
    settings.update(settings_overrides)
    return SimpleNamespace(id=uuid.uuid4(), name="Clínica Teste", settings=settings)


def _contact(*, full_name="Maria Silva", phone="+5511987654321", ai_paused=False, takeover=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        full_name=full_name,
        phone=phone,
        ai_paused=ai_paused,
        human_takeover_until=takeover,
    )


def _at(hour: int, minute: int = 0, *, day: int = 15) -> datetime:
    """A UTC instant corresponding to the given clinic-local (São Paulo) time.
    2026-07-15 is a Wednesday (a working day under the default schedule)."""
    return datetime(2026, 7, day, hour, minute, tzinfo=SP).astimezone(timezone.utc)


class TestCanSendProactive:
    def test_allows_a_normal_contact_during_business_hours(self):
        assert followups.can_send_proactive(_tenant(), _contact(), _at(10)) is True

    def test_blocks_a_paused_contact(self):
        assert followups.can_send_proactive(_tenant(), _contact(ai_paused=True), _at(10)) is False

    def test_blocks_while_a_human_is_handling_the_conversation(self):
        now = _at(10)
        contact = _contact(takeover=now + timedelta(minutes=30))
        assert followups.can_send_proactive(_tenant(), contact, now) is False

    def test_allows_once_the_human_takeover_window_expired(self):
        now = _at(10)
        contact = _contact(takeover=now - timedelta(minutes=1))
        assert followups.can_send_proactive(_tenant(), contact, now) is True

    def test_blocks_in_the_middle_of_the_night(self):
        # The regression this guards: a deploy at 21h anchors the interval job so
        # it fires at 03h local. A "human secretary" texting at 3am is the loudest
        # possible tell that she is not one.
        assert followups.can_send_proactive(_tenant(), _contact(), _at(3)) is False

    def test_blocks_before_opening_and_after_closing(self):
        assert followups.can_send_proactive(_tenant(), _contact(), _at(7, 59)) is False
        assert followups.can_send_proactive(_tenant(), _contact(), _at(18, 0)) is False

    def test_blocks_on_a_non_working_day(self):
        # 2026-07-19 is a Sunday; default working_days is Mon-Fri.
        assert followups.can_send_proactive(_tenant(), _contact(), _at(10, day=19)) is False

    def test_explicit_send_window_overrides_opening_hours(self):
        tenant = _tenant(followups={"send_window": {"start": "09:00", "end": "20:00"}})
        assert followups.can_send_proactive(tenant, _contact(), _at(19)) is True
        assert followups.can_send_proactive(tenant, _contact(), _at(8, 30)) is False

    def test_unparseable_window_falls_back_to_opening_hours(self):
        tenant = _tenant(followups={"send_window": {"start": "nonsense", "end": "??"}})
        assert followups.can_send_proactive(tenant, _contact(), _at(10)) is True
        assert followups.can_send_proactive(tenant, _contact(), _at(3)) is False


class TestDisplayName:
    def test_returns_first_name_for_a_real_name(self):
        assert followups._display_name(_contact(full_name="Maria Silva")) == "Maria"

    def test_empty_when_the_name_is_the_raw_phone_number(self):
        # webhooks._find_or_create_contact seeds full_name = phone when WhatsApp
        # exposes no push name — this is what produced "Olá, 5511987654321!".
        assert followups._display_name(_contact(full_name="5511987654321")) == ""

    def test_empty_when_name_equals_the_contact_phone_field(self):
        c = _contact(full_name="+5511987654321", phone="+5511987654321")
        assert followups._display_name(c) == ""

    def test_empty_when_there_is_no_name_at_all(self):
        assert followups._display_name(_contact(full_name="")) == ""

    def test_keeps_names_that_merely_contain_digits(self):
        assert followups._display_name(_contact(full_name="Ana 2")) == "Ana"


class TestReminderText:
    def test_never_addresses_the_patient_by_phone_number(self):
        # Every template must survive an empty name without leaving a dangling
        # comma or interpolating the phone.
        for _ in range(60):
            text = followups._reminder_text("", "Clínica X", "quinta às 10h", _at(10).astimezone(SP))
            assert "5511" not in text
            assert not text.startswith(",")
            assert "{name}" not in text

    def test_uses_the_first_name_when_available(self):
        text = followups._reminder_text("Maria", "Clínica X", "quinta às 10h", _at(10).astimezone(SP))
        assert "Maria" in text

    def test_never_says_bom_dia_in_the_afternoon(self):
        for _ in range(60):
            text = followups._reminder_text("Maria", "Clínica X", "quinta às 10h", _at(15).astimezone(SP))
            assert "bom dia" not in text.lower()

    def test_bom_dia_is_still_reachable_in_the_morning(self):
        seen = {
            followups._reminder_text("Maria", "Clínica X", "quinta às 10h", _at(9).astimezone(SP))
            for _ in range(200)
        }
        assert any("bom dia" in t.lower() for t in seen)

    def test_templates_actually_vary(self):
        seen = {
            followups._reminder_text("Maria", "Clínica X", "quinta às 10h", _at(10).astimezone(SP))
            for _ in range(200)
        }
        assert len(seen) > 1

    def test_works_without_a_clock_reference(self):
        text = followups._reminder_text("Maria", "Clínica X", "quinta às 10h")
        assert "Maria" in text and "Clínica X" in text
