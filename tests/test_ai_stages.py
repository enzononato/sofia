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


# ── Financial policies injected on every turn (always-on, not tool-gated) ────
# A live test showed Sofia inventing an evaluation price / saying "gratuita" when
# it was paid, because the policy lived only in get_clinic_info (often not
# called). It must now appear in the context block itself.

def _policy_block(clinic: dict) -> str:
    return build_context_block(
        _contact(), Stage.FIRST_CONTACT, [], tenant_settings={"clinic": clinic}
    )


def test_context_block_always_has_policies_section():
    block = _policy_block({})
    assert "POLÍTICAS DA CLÍNICA" in block


def test_context_block_evaluation_unset_says_not_configured():
    block = _policy_block({})
    assert "NÃO configurada" in block or "NÃO afirme" in block


def test_context_block_evaluation_paid_deductible_is_verbatim():
    block = _policy_block(
        {"evaluation_fee_mode": "paid", "evaluation_fee": 100, "evaluation_fee_deductible": True}
    )
    assert "100" in block
    assert "ABATIDO" in block or "abat" in block.lower()
    # And must NOT say it's free.
    assert "gratuita" not in block.lower().split("POLÍTICAS DA CLÍNICA", 1)[-1]


def test_context_block_evaluation_free_says_free():
    block = _policy_block({"evaluation_fee_mode": "free"})
    assert "GRATUITA" in block or "gratuita" in block.lower()


def test_context_block_installments_unset_warns_not_configured():
    block = _policy_block({})
    assert "Parcelamento não configurado" in block


def test_context_block_installments_configured_shows_number():
    block = _policy_block({"max_installments": 6})
    assert "6x" in block
