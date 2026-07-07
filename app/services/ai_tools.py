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
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact, CrmStage
from app.models.professional import ProfessionalWorkHours, professional_services
from app.models.service import Service
from app.models.user import User
from app.services import crm

logger = logging.getLogger(__name__)

# Scheduling modes (tenant.ai_config["scheduling_mode"]):
#   "capacity"         — Fase 1: N parallel appointments per clinic (settings.schedule.capacity)
#   "per_professional" — Fase 3: availability + booking are per professional
SCHEDULING_CAPACITY = "capacity"
SCHEDULING_PER_PROFESSIONAL = "per_professional"

# ---------------------------------------------------------------------------
# Tool declarations (schema sent to Gemini)
# ---------------------------------------------------------------------------

_list_services_decl = types.FunctionDeclaration(
    name="list_services",
    description=(
        "Lista todos os serviços / procedimentos ativos oferecidos pela clínica, "
        "incluindo nome, duração em minutos e preço. O preço retornado é sempre "
        "por consulta/sessão avulsa — nunca um pacote fechado ou tratamento completo. "
        "Ao informar valores ao paciente, deixe claro que o preço é por consulta. "
        "Se o campo price vier nulo (null) para um serviço, a clínica NÃO tem valor fixo "
        "tabelado para ele — nunca invente um número nem estime um valor; diga ao paciente "
        "que esse valor é avaliado e informado durante a consulta presencial. "
        "Use quando o paciente perguntar o que a clínica oferece ou antes de "
        "verificar disponibilidade."
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
                description="UUID do serviço. Necessário quando a clínica agenda por profissional.",
            ),
            "professional_id": types.Schema(
                type=types.Type.STRING,
                description="UUID do profissional (opcional). Use para ver a agenda de um profissional específico.",
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
                description="UUID do serviço agendado (recomendado; obrigatório quando a clínica agenda por profissional)",
            ),
            "professional_id": types.Schema(
                type=types.Type.STRING,
                description=(
                    "UUID do profissional escolhido. Informe quando o paciente escolher o profissional. "
                    "Se houver só um profissional disponível no horário, pode omitir que o sistema atribui."
                ),
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
            "new_professional_id": types.Schema(
                type=types.Type.STRING,
                description="UUID do novo profissional (opcional — só se o paciente quiser trocar de profissional)",
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

_list_professionals_decl = types.FunctionDeclaration(
    name="list_professionals",
    description=(
        "Lista os profissionais da clínica e quais serviços cada um realiza. "
        "Use quando o paciente perguntar quem atende, pedir um profissional específico, "
        "ou quando precisar apresentar opções de profissional para um serviço."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "service_id": types.Schema(
                type=types.Type.STRING,
                description="UUID do serviço (opcional). Se informado, lista só quem realiza esse serviço.",
            ),
        },
    ),
)

_set_crm_stage_decl = types.FunctionDeclaration(
    name="set_crm_stage",
    description=(
        "Classifica/atualiza o estágio do paciente no funil de CRM (Kanban) com base na conversa. "
        "O paciente começa em 'new_lead' (não classificado) e é você quem deve qualificá-lo assim "
        "que a conversa der sinal suficiente. Estágios válidos: "
        "'hot_lead' (LEAD QUENTE — demonstrou interesse claro: perguntou preço/horário, quer marcar, "
        "está decidindo, responde com entusiasmo); "
        "'cold_lead' (LEAD FRIO — pouco engajado: só pesquisando, evasivo, 'depois eu vejo', "
        "sumindo nas respostas, sem intenção clara ainda); "
        "'lost' (PERDIDO — disse claramente que não tem interesse / não quer mais); "
        "'post_care' (já foi atendido e está em acompanhamento). "
        "Reclassifique quando a temperatura mudar (ex.: um cold_lead que volta animado vira hot_lead). "
        "NÃO use para 'scheduled'/'attended' — esses são definidos automaticamente ao agendar/concluir. "
        "Não invente: só classifique com base no que a conversa realmente indicar. "
        "IMPORTANTE: classificar é uma ação silenciosa de registro interno — não muda o que você fala "
        "com o paciente. Sempre que a mensagem dele der um sinal claro de frio/quente/perdido, chame "
        "esta ferramenta NA MESMA resposta, mesmo que você também vá fazer uma pergunta de sondagem ou "
        "tratar uma objeção no texto — as duas coisas acontecem juntas, uma não substitui a outra."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "stage": types.Schema(
                type=types.Type.STRING,
                description="Novo estágio: hot_lead | cold_lead | post_care | lost",
            ),
            "reason": types.Schema(
                type=types.Type.STRING,
                description="Motivo curto da mudança (ex: 'perguntou preço e horário, quer marcar').",
            ),
        },
        required=["stage"],
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
        _list_professionals_decl,
        _set_crm_stage_decl,
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
    ai_config: dict | None = None,
    tenant_name: str | None = None,
) -> dict:
    """
    Dispatch a Gemini function call to the appropriate handler.
    tenant_id and contact_id are ALWAYS taken from the request context — never from args.
    tenant_settings is passed through for schedule-aware tools; ai_config selects the
    scheduling mode (capacity vs per_professional); tenant_name labels clinic info.
    """
    logger.info("Executing tool '%s' args=%s tenant=%s", name, args, tenant_id)

    settings_ = tenant_settings or {}
    # Per-professional scheduling is the DEFAULT (absence of the key = on). A clinic
    # can still switch to capacity explicitly in Settings → AI. Safety net: if the
    # clinic hasn't linked any service to a professional yet, fall back to capacity
    # so Sofia can still book during initial setup instead of finding no bookable
    # services (per-professional hides services nobody performs).
    mode = (ai_config or {}).get("scheduling_mode") or SCHEDULING_PER_PROFESSIONAL
    per_prof = mode == SCHEDULING_PER_PROFESSIONAL
    if per_prof and not await _tenant_has_professional_setup(db, tenant_id):
        per_prof = False

    if name == "list_services":
        return await _list_services(db, tenant_id, per_prof)

    if name == "check_availability":
        if per_prof:
            return await _check_availability_pp(db, tenant_id, settings_, args)
        return await _check_availability(db, tenant_id, settings_, args)

    if name == "create_appointment":
        if per_prof:
            return await _create_appointment_pp(db, tenant_id, contact_id, settings_, args)
        return await _create_appointment(db, tenant_id, contact_id, settings_, args)

    if name == "get_upcoming_appointments":
        return await _get_upcoming_appointments(db, tenant_id, contact_id, settings_)

    if name == "cancel_appointment":
        return await _cancel_appointment(db, tenant_id, contact_id, args)

    if name == "reschedule_appointment":
        if per_prof:
            return await _reschedule_appointment_pp(db, tenant_id, contact_id, settings_, args)
        return await _reschedule_appointment(db, tenant_id, contact_id, settings_, args)

    if name == "get_clinic_info":
        return await _get_clinic_info(settings_, tenant_name)

    if name == "update_contact_info":
        return await _update_contact_info(db, tenant_id, contact_id, args)

    if name == "list_professionals":
        return await _list_professionals(db, tenant_id, args)

    if name == "set_crm_stage":
        return await _set_crm_stage(db, tenant_id, contact_id, args)

    return {"error": f"Unknown tool: {name}"}


# ---------------------------------------------------------------------------
# Scheduling helpers (shared by availability + booking validation)
# ---------------------------------------------------------------------------

_DEFAULT_SLOT_MINUTES = 60


# This is a Brazil-only clinic SaaS. Defaulting an unconfigured clinic to UTC
# made every date roll over to "tomorrow" after 21h local — e.g. at 23:32 in
# Brazil the AI announced the next calendar day. America/Sao_Paulo (UTC-3, no
# DST) is correct for essentially all populated Brazil and is a far safer
# default than UTC. Tenants in another zone still override via settings.
_DEFAULT_TZ = "America/Sao_Paulo"


def _clinic_tz(tenant_settings: dict) -> ZoneInfo:
    """Resolve the clinic timezone, falling back to America/Sao_Paulo on
    invalid/missing config (see _DEFAULT_TZ)."""
    tz_name = ((tenant_settings or {}).get("schedule", {}) or {}).get("timezone") or _DEFAULT_TZ
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        logger.warning("Invalid timezone '%s' — falling back to %s", tz_name, _DEFAULT_TZ)
        return ZoneInfo(_DEFAULT_TZ)


# Portuguese weekday names (Mon=0 … Sun=6) — strftime locale is unreliable on Windows.
_WEEKDAYS_PT = [
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sábado", "domingo",
]


def _fmt_local(dt: datetime, tz: ZoneInfo) -> str:
    """Friendly pt-BR datetime in the clinic timezone (e.g. 'sexta-feira 20/06/2026 14:00')."""
    local = dt.astimezone(tz)
    return f"{_WEEKDAYS_PT[local.weekday()]} {local.strftime('%d/%m/%Y %H:%M')}"


def _resolve_schedule(tenant_settings: dict, target_date: date) -> dict:
    """
    Normalize the tenant schedule config for a given date. All fields optional;
    sensible defaults apply. `capacity` is the number of appointments the clinic
    can run in parallel (≈ professionals/rooms) — defaults to 1.
    """
    schedule = (tenant_settings or {}).get("schedule", {}) or {}
    tz = _clinic_tz(tenant_settings)

    working_days: list[int] = schedule.get("working_days", [1, 2, 3, 4, 5])

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

    try:
        capacity = int(schedule.get("capacity", 1))
    except (TypeError, ValueError):
        capacity = 1
    capacity = max(capacity, 1)

    return {
        "tz": tz,
        "working_days": working_days,
        "open_t": open_t,
        "close_t": close_t,
        "lunch_range": lunch_range,
        "capacity": capacity,
        "schedule": schedule,
    }


async def _booked_windows(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    tz: ZoneInfo,
    range_start: datetime,
    range_end: datetime,
    exclude_id: uuid.UUID | None = None,
    professional_id: uuid.UUID | None = None,
) -> list[tuple[datetime, datetime]]:
    """
    Return real (start, end) windows (in `tz`) of non-cancelled appointments that
    overlap the [range_start, range_end) interval. Duration comes from `ends_at`
    when present, otherwise from the service duration, otherwise a 60-min fallback.
    When `professional_id` is given, only that professional's appointments count.
    """
    q = select(Appointment).where(
        Appointment.tenant_id == tenant_id,
        Appointment.status != AppointmentStatus.CANCELLED,
        Appointment.scheduled_at < range_end,
    )
    if exclude_id is not None:
        q = q.where(Appointment.id != exclude_id)
    if professional_id is not None:
        q = q.where(Appointment.professional_id == professional_id)
    booked = (await db.execute(q)).scalars().all()

    # Batch-fetch durations only for rows lacking ends_at (avoids N+1)
    missing_ids = {a.service_id for a in booked if a.service_id and a.ends_at is None}
    durations: dict[uuid.UUID, int] = {}
    if missing_ids:
        svcs = await db.execute(select(Service).where(Service.id.in_(missing_ids)))
        durations = {s.id: s.duration_minutes for s in svcs.scalars().all()}

    windows: list[tuple[datetime, datetime]] = []
    for appt in booked:
        start = appt.scheduled_at.astimezone(tz)
        if appt.ends_at:
            end = appt.ends_at.astimezone(tz)
        elif appt.service_id in durations:
            end = start + timedelta(minutes=durations[appt.service_id])
        else:
            end = start + timedelta(minutes=_DEFAULT_SLOT_MINUTES)
        if end > range_start:
            windows.append((start, end))
    return windows


async def _validate_booking(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    tenant_settings: dict,
    start: datetime,
    end: datetime,
    exclude_id: uuid.UUID | None = None,
) -> str | None:
    """
    Validate a booking window [start, end) against the clinic schedule.
    Returns an error message string if invalid, or None if the slot is bookable.

    Checks: working day, within business hours, outside lunch break, and that the
    number of overlapping appointments is below the clinic `capacity`.

    NOTE: callers must hold the per-tenant advisory lock (see `_lock_tenant`) so the
    overlap count cannot change between this check and the subsequent insert/update.
    """
    tz = _clinic_tz(tenant_settings)
    local_start = start.astimezone(tz)
    local_end = end.astimezone(tz)
    target_date = local_start.date()

    sched = _resolve_schedule(tenant_settings, target_date)

    if target_date.isoweekday() not in sched["working_days"]:
        return "A clínica não atende neste dia da semana. Escolha outro dia."

    day_open = datetime.combine(target_date, sched["open_t"], tzinfo=tz)
    day_close = datetime.combine(target_date, sched["close_t"], tzinfo=tz)
    if local_start < day_open or local_end > day_close:
        return (
            f"O horário está fora do expediente "
            f"({sched['open_t'].strftime('%H:%M')}–{sched['close_t'].strftime('%H:%M')})."
        )

    lunch = sched["lunch_range"]
    if lunch and local_start < lunch[1] and local_end > lunch[0]:
        return "O horário coincide com o intervalo de almoço da clínica."

    windows = await _booked_windows(
        db, tenant_id, tz, local_start, local_end, exclude_id=exclude_id
    )
    if len(windows) >= sched["capacity"]:
        return "Esse horário acabou de ser preenchido. Por favor, escolha outro horário disponível."

    return None


async def _lock_tenant(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """
    Acquire a transaction-scoped Postgres advisory lock keyed on the tenant.
    Serializes concurrent booking writes for the same clinic so the
    check→insert window cannot be raced into a double-booking. The lock is
    released automatically when the surrounding transaction commits/rolls back.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k)::bigint)"),
        {"k": str(tenant_id)},
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def _list_services(
    db: AsyncSession, tenant_id: uuid.UUID, per_professional: bool = False
) -> dict:
    query = select(Service).where(
        Service.tenant_id == tenant_id,
        Service.is_active == True,  # noqa: E712
    )
    if per_professional:
        # Only offer services that have at least one active professional linked,
        # since per-professional scheduling cannot book a service nobody performs.
        linked = (
            select(professional_services.c.service_id)
            .join(User, User.id == professional_services.c.professional_id)
            .where(User.tenant_id == tenant_id, User.is_active == True)  # noqa: E712
        )
        query = query.where(Service.id.in_(linked))
    services = (await db.execute(query.order_by(Service.name))).scalars().all()

    def _price(s: Service) -> str | None:
        # A price of 0 (or negative) means the clinic never filled it in — it is
        # NOT "free". Report it as unset so Sofia says the value is assessed in
        # the consultation instead of announcing "R$ 0,00".
        if s.price is None or s.price <= 0:
            return None
        return str(s.price)

    return {
        "services": [
            {
                "id": str(s.id),
                "name": s.name,
                "duration_minutes": s.duration_minutes,
                "price": _price(s),
                "price_unset": _price(s) is None,
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

    sched = _resolve_schedule(tenant_settings, target_date)
    tz = sched["tz"]
    capacity = sched["capacity"]

    weekday_pt = _WEEKDAY_NAME_PT[target_date.isoweekday()]

    # Closed day — return early before any DB work
    if target_date.isoweekday() not in sched["working_days"]:
        return {
            "date": args["date"],
            "weekday": weekday_pt,
            "available_slots": [],
            "message": "A clínica não atende neste dia da semana.",
        }

    # ── Service duration for the requested service ────────────────────────────
    slot_minutes = _DEFAULT_SLOT_MINUTES
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
        granularity_minutes = int(sched["schedule"].get("slot_granularity_minutes", slot_minutes))
    except (TypeError, ValueError):
        granularity_minutes = slot_minutes
    granularity_dur = timedelta(minutes=granularity_minutes)

    # ── Booked windows for the target day ─────────────────────────────────────
    day_open = datetime.combine(target_date, sched["open_t"], tzinfo=tz)
    day_close = datetime.combine(target_date, sched["close_t"], tzinfo=tz)
    lunch_range = sched["lunch_range"]

    booked_ranges = await _booked_windows(db, tenant_id, tz, day_open, day_close)

    # ── Generate available slots ──────────────────────────────────────────────
    # A slot is free while fewer than `capacity` appointments overlap it
    # (capacity ≈ professionals/rooms working in parallel; default 1).
    available: list[str] = []
    cursor = day_open

    while cursor + slot_dur <= day_close:
        slot_end = cursor + slot_dur

        # Reject if the slot window overlaps the lunch break
        if lunch_range and cursor < lunch_range[1] and slot_end > lunch_range[0]:
            cursor += granularity_dur
            continue

        overlaps = sum(1 for start, end in booked_ranges if cursor < end and slot_end > start)
        if overlaps >= capacity:
            cursor += granularity_dur
            continue

        available.append(cursor.strftime("%H:%M"))
        cursor += granularity_dur

    if not available:
        return {
            "date": args["date"],
            "weekday": weekday_pt,
            "available_slots": [],
            "message": "Não há horários disponíveis nesta data.",
        }

    return {
        "date": args["date"],
        "weekday": weekday_pt,
        "available_slots": available,
        "timezone": tz.key,
    }


async def _create_appointment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    tenant_settings: dict,
    args: dict,
) -> dict:
    try:
        scheduled_at = datetime.fromisoformat(args["scheduled_at"])
    except (KeyError, ValueError):
        return {"error": "Formato de data/hora inválido. Use ISO 8601."}
    # A naive datetime from the AI means clinic-local time (that's how
    # check_availability reported the slots) — not UTC.
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=_clinic_tz(tenant_settings))

    # Resolve & validate service, capturing its duration for ends_at
    service_id: uuid.UUID | None = None
    duration_minutes = _DEFAULT_SLOT_MINUTES
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
            svc = svc_result.scalar_one_or_none()
            if svc:
                service_id = candidate
                duration_minutes = svc.duration_minutes
        except ValueError:
            pass  # invalid UUID — ignore silently

    ends_at = scheduled_at + timedelta(minutes=duration_minutes)

    # Serialize concurrent bookings for this tenant, then validate the slot is
    # still bookable (business hours + working day + lunch + capacity) before insert.
    await _lock_tenant(db, tenant_id)
    error = await _validate_booking(db, tenant_id, tenant_settings, scheduled_at, ends_at)
    if error:
        return {"error": error}

    appointment = Appointment(
        tenant_id=tenant_id,   # context — IA cannot override
        contact_id=contact_id,  # context — IA cannot override
        service_id=service_id,
        scheduled_at=scheduled_at,
        ends_at=ends_at,
        status=AppointmentStatus.SCHEDULED,
        notes=args.get("notes"),
    )
    db.add(appointment)
    await db.flush()  # get the ID without committing (caller commits)

    # CRM: a booked appointment advances the contact to the "scheduled" stage.
    contact = await db.get(Contact, contact_id)
    if contact is not None:
        crm.mark_scheduled(contact)

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
        "scheduled_at_local": _fmt_local(scheduled_at, _clinic_tz(tenant_settings)),
        "ends_at": ends_at.isoformat(),
        "status": AppointmentStatus.SCHEDULED,
    }


async def _get_upcoming_appointments(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    tenant_settings: dict,
) -> dict:
    now = datetime.now(timezone.utc)
    tz = _clinic_tz(tenant_settings)
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

    # Batch-resolve service + professional names (avoids N+1) so Sofia can say
    # "sua Limpeza com a Dra. Ana" instead of just an opaque id.
    service_ids = {a.service_id for a in appointments if a.service_id}
    prof_ids = {a.professional_id for a in appointments if a.professional_id}
    service_names: dict[uuid.UUID, str] = {}
    prof_names: dict[uuid.UUID, str] = {}
    if service_ids:
        rows = await db.execute(select(Service).where(Service.id.in_(service_ids)))
        service_names = {s.id: s.name for s in rows.scalars().all()}
    if prof_ids:
        rows = await db.execute(select(User).where(User.id.in_(prof_ids)))
        prof_names = {u.id: u.full_name for u in rows.scalars().all()}

    return {
        "timezone": tz.key,
        "appointments": [
            {
                "id": str(a.id),
                "scheduled_at": _fmt_local(a.scheduled_at, tz),
                "scheduled_at_iso": a.scheduled_at.astimezone(tz).isoformat(),
                "status": a.status,
                "service_id": str(a.service_id) if a.service_id else None,
                "service_name": service_names.get(a.service_id),
                "professional_name": prof_names.get(a.professional_id),
            }
            for a in appointments
        ],
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
    tenant_settings: dict,
    args: dict,
) -> dict:
    """
    Atomic reschedule: change scheduled_at (and optionally service) of an existing
    appointment. Tenant + contact scope enforced from context — AI cannot reschedule
    other patients' appointments. Revalidates the new slot (hours + capacity),
    excluding the appointment itself from the overlap count.
    """
    try:
        appointment_id = uuid.UUID(args["appointment_id"])
    except (KeyError, ValueError):
        return {"error": "appointment_id inválido."}

    try:
        new_scheduled_at = datetime.fromisoformat(args["new_scheduled_at"])
    except (KeyError, ValueError):
        return {"error": "Formato de new_scheduled_at inválido. Use ISO 8601."}
    # Naive datetime from the AI means clinic-local time — not UTC.
    if new_scheduled_at.tzinfo is None:
        new_scheduled_at = new_scheduled_at.replace(tzinfo=_clinic_tz(tenant_settings))

    # Serialize bookings for this tenant before reading + writing.
    await _lock_tenant(db, tenant_id)

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

    # Determine the effective service (new one if provided + valid, else current)
    target_service_id = appointment.service_id
    new_service_id_str = args.get("new_service_id")
    if new_service_id_str:
        try:
            candidate = uuid.UUID(new_service_id_str)
            svc_result = await db.execute(
                select(Service).where(
                    Service.id == candidate, Service.tenant_id == tenant_id
                )
            )
            if svc_result.scalar_one_or_none():
                target_service_id = candidate
        except ValueError:
            pass  # invalid UUID — silently ignore (keep old service)

    # Resolve duration for the effective service to compute ends_at
    duration_minutes = _DEFAULT_SLOT_MINUTES
    if target_service_id:
        svc = (
            await db.execute(select(Service).where(Service.id == target_service_id))
        ).scalar_one_or_none()
        if svc:
            duration_minutes = svc.duration_minutes

    new_ends_at = new_scheduled_at + timedelta(minutes=duration_minutes)

    # Validate the new slot, excluding this appointment from the overlap count.
    error = await _validate_booking(
        db, tenant_id, tenant_settings, new_scheduled_at, new_ends_at,
        exclude_id=appointment_id,
    )
    if error:
        return {"error": error}

    appointment.service_id = target_service_id
    appointment.scheduled_at = new_scheduled_at
    appointment.ends_at = new_ends_at

    await db.flush()

    logger.info(
        "Appointment rescheduled by AI tool: id=%s tenant=%s contact=%s new_at=%s",
        appointment.id, tenant_id, contact_id, new_scheduled_at,
    )

    return {
        "success": True,
        "appointment_id": str(appointment.id),
        "scheduled_at": appointment.scheduled_at.isoformat(),
        "scheduled_at_local": _fmt_local(appointment.scheduled_at, _clinic_tz(tenant_settings)),
        "service_id": str(appointment.service_id) if appointment.service_id else None,
        "message": "Agendamento remarcado com sucesso.",
    }


_WEEKDAY_NAME_PT = {
    1: "segunda", 2: "terça", 3: "quarta", 4: "quinta",
    5: "sexta", 6: "sábado", 7: "domingo",
}


async def _get_clinic_info(tenant_settings: dict, tenant_name: str | None = None) -> dict:
    """
    Return the clinic-info block from tenant.settings.clinic plus the schedule
    (with weekdays spelled out in pt-BR). Returns sane defaults when fields are
    missing — never errors.
    """
    clinic = tenant_settings.get("clinic", {}) or {}
    schedule = tenant_settings.get("schedule", {}) or {}
    working_days = schedule.get("working_days", [1, 2, 3, 4, 5])

    # Installments: only a real configured number is exposed. When unset, we say
    # so explicitly ("não configurado") — a live production chat showed the model
    # filling this gap with an invented "até 3 vezes" when the field was absent.
    raw_installments = clinic.get("max_installments")
    try:
        max_installments = int(raw_installments) if raw_installments else None
        if max_installments is not None and max_installments < 2:
            max_installments = None
    except (TypeError, ValueError):
        max_installments = None

    return {
        "name": tenant_name,
        "address": clinic.get("address"),
        "phone": clinic.get("phone"),
        "email": clinic.get("email"),
        "instagram": clinic.get("instagram"),
        "payment_methods": clinic.get("payment_methods", []),
        "max_installments": max_installments,
        "installments_info": (
            f"Parcelamento em até {max_installments}x no cartão de crédito."
            if max_installments
            else "Parcelamento não configurado — a quantidade de parcelas é combinada na clínica; NÃO invente um número."
        ),
        "additional_info": clinic.get("additional_info"),
        "schedule": {
            "timezone": schedule.get("timezone") or _DEFAULT_TZ,
            "working_days": working_days,
            "working_days_names": [_WEEKDAY_NAME_PT.get(d, str(d)) for d in working_days],
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


# Stages the AI may set directly. scheduled/attended are driven by facts
# (appointment created/completed), so the AI is not allowed to set them here.
_AI_SETTABLE_STAGES = {
    CrmStage.COLD_LEAD.value,
    CrmStage.HOT_LEAD.value,
    CrmStage.POST_CARE.value,
    CrmStage.LOST.value,
}


async def _set_crm_stage(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    args: dict,
) -> dict:
    """Let Sofia move the current contact in the CRM pipeline based on the
    conversation. tenant_id/contact_id come from context — never from args."""
    stage = (args.get("stage") or "").strip()
    if stage not in _AI_SETTABLE_STAGES:
        return {
            "error": f"Estágio inválido. Use um de: {sorted(_AI_SETTABLE_STAGES)}",
        }

    contact = (
        await db.execute(
            select(Contact).where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if contact is None:
        return {"error": "Contato não encontrado."}

    contact.crm_stage = stage
    contact.crm_stage_source = "ai"
    contact.crm_stage_updated_at = datetime.now(timezone.utc)
    await db.flush()

    logger.info(
        "CRM stage set by AI: contact=%s tenant=%s stage=%s reason=%s",
        contact_id, tenant_id, stage, args.get("reason"),
    )
    return {"success": True, "crm_stage": stage}


# ---------------------------------------------------------------------------
# Per-professional scheduling (Fase 3 — scheduling_mode="per_professional")
# ---------------------------------------------------------------------------

async def _resolve_service(
    db: AsyncSession, tenant_id: uuid.UUID, service_id_str: str | None
) -> Service | None:
    if not service_id_str:
        return None
    try:
        sid = uuid.UUID(service_id_str)
    except (ValueError, AttributeError):
        return None
    return (
        await db.execute(
            select(Service).where(Service.id == sid, Service.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()


async def _tenant_has_professional_setup(
    db: AsyncSession, tenant_id: uuid.UUID
) -> bool:
    """True if at least one of the clinic's services is linked to a professional.
    Used to decide whether per-professional scheduling can operate, or should
    gracefully fall back to capacity while the clinic is still being set up."""
    row = await db.scalar(
        select(professional_services.c.service_id)
        .join(Service, Service.id == professional_services.c.service_id)
        .where(Service.tenant_id == tenant_id)
        .limit(1)
    )
    return row is not None


async def _professionals_for_service(
    db: AsyncSession, tenant_id: uuid.UUID, service_id: uuid.UUID
) -> list[User]:
    """Active users (professionals) linked to a service, ordered by name."""
    rows = await db.execute(
        select(User)
        .join(professional_services, professional_services.c.professional_id == User.id)
        .where(
            professional_services.c.service_id == service_id,
            User.tenant_id == tenant_id,
            User.is_active == True,  # noqa: E712
        )
        .order_by(User.full_name)
    )
    return list(rows.scalars().all())


async def _professional_offers(
    db: AsyncSession, professional_id: uuid.UUID, service_id: uuid.UUID | None
) -> bool:
    if service_id is None:
        return True
    row = await db.execute(
        select(professional_services.c.service_id).where(
            professional_services.c.professional_id == professional_id,
            professional_services.c.service_id == service_id,
        )
    )
    return row.first() is not None


def _clinic_fallback_blocks(
    tenant_settings: dict, target_date: date, tz: ZoneInfo
) -> list[tuple[datetime, datetime]]:
    """Clinic-wide work blocks for a date (open→close minus lunch), used when a
    professional hasn't defined their own hours."""
    sched = _resolve_schedule(tenant_settings, target_date)
    if target_date.isoweekday() not in sched["working_days"]:
        return []
    open_dt = datetime.combine(target_date, sched["open_t"], tzinfo=tz)
    close_dt = datetime.combine(target_date, sched["close_t"], tzinfo=tz)
    lunch = sched["lunch_range"]
    if lunch and lunch[0] < close_dt and lunch[1] > open_dt:
        blocks: list[tuple[datetime, datetime]] = []
        if open_dt < lunch[0]:
            blocks.append((open_dt, min(lunch[0], close_dt)))
        if close_dt > lunch[1]:
            blocks.append((max(lunch[1], open_dt), close_dt))
        return blocks
    return [(open_dt, close_dt)]


async def _professional_work_blocks(
    db: AsyncSession,
    professional_id: uuid.UUID,
    tenant_settings: dict,
    target_date: date,
    tz: ZoneInfo,
) -> list[tuple[datetime, datetime]]:
    """
    Work blocks for a professional on a date. Uses their own work_hours when they
    have any defined (an empty result for that weekday means they don't work that
    day); falls back to the clinic schedule only when they have NO hours at all.
    """
    rows = (
        await db.execute(
            select(ProfessionalWorkHours).where(
                ProfessionalWorkHours.professional_id == professional_id
            )
        )
    ).scalars().all()
    if rows:
        wd = target_date.isoweekday()
        return [
            (
                datetime.combine(target_date, w.start_time, tzinfo=tz),
                datetime.combine(target_date, w.end_time, tzinfo=tz),
            )
            for w in rows
            if w.weekday == wd
        ]
    return _clinic_fallback_blocks(tenant_settings, target_date, tz)


def _slots_in_blocks(
    blocks: list[tuple[datetime, datetime]],
    booked: list[tuple[datetime, datetime]],
    slot_dur: timedelta,
    granularity: timedelta,
) -> list[datetime]:
    slots: list[datetime] = []
    for bstart, bend in blocks:
        cursor = bstart
        while cursor + slot_dur <= bend:
            slot_end = cursor + slot_dur
            if not any(cursor < e and slot_end > s for s, e in booked):
                slots.append(cursor)
            cursor += granularity
    return slots


async def _professional_slot_ok(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    tenant_settings: dict,
    professional_id: uuid.UUID,
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """True if [start, end) fits within one of the professional's work blocks and
    doesn't overlap any of their other appointments."""
    local_start = start.astimezone(tz)
    local_end = end.astimezone(tz)
    blocks = await _professional_work_blocks(
        db, professional_id, tenant_settings, local_start.date(), tz
    )
    if not any(bs <= local_start and local_end <= be for bs, be in blocks):
        return False
    booked = await _booked_windows(
        db, tenant_id, tz, local_start, local_end,
        exclude_id=exclude_id, professional_id=professional_id,
    )
    return len(booked) == 0


def _granularity(tenant_settings: dict, default_minutes: int) -> timedelta:
    schedule = (tenant_settings or {}).get("schedule", {}) or {}
    try:
        minutes = int(schedule.get("slot_granularity_minutes", default_minutes))
    except (TypeError, ValueError):
        minutes = default_minutes
    return timedelta(minutes=max(minutes, 5))


async def _check_availability_pp(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    tenant_settings: dict,
    args: dict,
) -> dict:
    """Per-professional availability: a time is offered if at least one qualified
    professional is free; the response lists who is free at each time."""
    try:
        target_date = date.fromisoformat(args["date"])
    except (KeyError, ValueError):
        return {"error": "Formato de data inválido. Use YYYY-MM-DD."}

    service = await _resolve_service(db, tenant_id, args.get("service_id"))
    if service is None:
        return {"error": "Preciso saber o serviço para verificar a disponibilidade. Use list_services primeiro."}

    tz = _clinic_tz(tenant_settings)
    weekday_pt = _WEEKDAY_NAME_PT[target_date.isoweekday()]
    slot_dur = timedelta(minutes=service.duration_minutes)
    granularity = _granularity(tenant_settings, service.duration_minutes)

    professionals = await _professionals_for_service(db, tenant_id, service.id)
    requested = args.get("professional_id")
    if requested:
        professionals = [p for p in professionals if str(p.id) == str(requested)]
        if not professionals:
            return {"error": "Esse profissional não realiza este serviço."}
    if not professionals:
        return {
            "date": args["date"],
            "weekday": weekday_pt,
            "available_slots": [],
            "message": "Nenhum profissional realiza este serviço ainda.",
        }

    day_start = datetime.combine(target_date, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)

    agg: dict[str, list[dict]] = {}
    for prof in professionals:
        blocks = await _professional_work_blocks(db, prof.id, tenant_settings, target_date, tz)
        if not blocks:
            continue
        booked = await _booked_windows(
            db, tenant_id, tz, day_start, day_end, professional_id=prof.id
        )
        for slot in _slots_in_blocks(blocks, booked, slot_dur, granularity):
            agg.setdefault(slot.strftime("%H:%M"), []).append(
                {"id": str(prof.id), "name": prof.full_name}
            )

    if not agg:
        return {
            "date": args["date"],
            "weekday": weekday_pt,
            "available_slots": [],
            "message": "Não há horários disponíveis nesta data.",
        }

    times = sorted(agg.keys())
    return {
        "date": args["date"],
        "weekday": weekday_pt,
        "service_id": str(service.id),
        "timezone": tz.key,
        "available_slots": times,
        "slots": [{"time": t, "professionals": agg[t]} for t in times],
    }


async def _create_appointment_pp(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    tenant_settings: dict,
    args: dict,
) -> dict:
    try:
        scheduled_at = datetime.fromisoformat(args["scheduled_at"])
    except (KeyError, ValueError):
        return {"error": "Formato de data/hora inválido. Use ISO 8601."}
    tz = _clinic_tz(tenant_settings)
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=tz)

    service = await _resolve_service(db, tenant_id, args.get("service_id"))
    if service is None:
        return {"error": "Preciso saber qual serviço será agendado. Use list_services primeiro."}

    ends_at = scheduled_at + timedelta(minutes=service.duration_minutes)

    professionals = await _professionals_for_service(db, tenant_id, service.id)
    if not professionals:
        return {"error": "Nenhum profissional realiza este serviço ainda."}

    await _lock_tenant(db, tenant_id)

    requested = args.get("professional_id")
    if requested:
        candidates = [p for p in professionals if str(p.id) == str(requested)]
        if not candidates:
            return {"error": "Esse profissional não realiza este serviço."}
    else:
        candidates = professionals

    free = [
        p for p in candidates
        if await _professional_slot_ok(db, tenant_id, tenant_settings, p.id, scheduled_at, ends_at, tz)
    ]
    if not free:
        return {"error": "Nenhum profissional disponível nesse horário. Use check_availability para ver horários livres."}
    if len(free) > 1 and not requested:
        return {
            "needs_selection": True,
            "professionals": [{"id": str(p.id), "name": p.full_name} for p in free],
            "message": "Há mais de um profissional disponível nesse horário. Pergunte ao paciente qual prefere e chame create_appointment de novo com professional_id.",
        }

    chosen = free[0]
    appointment = Appointment(
        tenant_id=tenant_id,
        contact_id=contact_id,
        service_id=service.id,
        professional_id=chosen.id,
        scheduled_at=scheduled_at,
        ends_at=ends_at,
        status=AppointmentStatus.SCHEDULED,
        notes=args.get("notes"),
    )
    try:
        async with db.begin_nested():
            db.add(appointment)
            await db.flush()
    except IntegrityError as exc:
        if "no_overlap_per_professional" in str(getattr(exc, "orig", exc)):
            # EXCLUDE constraint caught a concurrent booking for this professional
            return {"error": "Esse horário acabou de ser preenchido para o profissional. Escolha outro horário."}
        logger.exception("create_appointment_pp_integrity_error", extra={"tenant_id": str(tenant_id)})
        return {"error": "Não consegui concluir o agendamento. Tente novamente ou escolha outro horário."}

    # CRM: a booked appointment advances the contact to the "scheduled" stage.
    contact = await db.get(Contact, contact_id)
    if contact is not None:
        crm.mark_scheduled(contact)

    logger.info(
        "Appointment(pp) created by AI tool: id=%s tenant=%s contact=%s prof=%s at=%s",
        appointment.id, tenant_id, contact_id, chosen.id, scheduled_at,
    )

    return {
        "success": True,
        "appointment_id": str(appointment.id),
        "scheduled_at": scheduled_at.isoformat(),
        "scheduled_at_local": _fmt_local(scheduled_at, tz),
        "ends_at": ends_at.isoformat(),
        "professional_id": str(chosen.id),
        "professional_name": chosen.full_name,
        "status": AppointmentStatus.SCHEDULED,
    }


async def _reschedule_appointment_pp(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    tenant_settings: dict,
    args: dict,
) -> dict:
    try:
        appointment_id = uuid.UUID(args["appointment_id"])
    except (KeyError, ValueError):
        return {"error": "appointment_id inválido."}

    try:
        new_scheduled_at = datetime.fromisoformat(args["new_scheduled_at"])
    except (KeyError, ValueError):
        return {"error": "Formato de new_scheduled_at inválido. Use ISO 8601."}
    tz = _clinic_tz(tenant_settings)
    if new_scheduled_at.tzinfo is None:
        new_scheduled_at = new_scheduled_at.replace(tzinfo=tz)

    await _lock_tenant(db, tenant_id)

    appointment = (
        await db.execute(
            select(Appointment).where(
                Appointment.id == appointment_id,
                Appointment.tenant_id == tenant_id,
                Appointment.contact_id == contact_id,
                Appointment.status != AppointmentStatus.CANCELLED,
            )
        )
    ).scalar_one_or_none()
    if appointment is None:
        return {"error": "Agendamento não encontrado ou já cancelado."}

    # Effective service (new if provided + valid, else current)
    target_service_id = appointment.service_id
    new_service = await _resolve_service(db, tenant_id, args.get("new_service_id"))
    if new_service is not None:
        target_service_id = new_service.id

    duration_minutes = _DEFAULT_SLOT_MINUTES
    if target_service_id:
        svc = (
            await db.execute(select(Service).where(Service.id == target_service_id))
        ).scalar_one_or_none()
        if svc:
            duration_minutes = svc.duration_minutes
    new_ends_at = new_scheduled_at + timedelta(minutes=duration_minutes)

    # Effective professional
    target_prof_id = appointment.professional_id
    new_prof_str = args.get("new_professional_id")
    if new_prof_str:
        try:
            candidate = uuid.UUID(new_prof_str)
        except ValueError:
            return {"error": "new_professional_id inválido."}
        if not await _professional_offers(db, candidate, target_service_id):
            return {"error": "Esse profissional não realiza este serviço."}
        target_prof_id = candidate

    if target_prof_id is None:
        # No professional yet — resolve from the service's professionals
        professionals = (
            await _professionals_for_service(db, tenant_id, target_service_id)
            if target_service_id else []
        )
        free = [
            p for p in professionals
            if await _professional_slot_ok(
                db, tenant_id, tenant_settings, p.id, new_scheduled_at, new_ends_at, tz,
                exclude_id=appointment_id,
            )
        ]
        if not free:
            return {"error": "Nenhum profissional disponível nesse horário. Use check_availability."}
        if len(free) > 1:
            return {
                "needs_selection": True,
                "professionals": [{"id": str(p.id), "name": p.full_name} for p in free],
                "message": "Há mais de um profissional disponível. Pergunte qual o paciente prefere e chame de novo com new_professional_id.",
            }
        target_prof_id = free[0].id
    else:
        if not await _professional_offers(db, target_prof_id, target_service_id):
            return {"error": "O profissional do agendamento não realiza esse serviço. Informe new_professional_id."}
        if not await _professional_slot_ok(
            db, tenant_id, tenant_settings, target_prof_id, new_scheduled_at, new_ends_at, tz,
            exclude_id=appointment_id,
        ):
            return {"error": "O profissional não está disponível nesse horário. Escolha outro horário ou profissional."}

    appointment.service_id = target_service_id
    appointment.professional_id = target_prof_id
    appointment.scheduled_at = new_scheduled_at
    appointment.ends_at = new_ends_at
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        if "no_overlap_per_professional" in str(getattr(exc, "orig", exc)):
            return {"error": "Esse horário acabou de ser preenchido para o profissional. Escolha outro horário."}
        logger.exception("reschedule_appointment_pp_integrity_error", extra={"tenant_id": str(tenant_id)})
        return {"error": "Não consegui remarcar. Tente novamente ou escolha outro horário."}

    logger.info(
        "Appointment(pp) rescheduled by AI tool: id=%s tenant=%s prof=%s new_at=%s",
        appointment.id, tenant_id, target_prof_id, new_scheduled_at,
    )

    return {
        "success": True,
        "appointment_id": str(appointment.id),
        "scheduled_at": appointment.scheduled_at.isoformat(),
        "scheduled_at_local": _fmt_local(appointment.scheduled_at, tz),
        "service_id": str(appointment.service_id) if appointment.service_id else None,
        "professional_id": str(target_prof_id),
        "message": "Agendamento remarcado com sucesso.",
    }


async def _list_professionals(db: AsyncSession, tenant_id: uuid.UUID, args: dict) -> dict:
    """List active professionals and the services each one performs."""
    users = (
        await db.execute(
            select(User)
            .where(User.tenant_id == tenant_id, User.is_active == True)  # noqa: E712
            .options(selectinload(User.offered_services))
            .order_by(User.full_name)
        )
    ).scalars().all()

    service_filter = args.get("service_id")
    result = []
    for u in users:
        services = [s for s in u.offered_services if s.is_active]
        if not services:
            continue  # skip non-attending staff (receptionists, etc.)
        if service_filter and not any(str(s.id) == str(service_filter) for s in services):
            continue
        result.append({
            "id": str(u.id),
            "name": u.full_name,
            "services": [{"id": str(s.id), "name": s.name} for s in services],
        })

    if not result:
        return {"professionals": [], "message": "Nenhum profissional disponível para este critério."}
    return {"professionals": result}
