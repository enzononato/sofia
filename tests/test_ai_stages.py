"""
Unit tests for app.services.ai_stages.build_context_block().

No DB access — Contact/Appointment are plain in-memory SQLAlchemy model
instances (never flushed), and build_context_block() only reads attributes.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.services.ai_stages import Stage, build_context_block

# Same pt-BR weekday names build_context_block uses internally (Monday=0 .. Sunday=6).
_WEEKDAYS_PT = [
    "Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
    "Sexta-feira", "Sábado", "Domingo",
]

_CALENDAR_LINE_RE = re.compile(
    r"^(?P<weekday>\S+) \((?P<when>[^)]*)\) -> date=(?P<date>\d{4}-\d{2}-\d{2})\s+\[\d{2}/\d{2}/\d{4}\]$"
)


def _contact(**overrides) -> Contact:
    defaults = dict(
        full_name="Ana Paciente",
        whatsapp_name=None,
        status="active",
        crm_stage="new_lead",
        email=None,
        phone=None,
        date_of_birth=None,
    )
    defaults.update(overrides)
    return Contact(**defaults)


def test_missing_timezone_falls_back_to_sao_paulo_never_utc():
    block = build_context_block(_contact(), Stage.FIRST_CONTACT, [], tenant_settings={"schedule": {}})
    assert "(fuso America/Sao_Paulo)" in block
    assert "(fuso UTC)" not in block


def test_calendar_table_has_14_lines_with_matching_weekday_and_date():
    block = build_context_block(_contact(), Stage.FIRST_CONTACT, [], tenant_settings={"schedule": {}})

    calendar_lines = [
        line for line in block.splitlines() if _CALENDAR_LINE_RE.match(line)
    ]
    assert len(calendar_lines) == 14

    for line in calendar_lines:
        m = _CALENDAR_LINE_RE.match(line)
        assert m is not None
        weekday_name = m.group("weekday")
        date_str = m.group("date")
        expected_weekday = _WEEKDAYS_PT[datetime.strptime(date_str, "%Y-%m-%d").weekday()]
        assert weekday_name == expected_weekday, f"line {line!r} has mismatched weekday"


def test_no_upcoming_appointment_omits_proximo_agendamento():
    now = datetime.now(timezone.utc)
    past_appt = Appointment(
        id=uuid.uuid4(),
        scheduled_at=now - timedelta(days=2),
        status=AppointmentStatus.COMPLETED,
    )
    block = build_context_block(_contact(), Stage.ACTIVE_PATIENT, [past_appt], tenant_settings={"schedule": {}})
    assert "Próximo agendamento" not in block

    block_empty = build_context_block(_contact(), Stage.FIRST_CONTACT, [], tenant_settings={"schedule": {}})
    assert "Próximo agendamento" not in block_empty


def test_upcoming_non_cancelled_appointment_included_with_id():
    now = datetime.now(timezone.utc)
    future_appt = Appointment(
        id=uuid.uuid4(),
        scheduled_at=now + timedelta(days=1),
        status=AppointmentStatus.SCHEDULED,
    )
    block = build_context_block(
        _contact(), Stage.RETURNING_LEAD, [future_appt], tenant_settings={"schedule": {}}
    )
    assert "Próximo agendamento" in block
    assert str(future_appt.id) in block


def test_upcoming_cancelled_appointment_is_ignored():
    now = datetime.now(timezone.utc)
    cancelled_appt = Appointment(
        id=uuid.uuid4(),
        scheduled_at=now + timedelta(days=1),
        status=AppointmentStatus.CANCELLED,
    )
    block = build_context_block(
        _contact(), Stage.RETURNING_LEAD, [cancelled_appt], tenant_settings={"schedule": {}}
    )
    assert "Próximo agendamento" not in block
