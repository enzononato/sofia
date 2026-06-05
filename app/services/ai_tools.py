"""
Gemini Tool Use — ferramentas da secretária executiva.

Cada ferramenta tem duas partes:
  1. FunctionDeclaration  — schema que o Gemini usa para saber quando e como chamar
  2. Executor             — lógica Python que roda quando a IA decide acionar a tool

Segurança: tenant_id e contact_id vêm sempre do contexto da requisição.
A IA não pode injetar esses valores — qualquer campo com esses nomes nos args é ignorado.
"""

import logging
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google.genai import types
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.service import Service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool declarations (schema sent to Gemini)
# ---------------------------------------------------------------------------

_list_services_decl = types.FunctionDeclaration(
    name="list_services",
    description=(
        "Lista todos os serviços / procedimentos ativos oferecidos pela clínica, "
        "incluindo nome, duração em minutos e preço. Use quando o paciente perguntar "
        "o que a clínica oferece ou antes de verificar disponibilidade."
    ),
    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
)

_check_availability_decl = types.FunctionDeclaration(
    name="check_availability",
    description=(
        "Verifica os horários disponíveis para agendamento em uma data específica. "
        "Retorna uma lista de slots livres (formato HH:MM). "
        "Use assim que o paciente mencionar uma data ou pedir para agendar."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "date": types.Schema(
                type=types.Type.STRING,
                description="Data desejada no formato YYYY-MM-DD",
            ),
            "service_id": types.Schema(
                type=types.Type.STRING,
                description="UUID do serviço (opcional). Se informado, considera a duração do serviço.",
            ),
        },
        required=["date"],
    ),
)

_create_appointment_decl = types.FunctionDeclaration(
    name="create_appointment",
    description=(
        "Cria um agendamento para o paciente atual. "
        "Use somente após confirmar o horário com o paciente. "
        "Retorna confirmação com id e horário agendado."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "scheduled_at": types.Schema(
                type=types.Type.STRING,
                description="Data e hora do agendamento em formato ISO 8601 (ex: 2025-05-10T14:00:00)",
            ),
            "service_id": types.Schema(
                type=types.Type.STRING,
                description="UUID do serviço agendado (opcional mas recomendado)",
            ),
            "notes": types.Schema(
                type=types.Type.STRING,
                description="Observações adicionais sobre o agendamento (opcional)",
            ),
        },
        required=["scheduled_at"],
    ),
)

_get_upcoming_appointments_decl = types.FunctionDeclaration(
    name="get_upcoming_appointments",
    description=(
        "Retorna os próximos agendamentos do paciente que está conversando agora. "
        "Use quando o paciente perguntar sobre seus agendamentos, quiser remarcar ou cancelar."
    ),
    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
)

_cancel_appointment_decl = types.FunctionDeclaration(
    name="cancel_appointment",
    description=(
        "Cancela um agendamento do paciente atual. "
        "Use somente após o paciente confirmar que deseja cancelar. "
        "Retorna confirmação do cancelamento."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "appointment_id": types.Schema(
                type=types.Type.STRING,
                description="UUID do agendamento a ser cancelado",
            ),
            "reason": types.Schema(
                type=types.Type.STRING,
                description="Motivo do cancelamento (opcional)",
            ),
        },
        required=["appointment_id"],
    ),
)

_reschedule_appointment_decl = types.FunctionDeclaration(
    name="reschedule_appointment",
    description=(
        "Remarca um agendamento existente do paciente atual para uma nova data/hora. "
        "Use quando o paciente quiser mudar o horário de um agendamento (em vez de cancelar e criar de novo). "
        "Antes de remarcar, use check_availability para confirmar que o novo horário está livre."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "appointment_id": types.Schema(
                type=types.Type.STRING,
                description="UUID do agendamento a remarcar",
            ),
            "new_scheduled_at": types.Schema(
                type=types.Type.STRING,
                description="Nova data e hora em ISO 8601 (ex: 2025-05-12T15:30:00)",
            ),
            "new_service_id": types.Schema(
                type=types.Type.STRING,
                description="UUID do novo serviço (opcional — só se o paciente quiser trocar de serviço)",
            ),
        },
        required=["appointment_id", "new_scheduled_at"],
    ),
)

