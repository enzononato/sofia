"""
Schemas for the LGPD data-export / anonymization endpoints
(app/api/v1/routes/privacy.py, app/services/privacy.py).
"""

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from app.models.appointment import AppointmentStatus
from app.models.message import MessageChannel, MessageDirection


class ContactExportProfile(BaseModel):
    """Registration data — the PII fields that identify the patient."""

    id: uuid.UUID
    full_name: str
    email: str | None
    phone: str | None
    date_of_birth: date | None
    gender: str | None
    address: str | None
    medical_notes: dict[str, Any] | None
    whatsapp_name: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class ContactExportCrm(BaseModel):
    """Current CRM pipeline state. There is no separate stage-history table
    today — crm_stage/_source/_updated_at are the only state kept, so that is
    what gets exported here (documented so a future audit-log addition knows
    where to plug in)."""

    crm_stage: str
    crm_stage_source: str
    crm_stage_updated_at: datetime | None
    last_inbound_at: datetime | None
    last_followup_at: datetime | None


class ContactExportMessage(BaseModel):
    """A single message. The raw `media_url` (base64 data URI, can be several
    MB per audio/image) is intentionally NOT included in the export to keep
    the JSON response a reasonable size — only its metadata is. If the raw
    bytes are ever required for a portability request, they can be fetched
    per-message via GET /contacts/{id}/messages."""

    id: uuid.UUID
    direction: MessageDirection
    channel: MessageChannel
    content: str
    created_at: datetime
    has_media: bool
    media_type: str | None
    media_mime_type: str | None
    media_size_bytes: int | None


class ContactExportAppointment(BaseModel):
    id: uuid.UUID
    service_id: uuid.UUID | None
    professional_id: uuid.UUID | None
    scheduled_at: datetime
    ends_at: datetime | None
    status: AppointmentStatus
    notes: str | None
    cancellation_reason: str | None
    created_at: datetime


class ContactExportMeta(BaseModel):
    exported_at: datetime
    exported_by_user_id: uuid.UUID
    tenant_id: uuid.UUID
    message_count: int
    appointment_count: int


class ContactExport(BaseModel):
    """Full structured export of everything the system holds about one
    contact — registration data, conversation history, appointments, and
    current CRM state. Intended for the clinic to hand over to a patient
    exercising their LGPD data-access/portability right."""

    meta: ContactExportMeta
    profile: ContactExportProfile
    crm: ContactExportCrm
    messages: list[ContactExportMessage]
    appointments: list[ContactExportAppointment]


class ContactAnonymizeResult(BaseModel):
    """Result of an anonymization request."""

    id: uuid.UUID
    anonymized_at: datetime
    anonymized_by_user_id: uuid.UUID
    messages_scrubbed: int
    detail: str
