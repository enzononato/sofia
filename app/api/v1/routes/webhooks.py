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

import asyncio
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
from app.services import crm
from app.services import humanizer
from app.services import message_batcher as batcher
from app.services import whatsapp as wa_service
from app.services import whatsapp_instance as wi

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

    # Ignore WhatsApp group messages when the tenant has ignore_groups enabled (default: True)
    remote_jid: str = key.get("remoteJid", "")
    ignore_groups: bool = (tenant.settings or {}).get("ignore_groups", True)
    if ignore_groups and remote_jid.endswith("@g.us"):
        logger.info(
            "webhook_group_skipped",
            extra={"request_id": rid, "tenant_id": str(tenant.id), "jid": remote_jid},
        )
        return {"received": True}

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

        # Defaults — populated below for the media path. The decoded bytes are no
        # longer kept here: Phase 2 reconstructs media from the stored data URI.
        media_type: str | None = None
        media_mime_type: str | None = None
        media_size_bytes: int | None = None
        media_url: str | None = None

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

            # File size cap — reject files > 20 MB (protects Gemini and DB)
            _MAX_MEDIA_BYTES = 20 * 1024 * 1024
            if size_bytes > _MAX_MEDIA_BYTES:
                if not is_historical and instance_name:
                    kind_label = {"audio": "áudio", "image": "imagem", "video": "vídeo", "document": "documento"}.get(kind, kind)
                    await wa_service.send_text_message(
                        instance_name=instance_name,
                        phone=phone,
                        text=f"Recebi seu {kind_label}, mas ele é muito grande para processar (máximo 20 MB). Por favor, envie um arquivo menor. 😊",
                    )
                logger.info(
                    "webhook_media_too_large",
                    extra={**log_ctx, "phone": phone, "media_type": kind, "size_bytes": size_bytes},
                )
                return

            media_type = kind
            media_mime_type = mimetype
            media_size_bytes = size_bytes
            media_url = f"data:{mimetype};base64,{base64_data}"
            # For documents, use the original filename as content when there is no caption
            if kind == "document" and not caption:
                content = sub.get("fileName") or ""
            else:
                content = caption

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

                # CRM: record live inbound activity (powers re-engagement) and nudge
                # a brand-new lead into "in_conversation". Skip for historical sync.
                if not is_historical:
                    crm.mark_inbound(contact)

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

        if not instance_name:
            logger.error("webhook_no_instance", extra=log_ctx)
            return

        # ── Phase 2 dispatch: debounce text bursts; flush media immediately ────
        # The actual reply runs in _generate_and_send, which re-reads the
        # unanswered messages from the DB — so it naturally covers every message
        # accumulated during the debounce window.
        has_media = media_type is not None

        async def _work() -> None:
            await _generate_and_send(
                tenant=tenant,
                contact_id=contact_id,
                phone=phone,
                instance_name=instance_name,
                request_id=request_id,
            )

        if has_media:
            await batcher.flush(contact_id, _work)
        else:
            batcher.schedule(contact_id, _work)

    except Exception:
        logger.exception("webhook_processing_error", extra=log_ctx)


