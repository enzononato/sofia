import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.tenant import TenantPlan


class TenantBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    email: EmailStr
    phone: str | None = None
    address: str | None = None
    plan: TenantPlan = TenantPlan.FREE
    ai_config: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None


class TenantCreate(TenantBase):
    pass


class TenantUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    plan: TenantPlan | None = None
    is_active: bool | None = None
    ai_config: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None


class TenantRead(TenantBase):
    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
