"""
UAZAPI client — outbound messages only.

The provider hosts a single UAZAPI server. The server base URL is a global env
var (UAZAPI_URL). Each clinic has its own UAZAPI instance whose per-instance
token authenticates that clinic's sends. The token is stored server-side in
tenant.settings["whatsapp"]["token"] and passed in here — never exposed to clients.

Auth: every request carries the header `token: <instance_token>`.
Phone numbers are E.164 without '+' (e.g. "5511999999999").
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _base_url() -> str:
    if not settings.UAZAPI_URL:
        raise RuntimeError("UAZAPI_URL is not configured.")
    return settings.UAZAPI_URL.rstrip("/")


def _headers(instance_token: str) -> dict:
    return {"token": instance_token, "Content-Type": "application/json"}


async def send_text_message(instance_token: str, phone: str, text: str) -> None:
    """
    Send a plain-text WhatsApp message via UAZAPI (POST /send/text).

    Args:
        instance_token: the clinic's UAZAPI instance token.
        phone: destination in E.164 without '+' (e.g. "5511999999999").
        text: message content.
    """
    url = f"{_base_url()}/send/text"
    payload = {"number": phone, "text": text}

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            response = await client.post(url, json=payload, headers=_headers(instance_token))
            response.raise_for_status()
            logger.info(
                "whatsapp_sent",
                extra={"phone": phone, "status": response.status_code},
            )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "whatsapp_send_http_error",
                extra={
                    "phone": phone,
                    "status": exc.response.status_code,
                    "response_body": exc.response.text[:500],
                },
            )
            raise
        except httpx.RequestError as exc:
            logger.error(
                "whatsapp_send_network_error",
                extra={"phone": phone, "error": str(exc)},
            )
            raise


async def send_presence(
    instance_token: str,
    phone: str,
    presence: str = "composing",
    delay_ms: int = 2000,
) -> None:
    """
    Send a presence update ("digitando..."/typing) via UAZAPI (POST /message/presence).

    Best-effort: a failure here must NEVER block the actual reply, so all errors
    are swallowed (logged at warning only).

    Args:
        presence: "composing" (typing) | "recording" | "available" | "paused".
        delay_ms: how long UAZAPI should keep the presence active, in ms.
    """
    try:
        url = f"{_base_url()}/message/presence"
    except RuntimeError:
        return

    payload = {"number": phone, "presence": presence, "delay": delay_ms}

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.post(url, json=payload, headers=_headers(instance_token))
            response.raise_for_status()
            logger.debug("whatsapp_presence_sent", extra={"phone": phone, "presence": presence})
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning(
                "whatsapp_presence_failed",
                extra={"phone": phone, "error": str(exc)[:200]},
            )


async def mark_messages_as_read(instance_token: str, message_ids: list[str]) -> None:
    """
    Mark inbound WhatsApp messages as read (blue ticks) via UAZAPI
    (POST /message/markread, body {"id": [...]}). UAZAPI keys by provider message
    id (the `messageid` from the inbound webhook), so no chat JID is needed.

    Best-effort: errors are swallowed so they can never block the reply flow.
    """
    ids = [mid for mid in message_ids if mid]
    if not ids:
        return

    try:
        url = f"{_base_url()}/message/markread"
    except RuntimeError:
        return

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.post(url, json={"id": ids}, headers=_headers(instance_token))
            response.raise_for_status()
            logger.debug("whatsapp_marked_read", extra={"count": len(ids)})
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning("whatsapp_mark_read_failed", extra={"error": str(exc)[:200]})


async def send_media_message(
    instance_token: str,
    phone: str,
    media_type: str,
    media: str,
    caption: str = "",
    file_name: str = "",
    mime_type: str = "",
) -> None:
    """
    Send a media WhatsApp message via UAZAPI (POST /send/media).

    Args:
        media_type: 'image' | 'audio' | 'video' | 'document' (UAZAPI `type`).
        media: base64 payload (data URI prefix is stripped) or a public URL.
        caption: optional caption (UAZAPI `text`).
        file_name: original file name for documents (UAZAPI `docName`).
        mime_type: optional explicit MIME type (UAZAPI `mimetype`).
    """
    url = f"{_base_url()}/send/media"

    # UAZAPI's `file` accepts a URL or raw base64. Strip the "data:...;base64,"
    # prefix if present and forward the MIME type separately.
    clean_media = media
    if clean_media.startswith("data:"):
        head, _, tail = clean_media.partition(",")
        if tail:
            clean_media = tail
            if not mime_type and head.startswith("data:"):
                mime_type = head[len("data:"):].split(";", 1)[0]

    payload: dict = {"number": phone, "type": media_type, "file": clean_media}
    if caption:
        payload["text"] = caption
    if file_name:
        payload["docName"] = file_name
    if mime_type:
        payload["mimetype"] = mime_type

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.post(url, json=payload, headers=_headers(instance_token))
            response.raise_for_status()
            logger.info("whatsapp_media_sent", extra={"phone": phone, "type": media_type})
        except httpx.HTTPStatusError as exc:
            logger.error(
                "whatsapp_media_send_http_error",
                extra={
                    "phone": phone,
                    "status": exc.response.status_code,
                    "response_body": exc.response.text[:500],
                },
            )
            raise
        except httpx.RequestError as exc:
            logger.error(
                "whatsapp_media_send_network_error",
                extra={"phone": phone, "error": str(exc)},
            )
            raise
