"""
LGPD manual data-export and anonymization for a single Contact.

Both operations are triggered explicitly by an authenticated clinic user —
there is no background job, scheduler, or automatic retention policy here by
design (out of scope for this slice). `tenant_id` is always supplied by the
caller from `CurrentTenantId` (never trusted from a payload); every query in
this module is scoped by it.

Anonymization design notes (documented here because they have real
consequences for other subsystems):

  - Contact PII fields are scrubbed in place (full_name, email, phone,
    date_of_birth, gender, address, medical_notes, whatsapp_name,
    profile_picture_url) rather than deleting the row, so `Appointment` and
    `Message` rows (FK to contacts.id) keep working and clinic reporting
    that aggregates over appointments doesn't silently lose history.

  - `phone` is cleared (set to NULL), not hashed or replaced with a
    placeholder. This is a deliberate "right to be forgotten" choice:
    `app/api/v1/routes/webhooks.py::_find_or_create_contact` looks up a
    Contact by `(tenant_id, phone)` on every inbound WhatsApp message. If we
    left the real phone number on the anonymized row, a new message from
    that number would keep landing on this now-anonymous Contact — which
    might be desirable ("same patient, we just forgot who they are") but
    contradicts the stated goal of *forgetting* the patient. Clearing the
    phone means a future message from that number is treated as a brand
    new lead (fresh Contact, fresh CRM stage) — the phone may have been
    recycled to a different person anyway, so this is also the safer
    default. Whoever owns webhooks.py should be aware: anonymized contacts
    are invisible to phone-based lookup from that point on.

  - Message rows for the contact are NOT deleted — only `content` and
    `media_url`/media metadata are cleared. `direction`, `channel`, and
    `created_at` are kept so aggregate reporting (message volume per day,
    response-time metrics, etc.) doesn't develop holes. `whatsapp_message_id`
    is also cleared since it is an external correlation ID tied to the real
    WhatsApp conversation.

  - This action is irreversible. There is no "un-anonymize". Callers should
    confirm with the clinic user before invoking it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.appointment import Appointment
from app.models.contact import Contact
from app.models.message import Message

logger = logging.getLogger("app.privacy")

_ANONYMIZED_NAME = "Paciente anonimizado"


async def _get_contact_or_404(db: AsyncSession, contact_id: uuid.UUID, tenant_id: uuid.UUID) -> Contact:
    result = await db.execute(
        select(Contact).where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise NotFoundError("Contact not found.")
    return contact


async def export_contact_data(
    db: AsyncSession, contact_id: uuid.UUID, tenant_id: uuid.UUID, exported_by_user_id: uuid.UUID
) -> dict:
    """
    Build a full structured export of everything the system holds about one
    contact: registration data, every message, every appointment, and the
    current CRM state. Read-only — makes no changes.

    Returns a plain dict shaped like app.schemas.privacy.ContactExport so the
    route can validate/serialize it.
    """
    contact = await _get_contact_or_404(db, contact_id, tenant_id)

    messages_result = await db.execute(
        select(Message)
        .where(Message.tenant_id == tenant_id, Message.contact_id == contact_id)
        .order_by(Message.created_at.asc())
    )
    messages = messages_result.scalars().all()

    appointments_result = await db.execute(
        select(Appointment)
        .where(Appointment.tenant_id == tenant_id, Appointment.contact_id == contact_id)
        .order_by(Appointment.scheduled_at.asc())
    )
    appointments = appointments_result.scalars().all()

    now = datetime.now(timezone.utc)

    return {
        "meta": {
            "exported_at": now,
            "exported_by_user_id": exported_by_user_id,
            "tenant_id": tenant_id,
            "message_count": len(messages),
            "appointment_count": len(appointments),
        },
        "profile": {
            "id": contact.id,
            "full_name": contact.full_name,
            "email": contact.email,
            "phone": contact.phone,
            "date_of_birth": contact.date_of_birth,
            "gender": contact.gender,
            "address": contact.address,
            "medical_notes": contact.medical_notes,
            "whatsapp_name": contact.whatsapp_name,
            "status": contact.status,
            "created_at": contact.created_at,
            "updated_at": contact.updated_at,
        },
        "crm": {
            "crm_stage": contact.crm_stage,
            "crm_stage_source": contact.crm_stage_source,
            "crm_stage_updated_at": contact.crm_stage_updated_at,
            "last_inbound_at": contact.last_inbound_at,
            "last_followup_at": contact.last_followup_at,
        },
        "messages": [
            {
                "id": m.id,
                "direction": m.direction,
                "channel": m.channel,
                "content": m.content,
                "created_at": m.created_at,
                "has_media": m.media_url is not None,
                "media_type": m.media_type,
                "media_mime_type": m.media_mime_type,
                "media_size_bytes": m.media_size_bytes,
            }
            for m in messages
        ],
        "appointments": [
            {
                "id": a.id,
                "service_id": a.service_id,
                "professional_id": a.professional_id,
                "scheduled_at": a.scheduled_at,
                "ends_at": a.ends_at,
                "status": a.status,
                "notes": a.notes,
                "cancellation_reason": a.cancellation_reason,
                "created_at": a.created_at,
            }
            for a in appointments
        ],
    }


async def anonymize_contact(
    db: AsyncSession, contact_id: uuid.UUID, tenant_id: uuid.UUID, anonymized_by_user_id: uuid.UUID
) -> dict:
    """
    Irreversibly scrub PII from a Contact and its Message history.

    Idempotent: calling this twice on an already-anonymized contact is a
    no-op for the PII fields (they are already scrubbed) but re-stamps
    `anonymized_at`/`anonymized_by_user_id` to the latest call, and message
    scrubbing is naturally idempotent (clearing an already-empty field).
    Does not raise or error on a second call.

    Commits the transaction itself (matches the mutating-route convention
    used elsewhere in this codebase, e.g. contacts.py).
    """
    contact = await _get_contact_or_404(db, contact_id, tenant_id)

    already_anonymized = contact.anonymized_at is not None

    contact.full_name = _ANONYMIZED_NAME
    contact.email = None
    contact.phone = None  # see module docstring: clears phone-based re-linking on future messages
    contact.date_of_birth = None
    contact.gender = None
    contact.address = None
    contact.medical_notes = None
    contact.whatsapp_name = None
    contact.profile_picture_url = None
    contact.ai_thread_id = None

    now = datetime.now(timezone.utc)
    contact.anonymized_at = now
    contact.anonymized_by_user_id = anonymized_by_user_id

    messages_result = await db.execute(
        select(Message).where(Message.tenant_id == tenant_id, Message.contact_id == contact_id)
    )
    messages = messages_result.scalars().all()
    for m in messages:
        m.content = ""
        m.media_url = None
        m.media_type = None
        m.media_mime_type = None
        m.media_size_bytes = None
        m.whatsapp_message_id = None

    await db.commit()
    await db.refresh(contact)

    logger.warning(
        "contact_anonymized tenant_id=%s contact_id=%s by_user_id=%s messages_scrubbed=%d "
        "already_anonymized_before=%s",
        tenant_id,
        contact_id,
        anonymized_by_user_id,
        len(messages),
        already_anonymized,
    )

    return {
        "id": contact.id,
        "anonymized_at": contact.anonymized_at,
        "anonymized_by_user_id": contact.anonymized_by_user_id,
        "messages_scrubbed": len(messages),
        "detail": (
            "Contact anonymized. This action is irreversible."
            if not already_anonymized
            else "Contact was already anonymized; PII fields re-confirmed as scrubbed."
        ),
    }
