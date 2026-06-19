"""
Users / Staff routes — equipe da clínica.

POST   /users           — create staff (OWNER / ADMIN)
GET    /users           — list staff (paginated)
GET    /users/{id}      — detail
PATCH  /users/{id}      — update data, role, or password (OWNER / ADMIN)

Role rules:
  - Only OWNER can create/edit other OWNERs or assign the OWNER role.
  - ADMIN can create/edit any user except OWNERs.
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentTenantId, CurrentUser, DBSession
from app.config import settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.security import hash_password, hash_refresh_token
from app.models.invitation import Invitation
from app.models.professional import ProfessionalWorkHours
from app.models.service import Service
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.invitation import (
    InvitationCreate,
    InvitationCreateResponse,
    InvitationRead,
)
from app.schemas.pagination import Page, PageMeta, PaginationParams, pagination_params
from app.schemas.user import (
    ServiceAssignmentUpdate,
    UserCreate,
    UserDetailRead,
    UserRead,
    UserUpdate,
    WorkHourBlock,
    WorkHoursUpdate,
)
from app.services.email import invite_email_html, send_email
from app.services.tokens import revoke_all_user_tokens

_ROLE_LABELS_PT = {
    UserRole.OWNER: "Proprietário",
    UserRole.ADMIN: "Administrador",
    UserRole.RECEPTIONIST: "Recepcionista",
    UserRole.PROFESSIONAL: "Profissional",
    UserRole.VIEWER: "Visualizador",
}

router = APIRouter(prefix="/users", tags=["Users"])

_MANAGE_ROLES = (UserRole.OWNER, UserRole.ADMIN)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    if current_user.role not in _MANAGE_ROLES:
        raise ForbiddenError("Insufficient permissions.")

    if payload.role == UserRole.OWNER and current_user.role != UserRole.OWNER:
        raise ForbiddenError("Only OWNER can create another OWNER.")

    existing = await db.scalar(
        select(func.count()).select_from(User).where(User.email == payload.email)
    )
    if existing:
        raise ConflictError("Email already registered.", code="email_taken")

    # A blank password is allowed for staff who won't log in (e.g. a professional
    # who is only a bookable calendar resource). Generate a strong random one so
    # the account still has a valid hash and can be given credentials later.
    raw_password = payload.password or secrets.token_urlsafe(12)

    user = User(
        tenant_id=tenant_id,
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=hash_password(raw_password),
        role=payload.role,
        is_active=payload.is_active,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ── Invitations (declared before /{user_id} so the literal paths win) ─────────

@router.post("/invite", response_model=InvitationCreateResponse, status_code=status.HTTP_201_CREATED)
async def invite_user(
    payload: InvitationCreate,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    """Invite a teammate by email. Creates an invitation token and (best-effort)
    sends the invite email. If no email provider is configured, the invite link
    is returned for the admin to deliver manually."""
    if current_user.role not in _MANAGE_ROLES:
        raise ForbiddenError("Insufficient permissions.")
    if payload.role == UserRole.OWNER:
        raise ForbiddenError("Não é possível convidar alguém como proprietário.")

    existing = await db.scalar(
        select(func.count()).select_from(User).where(User.email == str(payload.email))
    )
    if existing:
        raise ConflictError("Já existe um usuário com este e-mail.", code="email_taken")

    # Drop any previous pending invite for the same email in this tenant.
    old = await db.execute(
        select(Invitation).where(
            Invitation.tenant_id == tenant_id,
            Invitation.email == str(payload.email),
            Invitation.accepted_at.is_(None),
        )
    )
    for inv in old.scalars().all():
        await db.delete(inv)

    token = secrets.token_urlsafe(32)
    invitation = Invitation(
        tenant_id=tenant_id,
        email=str(payload.email),
        role=payload.role.value,
        token_hash=hash_refresh_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.INVITE_EXPIRE_HOURS),
        invited_by_user_id=current_user.id,
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    invite_link = f"{settings.FRONTEND_BASE_URL}/accept-invite?token={token}"
    tenant = await db.get(Tenant, tenant_id)
    clinic_name = tenant.name if tenant else "sua clínica"
    role_label = _ROLE_LABELS_PT.get(payload.role, "membro")
    email_sent = await send_email(
        to=str(payload.email),
        subject=f"Convite — {clinic_name}",
        html=invite_email_html(clinic_name, role_label, invite_link),
    )

    return InvitationCreateResponse(
        invitation=InvitationRead.model_validate(invitation),
        invite_link=invite_link,
        email_sent=email_sent,
    )


@router.get("/invitations", response_model=list[InvitationRead])
async def list_invitations(
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    """Pending (unaccepted, non-expired) invitations for this clinic."""
    if current_user.role not in _MANAGE_ROLES:
        raise ForbiddenError("Insufficient permissions.")
    rows = await db.execute(
        select(Invitation)
        .where(
            Invitation.tenant_id == tenant_id,
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > datetime.now(timezone.utc),
        )
        .order_by(Invitation.created_at.desc())
    )
    return [InvitationRead.model_validate(i) for i in rows.scalars().all()]


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: uuid.UUID,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    if current_user.role not in _MANAGE_ROLES:
        raise ForbiddenError("Insufficient permissions.")
    inv = await db.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id, Invitation.tenant_id == tenant_id
        )
    )
    if inv is not None:
        await db.delete(inv)
        await db.commit()


@router.get("", response_model=Page[UserRead])
async def list_users(
    db: DBSession,
    tenant_id: CurrentTenantId,
    _: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    include_inactive: bool = Query(default=False),
):
    where = [User.tenant_id == tenant_id]
    if not include_inactive:
        where.append(User.is_active.is_(True))

    total = await db.scalar(select(func.count(User.id)).where(*where))
    rows = await db.execute(
        select(User)
        .where(*where)
        .order_by(User.full_name)
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    return Page[UserRead](
        data=[UserRead.model_validate(u) for u in rows.scalars().all()],
        meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset),
    )


@router.get("/{user_id}", response_model=UserDetailRead)
async def get_user(
    user_id: uuid.UUID,
    db: DBSession,
    tenant_id: CurrentTenantId,
    _: CurrentUser,
):
    user = await _get_detail_or_404(db, user_id, tenant_id)
    return _to_detail(user)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    if current_user.role not in _MANAGE_ROLES:
        raise ForbiddenError("Insufficient permissions.")

    target = await _get_or_404(db, user_id, tenant_id)

    if target.role == UserRole.OWNER and current_user.role != UserRole.OWNER:
        raise ForbiddenError("Only OWNER can edit another OWNER.")

    update_data = payload.model_dump(exclude_unset=True)

    if update_data.get("role") == UserRole.OWNER and current_user.role != UserRole.OWNER:
        raise ForbiddenError("Only OWNER can assign OWNER role.")

    new_email = update_data.get("email")
    if new_email and new_email != target.email:
        conflict = await db.scalar(
            select(func.count()).select_from(User).where(User.email == new_email)
        )
        if conflict:
            raise ConflictError("Email already registered.", code="email_taken")

    password_changed = "password" in update_data
    if password_changed:
        update_data["hashed_password"] = hash_password(update_data.pop("password"))

    deactivated = update_data.get("is_active") is False and target.is_active

    for field, value in update_data.items():
        setattr(target, field, value)

    # Sign-out-everywhere when password changes or account is deactivated
    if password_changed or deactivated:
        await revoke_all_user_tokens(db, target.id)

    await db.commit()
    await db.refresh(target)
    return target


@router.put("/{user_id}/services", response_model=UserDetailRead)
async def set_user_services(
    user_id: uuid.UUID,
    payload: ServiceAssignmentUpdate,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    """Replace the full set of services this professional offers (OWNER / ADMIN)."""
    if current_user.role not in _MANAGE_ROLES:
        raise ForbiddenError("Insufficient permissions.")

    user = await _get_detail_or_404(db, user_id, tenant_id)

    services: list[Service] = []
    if payload.service_ids:
        unique_ids = set(payload.service_ids)
        rows = await db.execute(
            select(Service).where(
                Service.id.in_(unique_ids), Service.tenant_id == tenant_id
            )
        )
        services = list(rows.scalars().all())
        missing = unique_ids - {s.id for s in services}
        if missing:
            raise NotFoundError(
                "Serviço(s) não encontrado(s): " + ", ".join(str(m) for m in missing)
            )

    user.offered_services = services
    await db.commit()

    user = await _get_detail_or_404(db, user_id, tenant_id)
    return _to_detail(user)


@router.put("/{user_id}/work-hours", response_model=UserDetailRead)
async def set_user_work_hours(
    user_id: uuid.UUID,
    payload: WorkHoursUpdate,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    """Replace the full set of weekly work blocks for this professional (OWNER / ADMIN)."""
    if current_user.role not in _MANAGE_ROLES:
        raise ForbiddenError("Insufficient permissions.")

    user = await _get_detail_or_404(db, user_id, tenant_id)

    # cascade="all, delete-orphan" removes the previous blocks on reassignment
    user.work_hours = [
        ProfessionalWorkHours(
            tenant_id=tenant_id,
            professional_id=user.id,
            weekday=b.weekday,
            start_time=b.start_time,
            end_time=b.end_time,
        )
        for b in payload.blocks
    ]
    await db.commit()

    user = await _get_detail_or_404(db, user_id, tenant_id)
    return _to_detail(user)


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _get_or_404(db, user_id: uuid.UUID, tenant_id: uuid.UUID) -> User:
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found.")
    return user


async def _get_detail_or_404(db, user_id: uuid.UUID, tenant_id: uuid.UUID) -> User:
    """Load a user with its offered services + work hours eagerly (async-safe)."""
    result = await db.execute(
        select(User)
        .where(User.id == user_id, User.tenant_id == tenant_id)
        .options(selectinload(User.offered_services), selectinload(User.work_hours))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found.")
    return user


def _to_detail(user: User) -> UserDetailRead:
    return UserDetailRead(
        id=user.id,
        tenant_id=user.tenant_id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        service_ids=[s.id for s in user.offered_services],
        work_hours=[
            WorkHourBlock(weekday=w.weekday, start_time=w.start_time, end_time=w.end_time)
            for w in sorted(user.work_hours, key=lambda x: (x.weekday, x.start_time))
        ],
    )