_get_clinic_info_decl = types.FunctionDeclaration(
    name="get_clinic_info",
    description=(
        "Retorna informações da clínica: endereço, telefone, email, horário de funcionamento, "
        "formas de pagamento, instagram e outras informações cadastradas. "
        "Use sempre que o paciente perguntar sobre localização, contato, horário, valores ou formas de pagamento."
    ),
    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
)

_update_contact_info_decl = types.FunctionDeclaration(
    name="update_contact_info",
    description=(
        "Atualiza dados cadastrais do paciente atual. Use quando o paciente fornecer "
        "espontaneamente seu nome completo, email, data de nascimento ou endereço. "
        "Só atualize campos que o paciente acabou de informar — não invente valores."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "full_name": types.Schema(
                type=types.Type.STRING,
                description="Nome completo do paciente",
            ),
            "email": types.Schema(
                type=types.Type.STRING,
                description="Email do paciente",
            ),
            "date_of_birth": types.Schema(
                type=types.Type.STRING,
                description="Data de nascimento no formato YYYY-MM-DD",
            ),
            "address": types.Schema(
                type=types.Type.STRING,
                description="Endereço completo",
            ),
        },
    ),
)

# Single Tool object bundling all declarations
CLINIC_TOOLS = types.Tool(
    function_declarations=[
        _list_services_decl,
        _check_availability_decl,
        _create_appointment_decl,
        _get_upcoming_appointments_decl,
        _cancel_appointment_decl,
        _reschedule_appointment_decl,
        _get_clinic_info_decl,
        _update_contact_info_decl,
    ]
)

# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

