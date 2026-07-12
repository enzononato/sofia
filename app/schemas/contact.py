import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.models.contact import ContactStatus, CrmStage
from app.schemas.message import MessagePreview


class ContactBase(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    date_of_birth: date | None = None
    gender: str | None = Field(None, max_length=20)
    address: str | None = None
    medical_notes: dict[str, Any] | None = None
    status: ContactStatus = ContactStatus.LEAD
    crm_stage: CrmStage = CrmStage.NEW_LEAD
    ai_thread_id: str | None = None
    whatsapp_name: str | None = None
    profile_picture_url: str | None = None
    ai_paused: bool = False


class ContactCreate(ContactBase):
    pass


class ContactUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=255)
    email: EmailStr | None = None
    phone: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    address: str | None = None
    medical_notes: dict[str, Any] | None = None
    status: ContactStatus | None = None
    crm_stage: CrmStage | None = None
    ai_thread_id: str | None = None
    whatsapp_name: str | None = None
    profile_picture_url: str | None = None
    ai_paused: bool | None = None


class ContactRead(ContactBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    crm_stage_source: str | None = None
    crm_stage_updated_at: datetime | None = None
    last_inbound_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContactReadWithLastMessage(ContactRead):
    last_message: MessagePreview | None = None
