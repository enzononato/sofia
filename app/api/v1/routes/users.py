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

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentTenantId, CurrentUser, DBSession
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.schemas.pagination import Page, PageMeta, PaginationParams, pagination_params
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.tokens import revoke_all_user_tokens

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

    user = User(
        tenant_id=tenant_id,
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        is_active=payload.is_active,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


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


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: uuid.UUID,
    db: DBSession,
    tenant_id: CurrentTenantId,
    _: CurrentUser,
):
    return await _get_or_404(db, user_id, tenant_id)


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


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _get_or_404(db, user_id: uuid.UUID, tenant_id: uuid.UUID) -> User:
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found.")
    return user
