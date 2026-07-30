"""
Integration tests for the "Sofia invented a service_id" failure, against a real
Postgres through the real tool executors (no Gemini involved — we call
`execute_tool` directly with the arguments a hallucinating model would send).

Observed in two of the repo's own manual E2E transcripts: `list_services`
returned one id, and the next turn called `check_availability` /
`create_appointment` with a completely different (non-existent) UUID. The
capacity-mode executors used to swallow that — `if svc:` simply didn't match, so
the appointment was created with `service_id = NULL` and the default 60-minute
duration while Sofia told the patient the procedure by name. The clinic ended up
with a booked slot and no procedure attached.

These tests pin the corrected behaviour: an unknown id is rejected and NOTHING
is written.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.services.ai_tools import execute_tool
from tests.integration.conftest import SeededTenant


async def _seed_contact_and_service(db_sessionmaker, tenant_id):
    from app.models.contact import Contact
    from app.models.service import Service

    async with db_sessionmaker() as session:
        contact = Contact(
            tenant_id=tenant_id,
            full_name="Paciente Tools",
            phone=f"+55119{uuid.uuid4().int % 100000000:08d}",
        )
        service = Service(
            tenant_id=tenant_id,
            name="Limpeza de Pele",
            duration_minutes=90,
            is_active=True,
        )
        session.add_all([contact, service])
        await session.commit()
        return contact.id, service.id


async def _appointment_count(db_sessionmaker, tenant_id) -> int:
    from app.models.appointment import Appointment

    async with db_sessionmaker() as session:
        return await session.scalar(
            select(func.count(Appointment.id)).where(Appointment.tenant_id == tenant_id)
        )


def _tomorrow_at_10() -> str:
    d = (datetime.now(timezone.utc) + timedelta(days=1)).date()
    return f"{d.isoformat()}T10:00:00"


async def test_create_appointment_rejects_unknown_service_id_and_writes_nothing(
    db_sessionmaker, tenant_a: SeededTenant
):
    contact_id, _service_id = await _seed_contact_and_service(db_sessionmaker, tenant_a.tenant_id)
    before = await _appointment_count(db_sessionmaker, tenant_a.tenant_id)

    async with db_sessionmaker() as session:
        result = await execute_tool(
            name="create_appointment",
            # A UUID the model made up — well-formed, but not this clinic's.
            args={"scheduled_at": _tomorrow_at_10(), "service_id": str(uuid.uuid4())},
            db=session,
            tenant_id=tenant_a.tenant_id,
            contact_id=contact_id,
            tenant_settings={},
            ai_config={"scheduling_mode": "capacity"},
            tenant_name="Clínica",
        )
        await session.commit()

    assert "error" in result, result
    assert "service_id" in result["error"]
    assert "list_services" in result["error"]  # tells the model how to recover
    # The load-bearing assertion: no half-formed booking was created.
    assert await _appointment_count(db_sessionmaker, tenant_a.tenant_id) == before


async def test_create_appointment_still_works_with_the_real_service_id(
    db_sessionmaker, tenant_a: SeededTenant
):
    from app.models.appointment import Appointment

    contact_id, service_id = await _seed_contact_and_service(db_sessionmaker, tenant_a.tenant_id)

    async with db_sessionmaker() as session:
        result = await execute_tool(
            name="create_appointment",
            args={"scheduled_at": _tomorrow_at_10(), "service_id": str(service_id)},
            db=session,
            tenant_id=tenant_a.tenant_id,
            contact_id=contact_id,
            tenant_settings={},
            ai_config={"scheduling_mode": "capacity"},
            tenant_name="Clínica",
        )
        await session.commit()

    assert result.get("success") is True, result

    async with db_sessionmaker() as session:
        appt = (
            await session.execute(
                select(Appointment).where(
                    Appointment.tenant_id == tenant_a.tenant_id,
                    Appointment.contact_id == contact_id,
                )
            )
        ).scalars().first()
    assert appt is not None
    assert appt.service_id == service_id
    # Duration comes from the service (90 min), not the 60-minute default.
    assert (appt.ends_at - appt.scheduled_at) == timedelta(minutes=90)


async def test_check_availability_rejects_unknown_service_id(
    db_sessionmaker, tenant_a: SeededTenant
):
    contact_id, _ = await _seed_contact_and_service(db_sessionmaker, tenant_a.tenant_id)
    target = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()

    async with db_sessionmaker() as session:
        result = await execute_tool(
            name="check_availability",
            args={"date": target, "service_id": str(uuid.uuid4())},
            db=session,
            tenant_id=tenant_a.tenant_id,
            contact_id=contact_id,
            tenant_settings={},
            ai_config={"scheduling_mode": "capacity"},
            tenant_name="Clínica",
        )

    assert "error" in result, result
    assert "service_id" in result["error"]