async def execute_tool(
    name: str,
    args: dict,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    tenant_settings: dict | None = None,
) -> dict:
    """
    Dispatch a Gemini function call to the appropriate handler.
    tenant_id and contact_id are ALWAYS taken from the request context — never from args.
    tenant_settings is passed through for schedule-aware tools (check_availability).
    """
    logger.info("Executing tool '%s' args=%s tenant=%s", name, args, tenant_id)

    if name == "list_services":
        return await _list_services(db, tenant_id)

    if name == "check_availability":
        return await _check_availability(db, tenant_id, tenant_settings or {}, args)

    if name == "create_appointment":
        return await _create_appointment(db, tenant_id, contact_id, args)

    if name == "get_upcoming_appointments":
        return await _get_upcoming_appointments(db, tenant_id, contact_id)

    if name == "cancel_appointment":
        return await _cancel_appointment(db, tenant_id, contact_id, args)

    if name == "reschedule_appointment":
        return await _reschedule_appointment(db, tenant_id, contact_id, args)

    if name == "get_clinic_info":
        return await _get_clinic_info(tenant_settings or {})

    if name == "update_contact_info":
        return await _update_contact_info(db, tenant_id, contact_id, args)

    return {"error": f"Unknown tool: {name}"}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def _list_services(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    result = await db.execute(
        select(Service).where(
            Service.tenant_id == tenant_id,
            Service.is_active == True,  # noqa: E712
        ).order_by(Service.name)
    )
    services = result.scalars().all()
    return {
        "services": [
            {
                "id": str(s.id),
                "name": s.name,
                "duration_minutes": s.duration_minutes,
                "price": str(s.price) if s.price is not None else None,
                "description": s.description,
            }
            for s in services
        ]
    }


async def _check_availability(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    tenant_settings: dict,
    args: dict,
) -> dict:
    """
    Returns available slots for a given date, respecting:
      - Clinic timezone (schedule.timezone)
      - Working days (schedule.working_days, ISO weekday: Mon=1, Sun=7)
      - Business hours (schedule.open_time / close_time)
      - Lunch break (schedule.lunch_start / lunch_end) — optional
      - Slot grid granularity (schedule.slot_granularity_minutes) — optional
      - Real service duration for the requested service
      - Overlap detection using actual appointment windows, not just start times

    tenant.settings shape (all fields optional — sensible defaults apply):
    {
      "schedule": {
        "timezone": "America/Sao_Paulo",   # default: "UTC"
        "working_days": [1, 2, 3, 4, 5],  # Mon–Fri; ISO weekday 1=Mon 7=Sun
        "open_time": "08:00",
        "close_time": "18:00",
        "lunch_start": "12:00",            # omit to disable lunch break
        "lunch_end":   "13:00",
        "slot_granularity_minutes": 30     # grid step; default = service duration
      }
    }
    """
    try:
        target_date = date.fromisoformat(args["date"])
    except (KeyError, ValueError):
        return {"error": "Formato de data inválido. Use YYYY-MM-DD."}

    # ── Schedule config with defaults ────────────────────────────────────────
    schedule = tenant_settings.get("schedule", {})

    tz_name: str = schedule.get("timezone", "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        logger.warning("Invalid timezone '%s' for tenant %s — falling back to UTC", tz_name, tenant_id)
        tz = ZoneInfo("UTC")

    working_days: list[int] = schedule.get("working_days", [1, 2, 3, 4, 5])

    # Closed day — return early before any DB work
    if target_date.isoweekday() not in working_days:
        return {
            "date": args["date"],
            "available_slots": [],
            "message": "A clínica não atende neste dia da semana.",
        }

    try:
        open_t = time.fromisoformat(schedule.get("open_time", "08:00"))
        close_t = time.fromisoformat(schedule.get("close_time", "18:00"))
    except ValueError:
        open_t, close_t = time(8, 0), time(18, 0)

    lunch_range: tuple[datetime, datetime] | None = None
    if schedule.get("lunch_start") and schedule.get("lunch_end"):
        try:
            lunch_range = (
                datetime.combine(target_date, time.fromisoformat(schedule["lunch_start"]), tzinfo=tz),
                datetime.combine(target_date, time.fromisoformat(schedule["lunch_end"]), tzinfo=tz),
            )
        except ValueError:
            pass

    # ── Service duration for the requested service ────────────────────────────
    slot_minutes = 60
    service_id_str = args.get("service_id")
    if service_id_str:
        try:
            svc_result = await db.execute(
                select(Service).where(
                    Service.id == uuid.UUID(service_id_str),
                    Service.tenant_id == tenant_id,
                )
            )
            svc = svc_result.scalar_one_or_none()
            if svc:
                slot_minutes = svc.duration_minutes
        except ValueError:
            pass

    slot_dur = timedelta(minutes=slot_minutes)

    # Grid step: configurable granularity or falls back to service duration
    try:
        granularity_minutes = int(schedule.get("slot_granularity_minutes", slot_minutes))
    except (TypeError, ValueError):
        granularity_minutes = slot_minutes
    granularity_dur = timedelta(minutes=granularity_minutes)

    # ── Booked appointments for the target day ────────────────────────────────
    day_open = datetime.combine(target_date, open_t, tzinfo=tz)
    day_close = datetime.combine(target_date, close_t, tzinfo=tz)

    result = await db.execute(
        select(Appointment).where(
            Appointment.tenant_id == tenant_id,
            Appointment.scheduled_at >= day_open,
            Appointment.scheduled_at < day_close,
            Appointment.status != AppointmentStatus.CANCELLED,
        )
    )
    booked = result.scalars().all()

    # Batch-fetch service durations for booked appointments (avoids N+1)
    booked_service_ids = {a.service_id for a in booked if a.service_id}
    service_durations: dict[uuid.UUID, int] = {}
    if booked_service_ids:
        svcs = await db.execute(select(Service).where(Service.id.in_(booked_service_ids)))
        service_durations = {s.id: s.duration_minutes for s in svcs.scalars().all()}

    # Build real (start, end) windows in clinic timezone
    booked_ranges: list[tuple[datetime, datetime]] = []
    for appt in booked:
        start = appt.scheduled_at.astimezone(tz)
        if appt.ends_at:
            end = appt.ends_at.astimezone(tz)
        elif appt.service_id and appt.service_id in service_durations:
            end = start + timedelta(minutes=service_durations[appt.service_id])
        else:
            end = start + timedelta(minutes=60)  # conservative fallback
        booked_ranges.append((start, end))

    # ── Generate available slots ──────────────────────────────────────────────
    available: list[str] = []
    cursor = day_open

    while cursor + slot_dur <= day_close:
        slot_end = cursor + slot_dur

        # Reject if the slot window overlaps the lunch break
        if lunch_range and cursor < lunch_range[1] and slot_end > lunch_range[0]:
            cursor += granularity_dur
            continue

        # Reject if the slot window overlaps any booked appointment
        if any(cursor < end and slot_end > start for start, end in booked_ranges):
            cursor += granularity_dur
            continue

        available.append(cursor.strftime("%H:%M"))
        cursor += granularity_dur

    if not available:
        return {
            "date": args["date"],
            "available_slots": [],
            "message": "Não há horários disponíveis nesta data.",
        }

    return {"date": args["date"], "available_slots": available, "timezone": tz_name}


async def _create_appointment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    args: dict,
) -> dict:
    try:
        scheduled_at = datetime.fromisoformat(args["scheduled_at"])
        # Ensure timezone-aware
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return {"error": "Formato de data/hora inválido. Use ISO 8601."}

    service_id: uuid.UUID | None = None
    service_id_str = args.get("service_id")
    if service_id_str:
        try:
            candidate = uuid.UUID(service_id_str)
            # Validate that service belongs to the tenant
            svc_result = await db.execute(
                select(Service).where(
                    Service.id == candidate, Service.tenant_id == tenant_id
                )
            )
            if svc_result.scalar_one_or_none():
                service_id = candidate
        except ValueError:
            pass  # invalid UUID — ignore silently

    appointment = Appointment(
        tenant_id=tenant_id,   # context — IA cannot override
        contact_id=contact_id,  # context — IA cannot override
        service_id=service_id,
        scheduled_at=scheduled_at,
        status=AppointmentStatus.SCHEDULED,
        notes=args.get("notes"),
    )
    db.add(appointment)
    await db.flush()  # get the ID without committing (caller commits)

    logger.info(
        "Appointment created by AI tool: id=%s tenant=%s contact=%s scheduled_at=%s",
        appointment.id,
        tenant_id,
        contact_id,
        scheduled_at,
    )

    return {
        "success": True,
        "appointment_id": str(appointment.id),
        "scheduled_at": scheduled_at.isoformat(),
        "status": AppointmentStatus.SCHEDULED,
    }


async def _get_upcoming_appointments(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
) -> dict:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Appointment).where(
            Appointment.tenant_id == tenant_id,
            Appointment.contact_id == contact_id,
            Appointment.scheduled_at >= now,
            Appointment.status != AppointmentStatus.CANCELLED,
        ).order_by(Appointment.scheduled_at).limit(5)
    )
    appointments = result.scalars().all()

    if not appointments:
        return {"appointments": [], "message": "Nenhum agendamento futuro encontrado."}

    return {
        "appointments": [
            {
                "id": str(a.id),
                "scheduled_at": a.scheduled_at.isoformat(),
                "status": a.status,
                "service_id": str(a.service_id) if a.service_id else None,
            }
            for a in appointments
        ]
    }


