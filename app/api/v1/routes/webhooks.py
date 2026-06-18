"""
WhatsApp webhook receiver (Evolution API).

Endpoint: POST /api/v1/webhooks/whatsapp/{tenant_slug}

This route is intentionally PUBLIC — Evolution API sends requests from its own
servers with no X-Tenant-ID header. Tenant isolation is enforced by:
  1. Resolving the tenant from {tenant_slug} in the URL path.
  2. Validating the per-tenant webhook_secret before any processing.
  3. Scoping every DB write with the resolved tenant_id.

The handler returns 200 immediately and processes the message in a
FastAPI BackgroundTask to avoid blocking Evolution API's retry logic.
"""

import base64
import logging
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.contact import Contact, ContactStatus
from app.models.message import Message, MessageChannel, MessageDirection
from app.models.tenant import Tenant
from app.services import ai as ai_service
from app.services import whatsapp as wa_service
from app.services import whatsapp_instance as wi
from app.core.errors import NotFoundError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/whatsapp/{tenant_slug}", status_code=status.HTTP_200_OK)
async def whatsapp_webhook(
    tenant_slug: str,
    request: Request,
    background_tasks: BackgroundTasks,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
):
    """
    Receive an Evolution API webhook event.
    Validates the tenant + secret, then processes the message in the background.
    Always returns 200 so Evolution API does not keep retrying.
    """
    rid = getattr(request.state, "request_id", None)
    body = await request.json()

    raw_event = body.get("event", "")
    event = raw_event.lower().replace("_", ".").replace("-", ".")

    logger.debug(
        "webhook_received",
        extra={"request_id": rid, "event": raw_event, "tenant_slug": tenant_slug},
    )

    if event == "connection.update":
        raw_state = body.get("data", {}).get("state", "close")
        state_map = {"open": "connected", "close": "disconnected", "connecting": "connecting"}
        new_status = state_map.get(raw_state, "disconnected")

        async with AsyncSessionLocal() as db:
            tenant = await _resolve_tenant_or_none(db, tenant_slug)
            if tenant is None:
                return {"received": True}

            expected_secret = (tenant.settings or {}).get("whatsapp", {}).get("webhook_secret")
            if expected_secret and x_webhook_secret != expected_secret:
                logger.warning(
                    "webhook_invalid_secret",
                    extra={"request_id": rid, "tenant_id": str(tenant.id), "event": event},
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret."
                )

            wa = dict((tenant.settings or {}).get("whatsapp", {}))
            if wa.get("status") != new_status:
                wa["status"] = new_status
                tenant.settings = {**(tenant.settings or {}), "whatsapp": dict(wa)}
                await db.commit()
            logger.info(
                "whatsapp_connection_update",
                extra={
                    "request_id": rid,
                    "tenant_id": str(tenant.id),
                    "state": raw_state,
                    "status": new_status,
                },
            )
        return {"received": True}

    if event != "messages.upsert":
        logger.info(
            "webhook_event_ignored",
            extra={"request_id": rid, "event": raw_event, "tenant_slug": tenant_slug},
        )
        return {"received": True}

    data = body.get("data", {})
    key = data.get("key", {})

    # ── Diagnostic: log raw payload shape so we can debug structure mismatches ──
    logger.debug(
        "webhook_raw_payload",
        extra={
            "request_id": rid,
            "tenant_slug": tenant_slug,
            "data_keys": list(data.keys()),
            "key": key,
            "fromMe": key.get("fromMe"),
            "remoteJid": key.get("remoteJid", ""),
            "pushName": data.get("pushName", ""),
            "has_message": "message" in data,
            "message_keys": list(data.get("message", {}).keys()) if isinstance(data.get("message"), dict) else str(type(data.get("message"))),
        },
    )

    # Ignore messages sent by the clinic itself (avoid infinite loops)
    if key.get("fromMe", False):
        logger.debug(
            "webhook_from_me_skipped",
            extra={
                "request_id": rid,
                "tenant_slug": tenant_slug,
                "remoteJid": key.get("remoteJid", ""),
            },
        )
        return {"received": True}

    async with AsyncSessionLocal() as db:
        tenant = await _resolve_tenant_or_none(db, tenant_slug)

    if tenant is None:
        logger.warning(
            "webhook_unknown_tenant",
            extra={"request_id": rid, "tenant_slug": tenant_slug},
        )
        return {"received": True}

    expected_secret = (tenant.settings or {}).get("whatsapp", {}).get("webhook_secret")
    if expected_secret and x_webhook_secret != expected_secret:
        logger.warning(
            "webhook_invalid_secret",
            extra={"request_id": rid, "tenant_id": str(tenant.id), "tenant_slug": tenant_slug},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret."
        )

    logger.info(
        "webhook_dispatching_to_background",
        extra={"request_id": rid, "tenant_id": str(tenant.id), "tenant_slug": tenant_slug},
    )
    background_tasks.add_task(_process_inbound_message, tenant, data, rid)
    return {"received": True}


