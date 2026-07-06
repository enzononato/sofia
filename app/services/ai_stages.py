"""
Conversation stage detection + per-stage prompt overlays for Sofia.

Stages are derived from each contact's appointment + message history:
  - first_contact         no message history at all
  - imminent_appointment  has SCHEDULED/CONFIRMED appointment in next 48h
  - post_appointment      last visit finished/cancelled in last 48h
  - active_patient        has any past COMPLETED appointment
  - returning_lead        has prior messages but zero appointments ever
  - reactivation          last message > 30 days ago

Each stage has a DEFAULT overlay text. Tenants can override any overlay via
`tenant.ai_config["prompt_<stage_value>"]` (e.g. `prompt_first_contact`).
"""

from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.message import Message
from app.services.ai_tools import _clinic_tz, _fmt_local


class Stage(str, Enum):
    FIRST_CONTACT = "first_contact"
    IMMINENT_APPOINTMENT = "imminent_appointment"
    POST_APPOINTMENT = "post_appointment"
    ACTIVE_PATIENT = "active_patient"
    RETURNING_LEAD = "returning_lead"
    REACTIVATION = "reactivation"


DEFAULT_STAGE_OVERLAYS: dict[Stage, str] = {
    Stage.FIRST_CONTACT: (
        "Esta é a PRIMEIRA conversa deste paciente com a clínica.\n"
        "- Apresente-se brevemente como Sofia, a secretária virtual.\n"
        "- Pergunte como pode ajudar de forma acolhedora.\n"
        "- Se o paciente já mandou uma dúvida concreta, vá direto resolvendo — "
        "não obrigue a passar por uma apresentação se ele já está pedindo algo."
    ),
    Stage.IMMINENT_APPOINTMENT: (
        "O paciente TEM um agendamento confirmado nas próximas 48 horas.\n"
        "- É provável que esteja entrando em contato sobre isso (confirmar, remarcar ou cancelar).\n"
        "- Use get_upcoming_appointments para ver os detalhes antes de responder.\n"
        "- Se ele quiser remarcar, use reschedule_appointment (não cancela e cria de novo)."
    ),
    Stage.POST_APPOINTMENT: (
        "O paciente teve um atendimento nas últimas 48 horas.\n"
        "- Demonstre interesse em saber como foi.\n"
        "- Se for serviço recorrente (ex: limpeza, manutenção), ofereça já agendar o próximo.\n"
        "- Não force vendas — escute primeiro."
    ),
    Stage.ACTIVE_PATIENT: (
        "Paciente já é recorrente da clínica.\n"
        "- Use tom mais íntimo e familiar — vocês já se conhecem.\n"
        "- Não repita explicações longas sobre serviços que ele já fez antes.\n"
        "- Vá direto ao ponto."
    ),
    Stage.RETURNING_LEAD: (
        "Paciente já conversou antes mas NUNCA agendou.\n"
        "- Seja proativa: apresente serviços e sugira datas.\n"
        "- Se houver hesitação, ofereça alternativas (horário, valor, formato).\n"
        "- Use list_services e check_availability sem esperar pedido explícito."
    ),
    Stage.REACTIVATION: (
        "Paciente sumiu há mais de 30 dias.\n"
        "- Receba com tom acolhedor: 'que bom ter você de volta!'.\n"
        "- Pergunte como pode ajudar agora; não pressione.\n"
        "- Se for serviço recorrente, antecipe e sugira já agendar."
    ),
}


async def analyze(
    db: AsyncSession,
    contact: Contact,
    history: list[Message],
) -> tuple[Stage, list[Appointment]]:
    """
    Detect the conversation stage and return the contact's full appointment list
    (the caller reuses it to build the context block — avoids a second query).
    """
    result = await db.execute(
        select(Appointment)
        .where(
            Appointment.tenant_id == contact.tenant_id,
            Appointment.contact_id == contact.id,
        )
        .order_by(desc(Appointment.scheduled_at))
    )
    appts = list(result.scalars().all())

    if not history:
        return Stage.FIRST_CONTACT, appts

    now = datetime.now(timezone.utc)
    soon = now + timedelta(hours=48)
    recent = now - timedelta(hours=48)

    # Imminent: SCHEDULED/CONFIRMED in next 48h
    for appt in appts:
        if (
            appt.status in (AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED)
            and now <= appt.scheduled_at <= soon
        ):
            return Stage.IMMINENT_APPOINTMENT, appts

    # Post-appointment: any visit finished/cancelled/no-show in last 48h
    for appt in appts:
        if (
            appt.status
            in (AppointmentStatus.COMPLETED, AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW)
            and recent <= appt.scheduled_at <= now
        ):
            return Stage.POST_APPOINTMENT, appts

    # Active: any past COMPLETED
    for appt in appts:
        if appt.status == AppointmentStatus.COMPLETED:
            return Stage.ACTIVE_PATIENT, appts

    # Reactivation: latest message older than 30 days
    last_msg = history[-1]  # history is oldest → newest
    if last_msg.created_at < now - timedelta(days=30):
        return Stage.REACTIVATION, appts

    # Fallback: returning lead (had conversations, no completed appointments)
    return Stage.RETURNING_LEAD, appts