async def _cancel_appointment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    args: dict,
) -> dict:
    try:
        appointment_id = uuid.UUID(args["appointment_id"])
    except (KeyError, ValueError):
        return {"error": "appointment_id inválido."}

    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.tenant_id == tenant_id,   # tenant scope — IA cannot cross tenants
            Appointment.contact_id == contact_id,  # contact scope — IA cannot cancel other patients' appointments
            Appointment.status != AppointmentStatus.CANCELLED,
        )
    )
    appointment = result.scalar_one_or_none()

    if appointment is None:
        return {"error": "Agendamento não encontrado ou já cancelado."}

    appointment.status = AppointmentStatus.CANCELLED
    appointment.cancellation_reason = args.get("reason") or "Cancelado pelo paciente via chat"
    await db.flush()

    logger.info(
        "Appointment cancelled by AI tool: id=%s tenant=%s contact=%s",
        appointment.id,
        tenant_id,
        contact_id,
    )

    return {
        "success": True,
        "appointment_id": str(appointment.id),
        "scheduled_at": appointment.scheduled_at.isoformat(),
        "message": "Agendamento cancelado com sucesso.",
    }


async def _reschedule_appointment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    args: dict,
) -> dict:
    """
    Atomic reschedule: change scheduled_at (and optionally service) of an existing
    appointment. Tenant + contact scope enforced from context — AI cannot reschedule
    other patients' appointments.
    """
    try:
        appointment_id = uuid.UUID(args["appointment_id"])
    except (KeyError, ValueError):
        return {"error": "appointment_id inválido."}

    try:
        new_scheduled_at = datetime.fromisoformat(args["new_scheduled_at"])
        if new_scheduled_at.tzinfo is None:
            new_scheduled_at = new_scheduled_at.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return {"error": "Formato de new_scheduled_at inválido. Use ISO 8601."}

    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.tenant_id == tenant_id,
            Appointment.contact_id == contact_id,
            Appointment.status != AppointmentStatus.CANCELLED,
        )
    )
    appointment = result.scalar_one_or_none()
    if appointment is None:
        return {"error": "Agendamento não encontrado ou já cancelado."}

    new_service_id_str = args.get("new_service_id")
    if new_service_id_str:
        try:
            candidate = uuid.UUID(new_service_id_str)
            svc_result = await db.execute(
                select(Service).where(
                    Service.id == candidate, Service.tenant_id == tenant_id
                )
            )
            svc = svc_result.scalar_one_or_none()
            if svc:
                appointment.service_id = candidate
                # Recompute ends_at when service (and thus duration) changes
                appointment.ends_at = new_scheduled_at + timedelta(minutes=svc.duration_minutes)
        except ValueError:
            pass  # invalid UUID — silently ignore (keep old service)

    appointment.scheduled_at = new_scheduled_at
    # If we didn't recompute ends_at via service change, recompute from existing service
    if appointment.ends_at is None or new_service_id_str is None:
        if appointment.service_id:
            svc_result = await db.execute(
                select(Service).where(Service.id == appointment.service_id)
            )
            svc = svc_result.scalar_one_or_none()
            if svc:
                appointment.ends_at = new_scheduled_at + timedelta(minutes=svc.duration_minutes)

    await db.flush()

    logger.info(
        "Appointment rescheduled by AI tool: id=%s tenant=%s contact=%s new_at=%s",
        appointment.id, tenant_id, contact_id, new_scheduled_at,
    )

    return {
        "success": True,
        "appointment_id": str(appointment.id),
        "scheduled_at": appointment.scheduled_at.isoformat(),
        "service_id": str(appointment.service_id) if appointment.service_id else None,
        "message": "Agendamento remarcado com sucesso.",
    }


