"""
Appointments routes — agendamentos da clínica.

POST   /appointments           — create
GET    /appointments           — list (pagination + filters)
GET    /appointments/{id}      — detail
PATCH  /appointments/{id}      — update status / notes / schedule
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentTenantId, CurrentUser, DBSession
from app.core.errors import ForbiddenError, NotFoundError, UnprocessableEntityError
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.service import Service
from app.models.user import User, UserRole
from app.schemas.appointment import AppointmentCreate, AppointmentRead, AppointmentUpdate
from app.schemas.pagination import Page, PageMeta, PaginationParams, pagination_params

router = APIRouter(prefix="/appointments", tags=["Appointments"])

_WRITE_ROLES = (UserRole.OWNER, UserRole.ADMIN, UserRole.RECEPTIONIST)


@router.post("", response_model=AppointmentRead, status_code=status.HTTP_201_CREATED)
async def create_appointment(
    payload: AppointmentCreate,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    """
    Create a new appointment.
    Security: contact_id, service_id, and professional_id are validated to
    belong to the current tenant before insertion — prevents cross-tenant FK injection.
    """
    if current_user.role not in _WRITE_ROLES:
        raise ForbiddenError("Insufficient permissions.")

    await _assert_tenant_fk(db, Contact, payload.contact_id, tenant_id, "contact_id")

    if payload.service_id:
        await _assert_tenant_fk(db, Service, payload.service_id, tenant_id, "service_id")

    if payload.professional_id:
        await _assert_user_belongs_to_tenant(db, payload.professional_id, tenant_id)

    appointment = Appointment(
        tenant_id=tenant_id,  # always from middleware, never from payload
        **payload.model_dump(),
    )
    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)
    return appointment


@router.get("", response_model=Page[AppointmentRead])
async def list_appointments(
    db: DBSession,
    tenant_id: CurrentTenantId,
    _: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    status_filter: AppointmentStatus | None = Query(default=None, alias="status"),
    contact_id: uuid.UUID | None = Query(default=None),
    professional_id: uuid.UUID | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
):
    """
    List appointments for the current tenant with optional filters.
    All filters are applied after the mandatory tenant_id scope.
    """
    where = [Appointment.tenant_id == tenant_id]
    if status_filter:
        where.append(Appointment.status == status_filter)
    if contact_id:
        where.append(Appointment.contact_id == contact_id)
    if professional_id:
        where.append(Appointment.professional_id == professional_id)
    if date_from:
        where.append(Appointment.scheduled_at >= date_from)
    if date_to:
        where.append(Appointment.scheduled_at <= date_to)

    total = await db.scalar(select(func.count(Appointment.id)).where(*where))
    rows = await db.execute(
        select(Appointment)
        .where(*where)
        .order_by(Appointment.scheduled_at)
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    return Page[AppointmentRead](
        data=[AppointmentRead.model_validate(a) for a in rows.scalars().all()],
        meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset),
    )


@router.get("/{appointment_id}", response_model=AppointmentRead)
async def get_appointment(
    appointment_id: uuid.UUID,
    db: DBSession,
    tenant_id: CurrentTenantId,
    _: CurrentUser,
):
    return await _get_or_404(db, appointment_id, tenant_id)


@router.patch("/{appointment_id}", response_model=AppointmentRead)
async def update_appointment(
    appointment_id: uuid.UUID,
    payload: AppointmentUpdate,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    if current_user.role not in _WRITE_ROLES:
        raise ForbiddenError("Insufficient permissions.")

    appointment = await _get_or_404(db, appointment_id, tenant_id)
    update_data = payload.model_dump(exclude_unset=True)

    if update_data.get("service_id"):
        await _assert_tenant_fk(db, Service, update_data["service_id"], tenant_id, "service_id")

    if update_data.get("professional_id"):
        await _assert_user_belongs_to_tenant(db, update_data["professional_id"], tenant_id)

    new_status = update_data.get("status")
    if new_status == AppointmentStatus.CANCELLED and not update_data.get("cancellation_reason"):
        raise UnprocessableEntityError(
            "cancellation_reason is required when cancelling an appointment.",
            code="cancellation_reason_required",
        )

    for field, value in update_data.items():
        setattr(appointment, field, value)

    await db.commit()
    await db.refresh(appointment)
    return appointment


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _get_or_404(db, appointment_id: uuid.UUID, tenant_id: uuid.UUID) -> Appointment:
    result = await db.execute(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.tenant_id == tenant_id,
        )
    )
    appt = result.scalar_one_or_none()
    if appt is None:
        raise NotFoundError("Appointment not found.")
    return appt


async def _assert_tenant_fk(db, model, record_id: uuid.UUID, tenant_id: uuid.UUID, field_name: str) -> None:
    """Verify that a FK record exists AND belongs to the current tenant."""
    exists = await db.scalar(
        select(func.count())
        .select_from(model)
        .where(model.id == record_id, model.tenant_id == tenant_id)
    )
    if not exists:
        raise UnprocessableEntityError(
            f"{field_name} '{record_id}' not found in this clinic.",
            code="invalid_fk",
        )


async def _assert_user_belongs_to_tenant(db, user_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Verify that a User (professional) belongs to the current tenant."""
    exists = await db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.id == user_id, User.tenant_id == tenant_id)
    )
    if not exists:
        raise UnprocessableEntityError(
            f"professional_id '{user_id}' not found in this clinic.",
            code="invalid_professional",
        )