async def _generate_and_send(
    tenant: Tenant,
    contact_id: uuid.UUID,
    phone: str,
    instance_name: str,
    request_id: str | None,
) -> None:
    """
    Produce and deliver Sofia's reply for all messages a contact sent during the
    debounce window, simulating human behavior:
      1. Mark the patient's messages as read (read receipt).
      2. Generate one reply over the combined unanswered messages.
      3. Split it into natural parts; send each with a "typing" presence and a
         randomized, length-proportional delay.

    AI tool writes are committed right after generation (before sending), so a
    later WhatsApp delivery error never rolls back a booking the AI made.
    """
    log_ctx = {"request_id": request_id, "tenant_id": str(tenant.id), "contact_id": str(contact_id)}
    remote_jid = f"{phone}@s.whatsapp.net"

    async with AsyncSessionLocal() as db:
        try:
            contact = await db.scalar(select(Contact).where(Contact.id == contact_id))
            if contact is None:
                logger.warning("webhook_contact_missing", extra=log_ctx)
                return

            # The admin may have paused the AI during the debounce window.
            if contact.ai_paused:
                logger.info("webhook_ai_paused_late", extra=log_ctx)
                return

            unanswered = await _collect_unanswered(db, tenant.id, contact_id)
            if not unanswered:
                logger.info("webhook_nothing_to_answer", extra=log_ctx)
                return

            exclude_ids = {m.id for m in unanswered}
            wa_ids = [m.whatsapp_message_id for m in unanswered if m.whatsapp_message_id]
            combined_text = "\n".join(m.content for m in unanswered if m.content).strip()
            media = _latest_media(unanswered)

            history = await _fetch_history(db, tenant.id, contact_id, exclude_ids=exclude_ids)

            reply_text, model_used = await ai_service.generate_reply(
                tenant=tenant,
                contact=contact,
                new_message=combined_text,
                history=history,
                db=db,
                media=media,
            )
            # Persist any tool writes (e.g. create_appointment) now.
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    # ── Read receipt before replying (best-effort) ───────────────────────────
    if settings.READ_RECEIPT_ENABLED and wa_ids:
        await wa_service.mark_messages_as_read(instance_name, remote_jid, wa_ids)

    # ── Partitioned, human-paced delivery ────────────────────────────────────
    parts = humanizer.split_reply(reply_text)
    for part in parts:
        if not part:
            continue
        if settings.TYPING_SIMULATION_ENABLED:
            delay = humanizer.typing_delay_seconds(part)
            await wa_service.send_presence(instance_name, phone, "composing", int(delay * 1000))
            await asyncio.sleep(delay)
        await wa_service.send_text_message(instance_name=instance_name, phone=phone, text=part)
        await _save_outbound(tenant.id, contact_id, part, model_used)

    logger.info(
        "webhook_processed",
        extra={**log_ctx, "phone": phone, "model": model_used, "parts": len(parts)},
    )


async def _save_outbound(
    tenant_id: uuid.UUID, contact_id: uuid.UUID, content: str, model_used: str
) -> None:
    """Persist one delivered outbound part. Failure here is logged, not raised,
    so a DB hiccup can't abort the remaining parts that already went out."""
    async with AsyncSessionLocal() as db:
        try:
            db.add(
                Message(
                    tenant_id=tenant_id,
                    contact_id=contact_id,
                    direction=MessageDirection.OUTBOUND,
                    channel=MessageChannel.WHATSAPP,
                    content=content,
                    ai_model_used=model_used,
                )
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("outbound_persist_failed", extra={"contact_id": str(contact_id)})


def _latest_media(messages: list[Message]) -> tuple[bytes, str] | None:
    """Reconstruct (bytes, mime) from the most recent media message in the burst,
    decoding the data URI saved in Phase 1. Returns None when there's no media."""
    for msg in reversed(messages):
        if msg.media_url and msg.media_mime_type:
            data = _decode_data_uri(msg.media_url)
            if data is not None:
                return data, msg.media_mime_type
    return None


def _decode_data_uri(media_url: str) -> bytes | None:
    if not media_url or not media_url.startswith("data:"):
        return None
    try:
        return base64.b64decode(media_url.split(",", 1)[1])
    except Exception:
        return None


async def _collect_unanswered(
    db: AsyncSession, tenant_id: uuid.UUID, contact_id: uuid.UUID
) -> list[Message]:
    """All inbound messages received after the last outbound (the burst to answer),
    oldest-first. If the AI never replied yet, returns every inbound message."""
    last_outbound_at = await db.scalar(
        select(Message.created_at)
        .where(
            Message.tenant_id == tenant_id,
            Message.contact_id == contact_id,
            Message.direction == MessageDirection.OUTBOUND,
        )
        .order_by(desc(Message.created_at))
        .limit(1)
    )

    stmt = select(Message).where(
        Message.tenant_id == tenant_id,
        Message.contact_id == contact_id,
        Message.direction == MessageDirection.INBOUND,
    )
    if last_outbound_at is not None:
        stmt = stmt.where(Message.created_at > last_outbound_at)
    stmt = stmt.order_by(Message.created_at)

    result = await db.execute(stmt)
    return list(result.scalars().all())


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
    exclude_ids: set[uuid.UUID],
) -> list[Message]:
    """Latest messages (excluding the current burst), oldest-first for the prompt."""
    stmt = select(Message).where(
        Message.tenant_id == tenant_id,
        Message.contact_id == contact_id,
    )
    if exclude_ids:
        stmt = stmt.where(Message.id.not_in(exclude_ids))
    stmt = stmt.order_by(desc(Message.created_at)).limit(settings.AI_HISTORY_LIMIT)

    result = await db.execute(stmt)
    return list(reversed(result.scalars().all()))