async def _get_clinic_info(tenant_settings: dict) -> dict:
    """
    Return the clinic-info block from tenant.settings.clinic plus the schedule.
    Returns sane defaults when fields are missing — never errors.
    """
    clinic = tenant_settings.get("clinic", {}) or {}
    schedule = tenant_settings.get("schedule", {}) or {}

    return {
        "address": clinic.get("address"),
        "phone": clinic.get("phone"),
        "email": clinic.get("email"),
        "instagram": clinic.get("instagram"),
        "payment_methods": clinic.get("payment_methods", []),
        "additional_info": clinic.get("additional_info"),
        "schedule": {
            "timezone": schedule.get("timezone", "UTC"),
            "working_days": schedule.get("working_days", [1, 2, 3, 4, 5]),
            "open_time": schedule.get("open_time", "08:00"),
            "close_time": schedule.get("close_time", "18:00"),
            "lunch_start": schedule.get("lunch_start"),
            "lunch_end": schedule.get("lunch_end"),
        },
    }


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UPDATABLE_FIELDS = {"full_name", "email", "date_of_birth", "address"}


async def _update_contact_info(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    args: dict,
) -> dict:
    """
    Update whitelisted fields on the current contact. Validation:
      - Only fields in _UPDATABLE_FIELDS are accepted (phone/status/ai_paused never).
      - email must match a basic format.
      - date_of_birth must be ISO YYYY-MM-DD.
      - tenant_id + contact_id come from context — AI can never edit another patient.
    """
    result = await db.execute(
        select(Contact).where(
            Contact.id == contact_id,
            Contact.tenant_id == tenant_id,
        )
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        return {"error": "Contato não encontrado."}

    updated: dict[str, str] = {}
    rejected: dict[str, str] = {}

    for field, raw_value in args.items():
        if field not in _UPDATABLE_FIELDS:
            rejected[field] = "campo não permitido"
            continue
        if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
            continue
        value = raw_value.strip() if isinstance(raw_value, str) else raw_value

        if field == "email":
            if not _EMAIL_RE.match(value):
                rejected[field] = "formato de email inválido"
                continue
            contact.email = value
            updated[field] = value

        elif field == "date_of_birth":
            try:
                contact.date_of_birth = date.fromisoformat(value)
                updated[field] = value
            except ValueError:
                rejected[field] = "data inválida (use YYYY-MM-DD)"

        elif field == "full_name":
            contact.full_name = value
            updated[field] = value

        elif field == "address":
            contact.address = value
            updated[field] = value

    if not updated:
        return {"success": False, "rejected": rejected, "message": "Nenhum campo válido para atualizar."}

    await db.flush()

    logger.info(
        "Contact updated by AI tool: contact=%s tenant=%s fields=%s",
        contact_id, tenant_id, list(updated.keys()),
    )

    return {
        "success": True,
        "updated": updated,
        "rejected": rejected,
        "message": "Cadastro atualizado.",
    }
