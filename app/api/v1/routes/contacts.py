"""
Contacts routes — pacientes e leads da clínica.

GET    /contacts                  — list with last-message preview (paginated)
GET    /contacts/{id}             — detail
GET    /contacts/{id}/messages    — conversation history (paginated)
PATCH  /contacts/{id}             — update data / status
"""

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select

from app.api.deps import CurrentTenantId, CurrentUser, DBSession
from app.core.errors import ForbiddenError, NotFoundError
from app.models.appointment import Appointment
from app.models.contact import Contact, ContactStatus
from app.models.message import Message
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.contact import ContactRead, ContactReadWithLastMessage, ContactUpdate
from app.schemas.message import MessageRead, MessageCreate
from app.services import whatsapp as wa_service
from app.schemas.pagination import Page, PageMeta, PaginationParams, pagination_params

router = APIRouter(prefix="/contacts", tags=["Contacts"])

_WRITE_ROLES = (UserRole.OWNER, UserRole.ADMIN, UserRole.RECEPTIONIST)


@router.get("", response_model=Page[ContactReadWithLastMessage])
async def list_contacts(
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    status_filter: ContactStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, description="Busca por nome ou telefone"),
):
    """
    Inbox-style list: contacts ordered by most recent activity, with the
    latest message preview attached.

    Performance:
      - Single COUNT query for `total`
      - Single SELECT for the page of contacts
      - One batch SELECT for all latest messages of those contacts (no N+1)
    """
    where = [Contact.tenant_id == tenant_id]
    # Professionals only see patients they have appointments with.
    if current_user.role == UserRole.PROFESSIONAL:
        where.append(
            Contact.id.in_(
                select(Appointment.contact_id).where(
                    Appointment.tenant_id == tenant_id,
                    Appointment.professional_id == current_user.id,
                )
            )
        )
    if status_filter:
        where.append(Contact.status == status_filter)
    if search:
        pattern = f"%{search}%"
        where.append(Contact.full_name.ilike(pattern) | Contact.phone.ilike(pattern))

    total = await db.scalar(select(func.count(Contact.id)).where(*where))

    # Outer join messages to get the max created_at for sorting, so old contacts bubble up
    rows = await db.execute(
        select(Contact)
        .outerjoin(Message, Contact.id == Message.contact_id)
        .where(*where)
        .group_by(Contact.id)
        .order_by(
            func.coalesce(func.max(Message.created_at), Contact.created_at).desc()
        )
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    contacts = rows.scalars().all()

    # Batch-fetch the latest message per contact — 2 queries, no N+1
    last_messages: dict[uuid.UUID, Message] = {}
    contact_ids = [c.id for c in contacts]
    if contact_ids:
        latest_subq = (
            select(
                Message.contact_id,
                func.max(Message.created_at).label("max_at"),
            )
            .where(
                Message.tenant_id == tenant_id,
                Message.contact_id.in_(contact_ids),
            )
            .group_by(Message.contact_id)
            .subquery()
        )
        msgs_result = await db.execute(
            select(Message).join(
                latest_subq,
                (Message.contact_id == latest_subq.c.contact_id)
                & (Message.created_at == latest_subq.c.max_at),
            )
        )
        last_messages = {m.contact_id: m for m in msgs_result.scalars().all()}

    return Page[ContactReadWithLastMessage](
        data=[
            ContactReadWithLastMessage(
                **ContactRead.model_validate(c).model_dump(),
                last_message=(
                    MessageRead.model_validate(last_messages[c.id])
                    if c.id in last_messages
                    else None
                ),
            )
            for c in contacts
        ],
        meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset),
    )