def overlay_for(stage: Stage) -> str:
    """Return the per-stage overlay. Fixed in code — not tenant-configurable
    (see app.services.ai module docstring)."""
    return DEFAULT_STAGE_OVERLAYS[stage]


def build_context_block(
    contact: Contact,
    stage: Stage,
    appts: list[Appointment],
    tenant_settings: dict | None = None,
) -> str:
    """
    Compact block of structured info about the contact that the AI can read
    directly. Includes the next upcoming appointment ID so Sofia can call
    reschedule/cancel without first looking it up.

    The current date/time is injected in the clinic timezone so the AI can
    correctly resolve relative dates ("hoje", "amanhã", "segunda que vem").
    All appointment times are shown in that same timezone.
    """
    now = datetime.now(timezone.utc)
    tz = _clinic_tz(tenant_settings or {})
    local_now = now.astimezone(tz)

    days_of_week = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo']

    lines: list[str] = ["--- CONTEXTO ATUAL ---"]
    lines.append(
        f"Agora são {local_now.strftime('%H:%M')} de {days_of_week[local_now.weekday()]}, "
        f"{local_now.strftime('%d/%m/%Y')} (fuso {tz.key})."
    )
    lines.append("")
    lines.append(
        "--- CALENDÁRIO (fonte única de datas — NUNCA calcule de cabeça; copie o valor ISO exato da linha) ---"
    )
    lines.append(
        "Cada linha liga um dia a data que você DEVE usar no campo `date`/`scheduled_at` das ferramentas."
    )
    for i in range(14):
        d = local_now + timedelta(days=i)
        weekday_name = days_of_week[d.weekday()]
        if i == 0:
            when = "hoje"
        elif i == 1:
            when = "amanhã"
        elif i < 7:
            when = "esta semana"
        else:
            when = "semana que vem"
        # e.g. "quinta-feira (esta semana) -> date=2026-07-09  [09/07/2026]"
        lines.append(
            f"{weekday_name} ({when}) -> date={d.strftime('%Y-%m-%d')}  [{d.strftime('%d/%m/%Y')}]"
        )
    lines.append(
        "Regras de leitura: encontre a linha cujo dia da semana é o que o paciente disse e use o `date=` "
        "DAQUELA linha, sem contar dias. Se ele disser só o nome do dia (ex.: 'sexta-feira'), use a linha "
        "'(esta semana)'; se disser 'que vem'/'próxima', use a linha '(semana que vem)'. Ao responder, "
        "confira que o dia da semana que você vai escrever é o MESMO da linha que você usou. "
        "Depois de chamar check_availability, o resultado traz o campo 'weekday' da data consultada: se ele "
        "não for o dia que o paciente pediu, você pegou a data errada — corrija e chame de novo."
    )
    lines.append("")
    lines.append("--- CONTEXTO DO PACIENTE ---")
    lines.append(f"Nome: {contact.full_name}")
    if contact.whatsapp_name and contact.whatsapp_name != contact.full_name:
        lines.append(f"Nome no WhatsApp: {contact.whatsapp_name}")
    lines.append(f"Status: {contact.status}")
    lines.append(
        f"Estágio no funil (CRM): {contact.crm_stage} "
        "(classifique com set_crm_stage conforme a conversa: interesse claro → hot_lead, "
        "pouco engajado/só pesquisando → cold_lead, sem interesse → lost)"
    )
    if contact.email:
        lines.append(f"Email: {contact.email}")
    if contact.phone:
        lines.append(f"Telefone: {contact.phone}")
    if contact.date_of_birth:
        lines.append(f"Data de nascimento: {contact.date_of_birth.isoformat()}")

    # Next appointment (earliest upcoming non-cancelled)
    upcoming = [
        a for a in appts
        if a.scheduled_at >= now and a.status != AppointmentStatus.CANCELLED
    ]
    if upcoming:
        upcoming.sort(key=lambda a: a.scheduled_at)
        nxt = upcoming[0]
        lines.append(
            f"Próximo agendamento: {_fmt_local(nxt.scheduled_at, tz)} "
            f"(status={nxt.status}, id={nxt.id})"
        )

    # Last completed visit (for active patients)
    completed = [a for a in appts if a.status == AppointmentStatus.COMPLETED]
    if completed:
        last = completed[0]  # appts already sorted by scheduled_at desc
        lines.append(f"Última visita realizada: {_fmt_local(last.scheduled_at, tz)}")

    lines.append(f"Estágio da conversa: {stage.value}")
    lines.append("--- FIM DO CONTEXTO ---")
    return "\n".join(lines)
