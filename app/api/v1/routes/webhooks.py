"""
WhatsApp webhook receiver (UAZAPI).

Endpoint: POST /api/v1/webhooks/whatsapp/{tenant_slug}?token={webhook_secret}

This route is intentionally PUBLIC — UAZAPI posts from its own servers with no
X-Tenant-ID header. Tenant isolation is enforced by:
  1. Resolving the tenant from {tenant_slug} in the URL path.
  2. Validating the per-tenant webhook_secret (UAZAPI cannot send custom headers,
     so the secret rides in the `?token=` query param of the webhook URL).
  3. Scoping every DB write with the resolved tenant_id.

UAZAPI event shape: {"event": "messages"|"connection"|"presence", "instance": "...",
"data": {...}}. Message data is FLAT (no nested Baileys structure) and already
carries the resolved phone (`sender_pn`) alongside the LID (`sender_lid`).

The handler returns 200 immediately and processes the message in a
FastAPI BackgroundTask to avoid blocking UAZAPI's retry logic.
"""

import asyncio
import base64
import logging
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Request, status
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


def _instance_token(tenant: Tenant) -> str | None:
    return (tenant.settings or {}).get("whatsapp", {}).get("token")


@router.post("/whatsapp/{tenant_slug}", status_code=status.HTTP_200_OK)
async def whatsapp_webhook(
    tenant_slug: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Receive a UAZAPI webhook event. Validates the tenant + secret (query param),
    then routes by event type. Always returns 200 so UAZAPI does not keep retrying.
    """
    rid = getattr(request.state, "request_id", None)
    body = await request.json()
    provided_secret = request.query_params.get("token")

    # uazapiGO sends the event type in `EventType` (not `event`) and nests the
    # payload under a per-event key (`message`, `chat`, `instance`, ...) rather
    # than a generic `data`. Resolve both defensively across field-name variants.
    event = (
        body.get("EventType")
        or body.get("event")
        or body.get("type")
        or body.get("eventType")
        or ""
    ).lower()
    data = (
        body.get("data")
        or body.get("message")
        or body.get("chat")
        or body.get("presence")
        or body.get("instance")
        or {}
    )
    if not isinstance(data, dict):
        data = {}

    logger.info(
        "webhook_received",
        extra={
            "request_id": rid,
            "event": event or "(empty)",
            "tenant_slug": tenant_slug,
            "body_keys": list(body.keys()),
        },
    )

    async with AsyncSessionLocal() as db:
        tenant = await _resolve_tenant_or_none(db, tenant_slug)

    if tenant is None:
        logger.warning("webhook_unknown_tenant", extra={"request_id": rid, "tenant_slug": tenant_slug})
        return {"received": True}

    expected_secret = (tenant.settings or {}).get("whatsapp", {}).get("webhook_secret")
    if expected_secret and provided_secret != expected_secret:
        logger.warning(
            "webhook_invalid_secret",
            extra={"request_id": rid, "tenant_id": str(tenant.id), "event": event},
        )
        return {"received": True}

    # ── Connection state changes ─────────────────────────────────────────────
    if event == "connection":
        await _handle_connection_update(tenant, data, rid)
        return {"received": True}

    # ── Contact presence / typing ────────────────────────────────────────────
    # uazapiGO carries the presence payload at the top level (`type`/`event`),
    # not under a `data`/`presence` sub-key, so pass the whole body through.
    if event == "presence":
        _handle_presence_update(tenant, body, rid)
        return {"received": True}

    # ── Inbound messages ─────────────────────────────────────────────────────
    if event not in ("messages", "message"):
        logger.info(
            "webhook_event_ignored",
            extra={"request_id": rid, "event": event or "(empty)", "tenant_slug": tenant_slug,
                   "body_keys": list(body.keys())},
        )
        return {"received": True}

    # Ignore our own outbound / API-sent messages (avoid loops)
    if data.get("fromMe") or data.get("wasSentByApi"):
        return {"received": True}

    # Ignore groups when the tenant has ignore_groups enabled (default: True)
    chatid = str(data.get("chatid") or "")
    is_group = bool(data.get("isGroup")) or chatid.endswith("@g.us")
    ignore_groups = (tenant.settings or {}).get("ignore_groups", True)
    if ignore_groups and is_group:
        logger.info(
            "webhook_group_skipped",
            extra={"request_id": rid, "tenant_id": str(tenant.id), "chatid": chatid},
        )
        return {"received": True}

    logger.info(
        "webhook_dispatching_to_background",
        extra={"request_id": rid, "tenant_id": str(tenant.id), "tenant_slug": tenant_slug},
    )
    background_tasks.add_task(_process_inbound_message, tenant, data, rid)
    return {"received": True}


_MULTIMODAL_DISABLED_REPLY = {
    "audio": "Recebi seu áudio! No momento, só consigo responder mensagens de texto. Por favor, escreva sua mensagem. 😊",
    "image": "Recebi sua imagem! No momento, só consigo responder mensagens de texto. 😊",
    "video": "Recebi seu vídeo! No momento, só consigo responder mensagens de texto. 😊",
    "document": "Recebi seu documento! No momento, só consigo responder mensagens de texto. 😊",
}


def _phone_from_jid(jid: str) -> str:
    """Strip a WhatsApp JID down to its number part (drops @s.whatsapp.net/@c.us/@lid)."""
    if not jid:
        return ""
    return jid.split("@", 1)[0] if "@" in jid else jid


def _uazapi_media_kind(message_type: str) -> str | None:
    """Map a UAZAPI messageType to our media kind (image/audio/video/document),
    or None for text/other. Substring match tolerates variants (e.g. 'ptt',
    'ImageMessage')."""
    mt = (message_type or "").lower()
    if "sticker" in mt:
        return "image"
    if "image" in mt:
        return "image"
    if "video" in mt:
        return "video"
    if "audio" in mt or "ptt" in mt or "voice" in mt:
        return "audio"
    if "document" in mt:
        return "document"
    return None


def _typing_key(tenant_id: uuid.UUID, phone: str) -> str:
    """Stable key tying a contact's presence state to their pending batch."""
    return f"{tenant_id}:{phone}"


# UAZAPI delivers a contact's phone (`sender_pn`) and LID (`sender_lid`) on each
# message. We remember lid→phone so a presence event keyed by LID (if UAZAPI ever
# sends one) still resolves to the right contact. In-process only.
_lid_to_phone: dict[str, str] = {}

# contact_id -> created_at of the newest inbound message already handed to the AI.
# In-process (single-worker), same lifecycle as the batcher registry. Closes a race:
# a message that arrives WHILE Sofia is still "typing" the previous reply lands with
# a timestamp EARLIER than the outbound (which is saved only after the typing delay),
# so a naive "inbound newer than last outbound?" check would treat it as already
# answered and silently drop it. Tracking the high-water mark of what the AI actually
# read — not when the reply was sent — makes that late message correctly unanswered.
_answered_watermark: dict[uuid.UUID, datetime] = {}


# Presence states meaning "the contact is still composing a message". 'paused' is
# included on purpose (WhatsApp emits it when the user stops to think but hasn't
# sent yet) so we don't fire the reply mid-composition.
_TYPING_STATES = {"composing", "recording", "paused"}
# Only an explicit "gone offline" releases the hold; 'available' follows 'paused'
# and must NOT free it early.
_RELEASE_STATES = {"unavailable"}

# Every WhatsApp presence token we recognise. uazapiGO (whatsmeow under the hood)
# doesn't document which JSON key carries the state, so instead of guessing the
# field name we scan the event object's values for one of these tokens.
_PRESENCE_TOKENS = _TYPING_STATES | _RELEASE_STATES | {"available"}


def _scan_presence_state(obj: dict) -> str:
    """Return the first recognised presence token found among a dict's scalar
    values (one level deep), or "" if none. Field-name-agnostic on purpose."""
    if not isinstance(obj, dict):
        return ""
    for value in obj.values():
        if isinstance(value, str) and value.lower() in _PRESENCE_TOKENS:
            return value.lower()
        if isinstance(value, dict):
            nested = _scan_presence_state(value)
            if nested:
                return nested
    return ""


async def _handle_connection_update(tenant: Tenant, data: dict, rid: str | None) -> None:
    """Persist the WhatsApp connection status from a UAZAPI 'connection' event."""
    raw = data if isinstance(data, dict) else {}
    inst = raw.get("instance") if isinstance(raw.get("instance"), dict) else {}
    connected = raw.get("connected")
    if connected is None:
        connected = (raw.get("status") or {}).get("connected") if isinstance(raw.get("status"), dict) else None
    raw_status = (
        (raw.get("status") if isinstance(raw.get("status"), str) else None)
        or raw.get("state")
        or inst.get("status")
        or ("connected" if connected else "disconnected")
    )
    status_map = {"open": "connected", "close": "disconnected", "connecting": "connecting"}
    new_status = status_map.get(str(raw_status), str(raw_status) if raw_status else "disconnected")
    if new_status not in ("connected", "disconnected", "connecting"):
        new_status = "connected" if connected else "disconnected"

    async with AsyncSessionLocal() as db:
        tenant = await _resolve_tenant_or_none(db, tenant.slug)
        if tenant is None:
            return
        wa = dict((tenant.settings or {}).get("whatsapp", {}))
        if wa.get("status") != new_status:
            wa["status"] = new_status
            tenant.settings = {**(tenant.settings or {}), "whatsapp": wa}
            await db.commit()
    logger.info(
        "whatsapp_connection_update",
        extra={"request_id": rid, "tenant_id": str(tenant.id), "status": new_status},
    )


def _handle_presence_update(tenant: Tenant, data: dict, request_id: str | None) -> None:
    """
    Feed a UAZAPI 'presence' event into the batcher's typing registry.
    composing/recording/paused → hold the reply; unavailable → release; anything
    else → leave the current hold untouched. Pure in-memory, no I/O.

    UAZAPI's presence payload field names are not fully documented, so we parse
    defensively and log the raw keys at INFO for the first live events.
    """
    raw = data if isinstance(data, dict) else {}
    # uazapiGO nests the presence detail under `event` (an object) with the
    # contact in `chatid`/`id` and the state in `type`/`presence`. Fall back to
    # the top-level `type`/`event` scalars for other providers/shapes.
    ev = raw.get("event") if isinstance(raw.get("event"), dict) else {}
    ident = str(
        ev.get("chatid") or ev.get("id") or ev.get("sender")
        or raw.get("chatid") or raw.get("sender") or raw.get("id") or raw.get("number")
        or ""
    )
    # First try the known keys; if they only yield the event *category*
    # ("presence") or nothing, scan the event object's values for a real
    # presence token (composing/available/…) regardless of the key name.
    state = str(
        ev.get("state") or ev.get("presence") or ev.get("status")
        or ""
    ).lower()
    if state not in _PRESENCE_TOKENS:
        state = _scan_presence_state(ev) or _scan_presence_state(raw) or state

    if ident.endswith("@lid"):
        phone = _lid_to_phone.get(ident.split("@", 1)[0])
    else:
        phone = _phone_from_jid(ident)

    if not phone:
        # Log the raw VALUES (not just keys) so the uazapiGO presence shape can be
        # nailed down from a live event and the parsing tightened if needed.
        logger.info(
            "presence_update",
            extra={
                "request_id": request_id,
                "tenant_id": str(tenant.id),
                "state": state or "(empty)",
                "action": "unmapped",
                "raw_type": str(raw.get("type"))[:80],
                "raw_event": str(raw.get("event"))[:200],
            },
        )
        return

    key = _typing_key(tenant.id, phone)
    if state in _TYPING_STATES:
        batcher.mark_typing(key, settings.TYPING_HOLD_SECONDS)
        action = "hold"
    elif state in _RELEASE_STATES:
        batcher.clear_typing(key)
        action = "release"
    else:
        action = "ignore"

    logger.info(
        "presence_update",
        extra={
            "request_id": request_id,
            "tenant_id": str(tenant.id),
            "phone": phone,
            "state": state or "(empty)",
            "action": action,
            # Dump the full event object so the real presence-state field
            # (composing/available/…) can be verified from a live event.
            "event_obj": str(ev)[:300],
        },
    )


async def _process_inbound_message(tenant: Tenant, data: dict, request_id: str | None) -> None:
    """
    Two-phase pipeline:
      Phase 1 (own transaction): save inbound → committed immediately, visible in inbox.
      Phase 2 (own transaction): fetch history → AI reply → save outbound → commit → send.

    Splitting transactions ensures the inbound message appears in the inbox without
    waiting for the AI. Tool writes from the AI share Phase 2's transaction and are
    rolled back atomically with the outbound message on failure.

    Multimodal: when the message is audio/image/video/document AND the tenant has
    multimodal_enabled=true, the bytes are downloaded from UAZAPI, persisted as a
    data URI in media_url, and forwarded to Gemini as inline_data.
    """
    log_ctx = {"request_id": request_id, "tenant_id": str(tenant.id)}

    try:
        # ── Identify the contact (UAZAPI gives resolved phone + LID) ──────────
        sender_pn = str(data.get("sender_pn") or "")
        chatid = str(data.get("chatid") or "")
        sender = str(data.get("sender") or "")
        phone = _phone_from_jid(sender_pn or chatid or sender)
        push_name: str = data.get("senderName") or ""
        message_id: str = str(data.get("messageid") or data.get("id") or "")

        sender_lid = str(data.get("sender_lid") or "")
        if sender_lid and phone:
            _lid_to_phone[sender_lid.split("@", 1)[0]] = phone

        if not phone:
            logger.info("webhook_no_phone", extra={**log_ctx})
            return

        # UAZAPI messageTimestamp is in milliseconds.
        ts_raw = data.get("messageTimestamp") or 0
        ts_s = ts_raw / 1000 if ts_raw > 1_000_000_000_000 else ts_raw
        is_historical = ts_s > 0 and (time.time() - ts_s) > 300

        text = (data.get("text") or "").strip()
        media_kind = _uazapi_media_kind(data.get("messageType", ""))

        instance_token = _instance_token(tenant)
        ai_cfg = tenant.ai_config or {}
        # Multimodal is ON by default (absence of the key = enabled); a clinic can
        # still turn it off explicitly in Settings → AI.
        multimodal_enabled = bool(ai_cfg.get("multimodal_enabled", True))

        media_type: str | None = None
        media_mime_type: str | None = None
        media_size_bytes: int | None = None
        media_url: str | None = None

        # ── Pure text fast path ────────────────────────────────────────────
        if media_kind is None:
            if not text:
                logger.info("webhook_non_text_ignored", extra={**log_ctx, "phone": phone})
                return
            content = text

        # ── Media path ─────────────────────────────────────────────────────
        else:
            if not multimodal_enabled:
                if not is_historical and instance_token:
                    await wa_service.send_text_message(
                        instance_token=instance_token,
                        phone=phone,
                        text=_MULTIMODAL_DISABLED_REPLY.get(media_kind, _MULTIMODAL_DISABLED_REPLY["document"]),
                    )
                    logger.info(
                        "webhook_media_refused_disabled",
                        extra={**log_ctx, "phone": phone, "media_type": media_kind},
                    )
                else:
                    logger.info(
                        "webhook_media_ignored_historical",
                        extra={**log_ctx, "phone": phone, "media_type": media_kind},
                    )
                return

            if not instance_token:
                logger.error("webhook_no_instance_for_download", extra=log_ctx)
                return

            download = await wi.download_media_base64(instance_token, message_id)
            if download is None:
                logger.warning(
                    "webhook_media_download_giving_up",
                    extra={**log_ctx, "phone": phone, "media_type": media_kind},
                )
                return

            base64_data, mimetype, size_bytes = download

            _MAX_MEDIA_BYTES = 20 * 1024 * 1024
            if size_bytes > _MAX_MEDIA_BYTES:
                if not is_historical and instance_token:
                    kind_label = {"audio": "áudio", "image": "imagem", "video": "vídeo", "document": "documento"}.get(media_kind, media_kind)
                    await wa_service.send_text_message(
                        instance_token=instance_token,
                        phone=phone,
                        text=f"Recebi seu {kind_label}, mas ele é muito grande para processar (máximo 20 MB). Por favor, envie um arquivo menor. 😊",
                    )
                logger.info(
                    "webhook_media_too_large",
                    extra={**log_ctx, "phone": phone, "media_type": media_kind, "size_bytes": size_bytes},
                )
                return

            media_type = media_kind
            media_mime_type = mimetype
            media_size_bytes = size_bytes
            media_url = f"data:{mimetype};base64,{base64_data}"
            content = text  # caption (may be empty)

        # ── Phase 1: persist inbound immediately ─────────────────────────────
        async with AsyncSessionLocal() as db:
            try:
                # Idempotency: UAZAPI may re-deliver. Skip if already stored.
                if message_id:
                    dup = await db.scalar(
                        select(Message.id).where(
                            Message.tenant_id == tenant.id,
                            Message.whatsapp_message_id == message_id,
                        )
                    )
                    if dup is not None:
                        logger.info(
                            "webhook_duplicate_skipped",
                            extra={**log_ctx, "phone": phone, "whatsapp_message_id": message_id},
                        )
                        return

                contact = await _find_or_create_contact(db, tenant, phone, push_name)
                ai_paused = contact.ai_paused

                if not is_historical:
                    crm.mark_inbound(contact)

                inbound_msg = Message(
                    tenant_id=tenant.id,
                    contact_id=contact.id,
                    direction=MessageDirection.INBOUND,
                    channel=MessageChannel.WHATSAPP,
                    content=content,
                    whatsapp_message_id=message_id,
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
                extra={**log_ctx, "phone": phone, "age_s": int(time.time() - ts_s)},
            )
            return

        if ai_paused:
            logger.info("webhook_ai_paused", extra={**log_ctx, "phone": phone, "contact_id": str(contact_id)})
            return

        if not instance_token:
            logger.error("webhook_no_instance", extra=log_ctx)
            return

        # ── Phase 2 dispatch: debounce text bursts; flush media immediately ────
        has_media = media_type is not None

        async def _work() -> None:
            await _generate_and_send(
                tenant=tenant,
                contact_id=contact_id,
                phone=phone,
                instance_token=instance_token,
                request_id=request_id,
            )

        if has_media:
            await batcher.flush(contact_id, _work)
        else:
            batcher.schedule(contact_id, _work, typing_key=_typing_key(tenant.id, phone))

    except Exception:
        logger.exception("webhook_processing_error", extra=log_ctx)


async def _generate_and_send(
    tenant: Tenant,
    contact_id: uuid.UUID,
    phone: str,
    instance_token: str,
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

    async with AsyncSessionLocal() as db:
        try:
            contact = await db.scalar(select(Contact).where(Contact.id == contact_id))
            if contact is None:
                logger.warning("webhook_contact_missing", extra=log_ctx)
                return

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
            await db.commit()

            # Newest message this reply accounts for. We do NOT mark it answered
            # yet — only once we actually commit to sending (below), so a reply
            # that gets superseded never marks its burst answered.
            newest_answered = max(m.created_at for m in unanswered)
        except Exception:
            await db.rollback()
            raise

    # ── Read receipt before replying (best-effort) ───────────────────────────
    if settings.READ_RECEIPT_ENABLED and wa_ids:
        await wa_service.mark_messages_as_read(instance_token, wa_ids)

    # ── Partitioned, human-paced delivery ────────────────────────────────────
    # A human who is mid-reply when a new message lands folds it into one answer
    # instead of firing a second. We emulate that: right before the FIRST send
    # (after the typing delay — the widest window for a new message to arrive),
    # re-check for any inbound newer than this burst. If one exists, abort: the
    # new message already restarted the debounce, which will re-run over the whole
    # burst and produce a single combined reply. The "answered" watermark is set
    # only once we commit to sending, so an aborted reply never marks its burst
    # answered (it gets re-read and answered together with the new message).
    parts = humanizer.split_reply(reply_text)
    committed = False
    for part in parts:
        if not part:
            continue
        if settings.TYPING_SIMULATION_ENABLED:
            delay = humanizer.typing_delay_seconds(part)
            await wa_service.send_presence(instance_token, phone, "composing", int(delay * 1000))
            await asyncio.sleep(delay)
        if not committed:
            if await _has_newer_inbound(tenant.id, contact_id, newest_answered):
                logger.info("reply_superseded_by_new_message", extra=log_ctx)
                return
            prev = _answered_watermark.get(contact_id)
            if prev is None or newest_answered > prev:
                _answered_watermark[contact_id] = newest_answered
            committed = True
        await wa_service.send_text_message(instance_token=instance_token, phone=phone, text=part)
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


async def _has_newer_inbound(
    tenant_id: uuid.UUID, contact_id: uuid.UUID, since: datetime
) -> bool:
    """True if the contact sent any inbound message after `since` (the newest
    message the pending reply accounts for). Used to detect that the patient kept
    talking while Sofia was generating/typing, so the reply can be aborted and
    folded into a single combined answer."""
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(Message.id)
            .where(
                Message.tenant_id == tenant_id,
                Message.contact_id == contact_id,
                Message.direction == MessageDirection.INBOUND,
                Message.created_at > since,
            )
            .limit(1)
        )
        return row is not None


async def _collect_unanswered(
    db: AsyncSession, tenant_id: uuid.UUID, contact_id: uuid.UUID
) -> list[Message]:
    """Inbound messages the AI hasn't answered yet (the burst to reply to),
    oldest-first.

    Cutoff preference:
      1. The in-process watermark — created_at of the newest inbound already handed
         to the AI. This is authoritative and immune to the typing-delay race (a
         message arriving mid-reply is newer than the mark, so it stays unanswered).
      2. Fallback to the last outbound's timestamp when there's no watermark yet
         (e.g. right after a process restart), so we don't re-answer old bursts.
    """
    cutoff = _answered_watermark.get(contact_id)
    if cutoff is None:
        cutoff = await db.scalar(
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
    if cutoff is not None:
        stmt = stmt.where(Message.created_at > cutoff)
    stmt = stmt.order_by(Message.created_at)

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _resolve_tenant_or_none(db: AsyncSession, slug: str) -> Tenant | None:
    result = await db.execute(
        select(Tenant).where(Tenant.slug == slug, Tenant.is_active.is_(True))
    )
    return result.scalar_one_or_none()


async def _find_or_create_contact(
    db: AsyncSession, tenant: Tenant, phone: str, push_name: str
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
        display_name = push_name or phone

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

        instance_token = _instance_token(tenant)
        if instance_token:
            pic_url = await wi.fetch_profile_picture(instance_token, phone)
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