_MEDIA_KIND_BY_KEY = {
    "audioMessage": "audio",
    "imageMessage": "image",
    "videoMessage": "video",
    "documentMessage": "document",
}

_MULTIMODAL_DISABLED_REPLY = {
    "audio": "Recebi seu áudio! No momento, só consigo responder mensagens de texto. Por favor, escreva sua mensagem. 😊",
    "image": "Recebi sua imagem! No momento, só consigo responder mensagens de texto. 😊",
    "video": "Recebi seu vídeo! No momento, só consigo responder mensagens de texto. 😊",
    "document": "Recebi seu documento! No momento, só consigo responder mensagens de texto. 😊",
}

_AUDIO_MAX_SECONDS = 90  # 1m30s


def _detect_media(message_obj: dict) -> tuple[str, dict] | None:
    """Returns (media_kind, sub_payload) for the first media key found, or None."""
    for key, kind in _MEDIA_KIND_BY_KEY.items():
        if key in message_obj and isinstance(message_obj[key], dict):
            return kind, message_obj[key]
    return None


async def _process_inbound_message(tenant: Tenant, data: dict, request_id: str | None) -> None:
    """
    Two-phase pipeline:
      Phase 1 (own transaction): save inbound → committed immediately, visible in inbox.
      Phase 2 (own transaction): fetch history → AI reply → save outbound → commit → send.

    Splitting transactions ensures the inbound message appears in the inbox without
    waiting for the AI (~1-5 s). Tool writes from the AI share Phase 2's transaction
    and are rolled back atomically with the outbound message on failure.

    Multimodal: when message contains audio/image/video/document AND the tenant has
    multimodal_enabled=true in ai_config, the bytes are downloaded from Evolution,
    persisted as a data URI in media_url, and forwarded to Gemini as inline_data.
    """
    log_ctx = {"request_id": request_id, "tenant_id": str(tenant.id)}

    try:
        key = data.get("key", {})
        message_obj = data.get("message", {})

        remote_jid: str = key.get("remoteJid", "")
        phone = remote_jid.replace("@s.whatsapp.net", "").replace("@c.us", "")
        push_name: str = data.get("pushName", "")
        whatsapp_msg_id: str = key.get("id", "")

        msg_timestamp = data.get("messageTimestamp", 0)
        is_historical = msg_timestamp > 0 and (time.time() - msg_timestamp) > 300

        # Caption / text part of the message (may be empty when media-only)
        caption = (
            message_obj.get("conversation")
            or message_obj.get("extendedTextMessage", {}).get("text")
            or message_obj.get("imageMessage", {}).get("caption")
            or message_obj.get("videoMessage", {}).get("caption")
            or message_obj.get("documentMessage", {}).get("caption")
            or ""
        ).strip()

        instance_name = (tenant.settings or {}).get("whatsapp", {}).get("instance")
        ai_cfg = tenant.ai_config or {}
        multimodal_enabled = bool(ai_cfg.get("multimodal_enabled", False))

        media_info = _detect_media(message_obj)

        # Defaults — populated below for the media path
        media_type: str | None = None
        media_mime_type: str | None = None
        media_size_bytes: int | None = None
        media_url: str | None = None
        media_bytes: bytes | None = None

        # ── Pure text fast path ────────────────────────────────────────────
        if media_info is None:
            if not caption:
                logger.info("webhook_non_text_ignored", extra={**log_ctx, "phone": phone})
                return
            content = caption

        # ── Media path ─────────────────────────────────────────────────────
        else:
            kind, sub = media_info

            # Multimodal disabled → polite refusal (skip for historical sync)
            if not multimodal_enabled:
                if not is_historical and instance_name:
                    await wa_service.send_text_message(
                        instance_name=instance_name,
                        phone=phone,
                        text=_MULTIMODAL_DISABLED_REPLY[kind],
                    )
                    logger.info(
                        "webhook_media_refused_disabled",
                        extra={**log_ctx, "phone": phone, "media_type": kind},
                    )
                else:
                    logger.info(
                        "webhook_media_ignored_historical",
                        extra={**log_ctx, "phone": phone, "media_type": kind},
                    )
                return

            # Audio length cap
            if kind == "audio":
                duration_s = sub.get("seconds")
                if duration_s and duration_s > _AUDIO_MAX_SECONDS:
                    if not is_historical and instance_name:
                        await wa_service.send_text_message(
                            instance_name=instance_name,
                            phone=phone,
                            text=(
                                "Recebi seu áudio, mas ele está muito longo (máximo 1m30s). "
                                "Por favor, envie um áudio mais curto ou escreva sua mensagem. 😊"
                            ),
                        )
                    logger.info(
                        "webhook_audio_too_long",
                        extra={**log_ctx, "phone": phone, "duration_s": duration_s},
                    )
                    return

            if not instance_name:
                logger.error("webhook_no_instance_for_download", extra=log_ctx)
                return

            # Download bytes from Evolution
            download = await wi.download_media_base64(instance_name, data)
            if download is None:
                logger.warning(
                    "webhook_media_download_giving_up",
                    extra={**log_ctx, "phone": phone, "media_type": kind},
                )
                return

            base64_data, mimetype, size_bytes = download
            media_type = kind
            media_mime_type = mimetype
            media_size_bytes = size_bytes
            media_url = f"data:{mimetype};base64,{base64_data}"
            media_bytes = base64.b64decode(base64_data)
            content = caption  # may be empty — that's fine, frontend renders the media

        # ── Phase 1: persist inbound immediately ─────────────────────────────
        async with AsyncSessionLocal() as db:
            try:
                # Idempotency: Evolution may re-deliver the same event. Skip if we
                # already stored this WhatsApp message id for this tenant.
                if whatsapp_msg_id:
                    dup = await db.scalar(
                        select(Message.id).where(
                            Message.tenant_id == tenant.id,
                            Message.whatsapp_message_id == whatsapp_msg_id,
                        )
                    )
                    if dup is not None:
                        logger.info(
                            "webhook_duplicate_skipped",
                            extra={**log_ctx, "phone": phone, "whatsapp_message_id": whatsapp_msg_id},
                        )
                        return

                contact = await _find_or_create_contact(db, tenant, phone, push_name, data=data)
                ai_paused = contact.ai_paused

                inbound_msg = Message(
                    tenant_id=tenant.id,
                    contact_id=contact.id,
                    direction=MessageDirection.INBOUND,
                    channel=MessageChannel.WHATSAPP,
                    content=content,
                    whatsapp_message_id=whatsapp_msg_id,
                    media_type=media_type,
                    media_mime_type=media_mime_type,
                    media_size_bytes=media_size_bytes,
                    media_url=media_url,
                )
                db.add(inbound_msg)
                await db.commit()

                contact_id = contact.id
                inbound_id = inbound_msg.id
            except Exception:
                await db.rollback()
                raise

        if is_historical:
            logger.info(
                "webhook_historical_saved",
                extra={**log_ctx, "phone": phone, "age_s": int(time.time() - msg_timestamp)},
            )
            return

        if ai_paused:
            logger.info("webhook_ai_paused", extra={**log_ctx, "phone": phone, "contact_id": str(contact_id)})
            return

        # ── Phase 2: AI reply (tool writes share this transaction) ────────────
        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(select(Contact).where(Contact.id == contact_id))
                contact = result.scalar_one()

                history = await _fetch_history(db, tenant.id, contact_id, exclude_id=inbound_id)

                reply_text, model_used = await ai_service.generate_reply(
                    tenant=tenant,
                    contact=contact,
                    new_message=content,
                    history=history,
                    db=db,
                    media=(media_bytes, media_mime_type) if media_bytes else None,
                )

                outbound_msg = Message(
                    tenant_id=tenant.id,
                    contact_id=contact_id,
                    direction=MessageDirection.OUTBOUND,
                    channel=MessageChannel.WHATSAPP,
                    content=reply_text,
                    ai_model_used=model_used,
                )
                db.add(outbound_msg)
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        if not instance_name:
            logger.error("webhook_no_instance", extra=log_ctx)
            return

        await wa_service.send_text_message(
            instance_name=instance_name, phone=phone, text=reply_text,
        )

        logger.info(
            "webhook_processed",
            extra={
                **log_ctx,
                "phone": phone,
                "contact_id": str(contact_id),
                "model": model_used,
                "media_type": media_type,
            },
        )

    except Exception:
        logger.exception("webhook_processing_error", extra=log_ctx)


