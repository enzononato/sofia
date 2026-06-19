"""
Reports / analytics — aggregated metrics for the clinic dashboard.

GET /reports/overview?days=30  — leads trend, conversion, stage distribution,
appointment status breakdown, no-show rate, top services, message volume.

All queries are tenant-scoped. Restricted to clinic admins (owner/admin).
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import CurrentTenantId, CurrentUser, DBSession
from app.core.errors import ForbiddenError
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact, CrmStage
from app.models.message import Message, MessageDirection
from app.models.service import Service
from app.models.user import UserRole
from app.schemas.report import (
    MessageVolumePoint,
    NamedCount,
    ReportOverview,
    TrendPoint,
)

router = APIRouter(prefix="/reports", tags=["Reports"])

_ADMIN_ROLES = (UserRole.OWNER, UserRole.ADMIN)

_CONVERTED_STAGES = (
    CrmStage.SCHEDULED.value,
    CrmStage.ATTENDED.value,
    CrmStage.POST_CARE.value,
)

_STAGE_LABELS = {
    CrmStage.NEW_LEAD.value: "Novo Lead",
    CrmStage.IN_CONVERSATION.value: "Em conversa",
    CrmStage.SCHEDULED.value: "Agendado",
    CrmStage.ATTENDED.value: "Compareceu",
    CrmStage.POST_CARE.value: "Pós-atendimento",
    CrmStage.LOST.value: "Perdido",
}

_STATUS_LABELS = {
    AppointmentStatus.SCHEDULED.value: "Agendado",
    AppointmentStatus.CONFIRMED.value: "Confirmado",
    AppointmentStatus.IN_PROGRESS.value: "Em andamento",
    AppointmentStatus.COMPLETED.value: "Concluído",
    AppointmentStatus.CANCELLED.value: "Cancelado",
    AppointmentStatus.NO_SHOW.value: "Não compareceu",
}


@router.get("/overview", response_model=ReportOverview)
async def overview(
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
    days: int = Query(default=30, ge=1, le=365),
):
    if current_user.role not in _ADMIN_ROLES:
        raise ForbiddenError("Apenas administradores podem ver relatórios.")

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    # ── Contacts / conversion ────────────────────────────────────────────────
    total_contacts = await db.scalar(
        select(func.count(Contact.id)).where(Contact.tenant_id == tenant_id)
    ) or 0
    new_contacts = await db.scalar(
        select(func.count(Contact.id)).where(
            Contact.tenant_id == tenant_id, Contact.created_at >= since
        )
    ) or 0
    converted_contacts = await db.scalar(
        select(func.count(Contact.id)).where(
            Contact.tenant_id == tenant_id,
            Contact.crm_stage.in_(_CONVERTED_STAGES),
        )
    ) or 0
    conversion_rate = (converted_contacts / total_contacts) if total_contacts else 0.0

    # ── Stage distribution ────────────────────────────────────────────────────
    stage_rows = await db.execute(
        select(Contact.crm_stage, func.count(Contact.id))
        .where(Contact.tenant_id == tenant_id)
        .group_by(Contact.crm_stage)
    )
    stage_counts = {stage: count for stage, count in stage_rows.all()}
    stage_distribution = [
        NamedCount(label=label, count=stage_counts.get(value, 0))
        for value, label in _STAGE_LABELS.items()
    ]

    # ── Appointments ──────────────────────────────────────────────────────────
    total_appointments = await db.scalar(
        select(func.count(Appointment.id)).where(
            Appointment.tenant_id == tenant_id, Appointment.scheduled_at >= since
        )
    ) or 0
    upcoming_appointments = await db.scalar(
        select(func.count(Appointment.id)).where(
            Appointment.tenant_id == tenant_id,
            Appointment.scheduled_at >= now,
            Appointment.status != AppointmentStatus.CANCELLED,
        )
    ) or 0

    status_rows = await db.execute(
        select(Appointment.status, func.count(Appointment.id))
        .where(Appointment.tenant_id == tenant_id, Appointment.scheduled_at >= since)
        .group_by(Appointment.status)
    )
    status_counts = {status: count for status, count in status_rows.all()}
    appointments_by_status = [
        NamedCount(label=label, count=status_counts.get(value, 0))
        for value, label in _STATUS_LABELS.items()
        if status_counts.get(value, 0) > 0
    ]

    completed = status_counts.get(AppointmentStatus.COMPLETED.value, 0)
    no_show = status_counts.get(AppointmentStatus.NO_SHOW.value, 0)
    no_show_rate = (no_show / (completed + no_show)) if (completed + no_show) else 0.0

    # ── Top services ──────────────────────────────────────────────────────────
    service_rows = await db.execute(
        select(Service.name, func.count(Appointment.id).label("c"))
        .join(Appointment, Appointment.service_id == Service.id)
        .where(Appointment.tenant_id == tenant_id, Appointment.scheduled_at >= since)
        .group_by(Service.name)
        .order_by(func.count(Appointment.id).desc())
        .limit(5)
    )
    top_services = [NamedCount(label=name, count=c) for name, c in service_rows.all()]

    # ── Time series: full day range so charts are continuous ──────────────────
    day_list: list[str] = []
    cursor = since.date()
    end = now.date()
    while cursor <= end:
        day_list.append(cursor.isoformat())
        cursor += timedelta(days=1)

    leads_rows = await db.execute(
        select(func.date(Contact.created_at), func.count(Contact.id))
        .where(Contact.tenant_id == tenant_id, Contact.created_at >= since)
        .group_by(func.date(Contact.created_at))
    )
    leads_by_day = {str(d): c for d, c in leads_rows.all()}
    leads_trend = [TrendPoint(date=d, count=leads_by_day.get(d, 0)) for d in day_list]

    msg_rows = await db.execute(
        select(func.date(Message.created_at), Message.direction, func.count(Message.id))
        .where(Message.tenant_id == tenant_id, Message.created_at >= since)
        .group_by(func.date(Message.created_at), Message.direction)
    )
    inbound_by_day: dict[str, int] = defaultdict(int)
    outbound_by_day: dict[str, int] = defaultdict(int)
    for d, direction, count in msg_rows.all():
        key = str(d)
        if direction == MessageDirection.INBOUND or direction == MessageDirection.INBOUND.value:
            inbound_by_day[key] += count
        else:
            outbound_by_day[key] += count
    messages_volume = [
        MessageVolumePoint(date=d, inbound=inbound_by_day.get(d, 0), outbound=outbound_by_day.get(d, 0))
        for d in day_list
    ]

    return ReportOverview(
        days=days,
        total_contacts=total_contacts,
        new_contacts=new_contacts,
        converted_contacts=converted_contacts,
        conversion_rate=round(conversion_rate, 4),
        total_appointments=total_appointments,
        upcoming_appointments=upcoming_appointments,
        no_show_rate=round(no_show_rate, 4),
        leads_trend=leads_trend,
        stage_distribution=stage_distribution,
        appointments_by_status=appointments_by_status,
        top_services=top_services,
        messages_volume=messages_volume,
    )