@router.get("/{contact_id}", response_model=ContactRead)
async def get_contact(
    contact_id: uuid.UUID,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    return await _get_or_404(db, contact_id, tenant_id, current_user)


@router.get("/{contact_id}/messages", response_model=Page[MessageRead])
async def list_contact_messages(
    contact_id: uuid.UUID,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
):
    """
    Conversation history for a contact, most recent first.
    Tenant-scoped — the contact existence is validated under the same tenant
    before any messages are returned.
    """
    await _get_or_404(db, contact_id, tenant_id, current_user)

    where = [Message.tenant_id == tenant_id, Message.contact_id == contact_id]
    total = await db.scalar(select(func.count(Message.id)).where(*where))

    rows = await db.execute(
        select(Message)
        .where(*where)
        .order_by(desc(Message.created_at))
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    return Page[MessageRead](
        data=[MessageRead.model_validate(m) for m in rows.scalars().all()],
        meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset),
    )


@router.post("/{contact_id}/messages", response_model=MessageRead, status_code=201)
async def send_manual_message(
    contact_id: uuid.UUID,
    payload: MessageCreate,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    """
    Send a manual WhatsApp message to a contact on behalf of the clinic.
    """
    if current_user.role not in _WRITE_ROLES:
        raise ForbiddenError("Insufficient permissions.")

    contact = await _get_or_404(db, contact_id, tenant_id, current_user)

    # Resolve the clinic's UAZAPI instance token from tenant settings
    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    instance_token = (tenant.settings or {}).get("whatsapp", {}).get("token")
    if not instance_token:
        raise ForbiddenError(
            "WhatsApp não está conectado. Conecte-se primeiro nas Configurações."
        )

    # Send via UAZAPI first
    await wa_service.send_text_message(
        instance_token=instance_token,
        phone=contact.phone,
        text=payload.content,
    )

    # Save to database if the send succeeds
    msg = Message(
        tenant_id=tenant_id,
        contact_id=contact.id,
        direction=payload.direction,
        channel=payload.channel,
        content=payload.content,
        ai_model_used=None,  # Manual message, no AI
    )
    db.add(msg)
    # A human on the team just took over this conversation — pause Sofia in the
    # SAME transaction as the send so there's no window for the message_batcher
    # to fire an automatic reply before a separate PATCH would have paused it
    # (the frontend also does this PATCH, but it's now redundant, not load-bearing).
    contact.ai_paused = True
    await db.commit()
    await db.refresh(msg)
    return msg


@router.patch("/{contact_id}", response_model=ContactRead)
async def update_contact(
    contact_id: uuid.UUID,
    payload: ContactUpdate,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    if current_user.role not in _WRITE_ROLES:
        raise ForbiddenError("Insufficient permissions.")

    contact = await _get_or_404(db, contact_id, tenant_id, current_user)
    update_data = payload.model_dump(exclude_unset=True)

    # A manual stage change (Kanban drag) is flagged so the AI won't auto-regress it.
    if "crm_stage" in update_data and update_data["crm_stage"] != contact.crm_stage:
        contact.crm_stage_source = "manual"
        contact.crm_stage_updated_at = datetime.now(timezone.utc)

    for field, value in update_data.items():
        setattr(contact, field, value)

    await db.commit()
    await db.refresh(contact)
    return contact


@router.post("/{contact_id}/messages/media", response_model=MessageRead, status_code=201)
async def send_media_message(
    contact_id: uuid.UUID,
    payload: dict,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    """
    Send a media WhatsApp message (audio, image, document) to a contact.
    Payload: { media_type, media (base64 data URI), caption?, file_name? }
    """
    if current_user.role not in _WRITE_ROLES:
        raise ForbiddenError("Insufficient permissions.")

    contact = await _get_or_404(db, contact_id, tenant_id, current_user)

    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    instance_token = (tenant.settings or {}).get("whatsapp", {}).get("token")
    if not instance_token:
        raise ForbiddenError(
            "WhatsApp não está conectado. Conecte-se primeiro nas Configurações."
        )

    media_type = payload.get("media_type", "audio")
    media_data = payload.get("media", "")
    caption = payload.get("caption", "")
    file_name = payload.get("file_name", "")

    await wa_service.send_media_message(
        instance_token=instance_token,
        phone=contact.phone,
        media_type=media_type,
        media=media_data,
        caption=caption,
        file_name=file_name,
    )

    # Save record to database
    # For audio, save the data URI so it can be played back in the inbox.
    # For other types, save a label.
    if media_type == "audio":
        content_value = media_data  # full data URI (data:audio/webm;base64,...)
    else:
        content_value = f"[{media_type.upper()}]"
        if caption:
            content_value += f" {caption}"

    msg = Message(
        tenant_id=tenant_id,
        contact_id=contact.id,
        direction="outbound",
        channel="whatsapp",
        content=content_value,
        ai_model_used=None,
    )
    db.add(msg)
    # Same rationale as send_manual_message: pause Sofia server-side, in the same
    # commit as the send, so the message_batcher can't race an automatic reply.
    contact.ai_paused = True
    await db.commit()
    await db.refresh(msg)
    return msg


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _professional_has_access(
    db, contact_id: uuid.UUID, tenant_id: uuid.UUID, professional_id: uuid.UUID
) -> bool:
    """A `professional` may only access a contact they have an appointment with."""
    result = await db.execute(
        select(Appointment.id)
        .where(
            Appointment.tenant_id == tenant_id,
            Appointment.contact_id == contact_id,
            Appointment.professional_id == professional_id,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _get_or_404(
    db,
    contact_id: uuid.UUID,
    tenant_id: uuid.UUID,
    current_user: User | None = None,
) -> Contact:
    result = await db.execute(
        select(Contact).where(Contact.id == contact_id, Contact.tenant_id == tenant_id)
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise NotFoundError("Contact not found.")

    # Same scope rule as list_contacts: a professional only reaches contacts they
    # have an appointment with. 404 (not 403) so the endpoint doesn't confirm
    # the contact exists in the clinic to a professional with no relation to it.
    if current_user is not None and current_user.role == UserRole.PROFESSIONAL:
        if not await _professional_has_access(db, contact_id, tenant_id, current_user.id):
            raise NotFoundError("Contact not found.")

    return contact