async def _resolve_tenant_or_none(db: AsyncSession, slug: str) -> Tenant | None:
    result = await db.execute(
        select(Tenant).where(Tenant.slug == slug, Tenant.is_active.is_(True))
    )
    return result.scalar_one_or_none()


async def _find_or_create_contact(
    db: AsyncSession, tenant: Tenant, phone: str, push_name: str, data: dict = None
) -> Contact:
    """
    Look up a Contact by phone within the tenant. Creates a new lead if not found.
    tenant_id is always taken from the resolved tenant — never from external input.
    """
    result = await db.execute(
        select(Contact).where(Contact.tenant_id == tenant.id, Contact.phone == phone)
    )
    contact = result.scalar_one_or_none()

    if contact is None:
        data = data or {}
        # Try to extract the saved contact name if available in the webhook, otherwise fallback to pushName
        contact_name = data.get("contact", {}).get("name")
        display_name = contact_name or push_name or phone

        contact = Contact(
            tenant_id=tenant.id,
            full_name=display_name,
            whatsapp_name=push_name,
            phone=phone,
            status=ContactStatus.LEAD,
            ai_paused=False,
        )
        db.add(contact)
        await db.flush()

        # Fetch profile picture concurrently in the background if possible, or wait for it
        instance_name = (tenant.settings or {}).get("whatsapp", {}).get("instance")
        if instance_name:
            pic_url = await wi.fetch_profile_picture(instance_name, phone)
            if pic_url:
                contact.profile_picture_url = pic_url
                db.add(contact)
                await db.flush()

        logger.info(
            "contact_created_from_webhook",
            extra={"tenant_id": str(tenant.id), "contact_id": str(contact.id), "phone": phone},
        )

    return contact


async def _fetch_history(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    exclude_id: uuid.UUID,
) -> list[Message]:
    """Latest messages, oldest-first (correct order for the AI prompt)."""
    result = await db.execute(
        select(Message)
        .where(
            Message.tenant_id == tenant_id,
            Message.contact_id == contact_id,
            Message.id != exclude_id,
        )
        .order_by(desc(Message.created_at))
        .limit(settings.AI_HISTORY_LIMIT)
    )
    return list(reversed(result.scalars().all()))
