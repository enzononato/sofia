"""
Tenant routes — settings and profile of the current clinic.

GET   /tenants/me  — return the authenticated clinic's data
PATCH /tenants/me  — update name, contact info, ai_config, settings
"""

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentTenantId, CurrentUser, DBSession
from app.core.errors import ForbiddenError, NotFoundError
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.schemas.tenant import TenantRead, TenantUpdate

router = APIRouter(prefix="/tenants", tags=["Tenants"])

_WRITE_ROLES = (UserRole.OWNER, UserRole.ADMIN)


@router.get("/me", response_model=TenantRead)
async def get_my_tenant(
    db: DBSession,
    tenant_id: CurrentTenantId,
    _: CurrentUser,
):
    """Return the current clinic's profile."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise NotFoundError("Tenant not found.")
    return tenant


@router.patch("/me", response_model=TenantRead)
async def update_my_tenant(
    payload: TenantUpdate,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    if current_user.role not in _WRITE_ROLES:
        raise ForbiddenError("Only owners and admins can update clinic settings.")

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise NotFoundError("Tenant not found.")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tenant, field, value)

    await db.commit()
    await db.refresh(tenant)
    return tenant
