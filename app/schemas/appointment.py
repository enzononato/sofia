import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.appointment import AppointmentStatus


class AppointmentBase(BaseModel):
    contact_id: uuid.UUID
    service_id: uuid.UUID | None = None
    professional_id: uuid.UUID | None = None
    scheduled_at: datetime
    ends_at: datetime | None = None
    status: AppointmentStatus = AppointmentStatus.SCHEDULED
    notes: str | None = None
    cancellation_reason: str | None = None

    @model_validator(mode="after")
    def ends_at_after_scheduled(self) -> "AppointmentBase":
        if self.ends_at and self.ends_at <= self.scheduled_at:
            raise ValueError("ends_at must be after scheduled_at")
        return self


class AppointmentCreate(AppointmentBase):
    pass


class AppointmentUpdate(BaseModel):
    service_id: uuid.UUID | None = None
    professional_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    ends_at: datetime | None = None
    status: AppointmentStatus | None = None
    notes: str | None = None
    cancellation_reason: str | None = None


class AppointmentRead(AppointmentBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
