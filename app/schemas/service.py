import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ServiceBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    description: str | None = None
    duration_minutes: int = Field(60, ge=5, le=480)
    price: Decimal | None = Field(None, ge=0, decimal_places=2)
    is_active: bool = True


class ServiceCreate(ServiceBase):
    pass


class ServiceUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    description: str | None = None
    duration_minutes: int | None = Field(None, ge=5, le=480)
    price: Decimal | None = Field(None, ge=0, decimal_places=2)
    is_active: bool | None = None


class ServiceRead(ServiceBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
