"""
Services routes — procedimentos oferecidos pela clínica.

POST  /services         — create a new service (tenant_id injected, never from body)
GET   /services         — list services with pagination envelope
GET   /services/{id}    — get a single service
PATCH /services/{id}    — update a service
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentTenantId, CurrentUser, DBSession
from app.core.errors import ForbiddenError, NotFoundError
from app.models.service import Service
from app.models.user import UserRole
from app.schemas.pagination import Page, PageMeta, PaginationParams, pagination_params
from app.schemas.service import ServiceCreate, ServiceRead, ServiceUpdate

router = APIRouter(prefix="/services", tags=["Services"])

_WRITE_ROLES = (UserRole.OWNER, UserRole.ADMIN)


@router.post("", response_model=ServiceRead, status_code=status.HTTP_201_CREATED)
async def create_service(
    payload: ServiceCreate,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    """
    Create a new service. tenant_id is injected from middleware — never from
    the body — so cross-tenant injection is structurally impossible.
    """
    if current_user.role not in _WRITE_ROLES:
        raise ForbiddenError("Only owners and admins can create services.")

    service = Service(tenant_id=tenant_id, **payload.model_dump())
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return service


@router.get("", response_model=Page[ServiceRead])
async def list_services(
    db: DBSession,
    tenant_id: CurrentTenantId,
    _: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    active_only: bool = Query(default=True),
):
    """
    List services for the current tenant.
    The WHERE clause always includes tenant_id — cross-tenant leakage is structurally impossible.
    """
    where = [Service.tenant_id == tenant_id]
    if active_only:
        where.append(Service.is_active.is_(True))

    total = await db.scalar(select(func.count(Service.id)).where(*where))
    rows = await db.execute(
        select(Service)
        .where(*where)
        .order_by(Service.name)
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    return Page[ServiceRead](
        data=[ServiceRead.model_validate(s) for s in rows.scalars().all()],
        meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset),
    )


@router.get("/{service_id}", response_model=ServiceRead)
async def get_service(
    service_id: uuid.UUID,
    db: DBSession,
    tenant_id: CurrentTenantId,
    _: CurrentUser,
):
    return await _get_or_404(db, service_id, tenant_id)


@router.patch("/{service_id}", response_model=ServiceRead)
async def update_service(
    service_id: uuid.UUID,
    payload: ServiceUpdate,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    if current_user.role not in _WRITE_ROLES:
        raise ForbiddenError("Only owners and admins can update services.")

    service = await _get_or_404(db, service_id, tenant_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(service, field, value)

    await db.commit()
    await db.refresh(service)
    return service


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _get_or_404(db, service_id: uuid.UUID, tenant_id: uuid.UUID) -> Service:
    """
    Fetch a service by PK, always scoped to tenant_id. 404 — never 403 — for
    missing-or-wrong-tenant to avoid leaking existence in another clinic.
    """
    result = await db.execute(
        select(Service).where(Service.id == service_id, Service.tenant_id == tenant_id)
    )
    service = result.scalar_one_or_none()
    if service is None:
        raise NotFoundError("Service not found.")
    return service
