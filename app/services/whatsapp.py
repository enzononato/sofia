"""
Evolution API client — outbound messages only.

The provider hosts a single Evolution API on their VPS. Credentials
(EVOLUTION_API_URL, EVOLUTION_API_KEY) are global server-side env vars —
never stored in or read from tenant settings.

Each tenant's instance name is stored in tenant.settings["whatsapp"]["instance"]
and is set automatically when the tenant connects via POST /tenants/me/whatsapp/connect.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _validate_provider() -> tuple[str, str]:
    """
    Returns (api_url, api_key) from global env vars.
    Raises RuntimeError if the provider hasn't configured Evolution API.
    """
    if not settings.EVOLUTION_API_URL or not settings.EVOLUTION_API_KEY:
        raise RuntimeError(
            "EVOLUTION_API_URL and EVOLUTION_API_KEY must be set in environment."
        )
    return settings.EVOLUTION_API_URL.rstrip("/"), settings.EVOLUTION_API_KEY


async def send_text_message(
    instance_name: str,
    phone: str,
    text: str,
) -> None:
    """
    Send a plain-text WhatsApp message via Evolution API.

    Args:
        instance_name: the Evolution instance name (e.g. "clinic-minha-clinica").
        phone: destination in E.164 without '+' (e.g. "5511999999999").
        text: message content.
    """
    api_url, api_key = _validate_provider()

    url = f"{api_url}/message/sendText/{instance_name}"
    payload = {"number": phone, "text": text}
    headers = {"apikey": api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            logger.info(
                "whatsapp_sent",
                extra={"phone": phone, "instance": instance_name, "status": response.status_code},
            )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "whatsapp_send_http_error",
                extra={
                    "phone": phone,
                    "instance": instance_name,
                    "status": exc.response.status_code,
                    "response_body": exc.response.text[:500],
                },
            )
            raise
        except httpx.RequestError as exc:
            logger.error(
                "whatsapp_send_network_error",
                extra={"phone": phone, "instance": instance_name, "error": str(exc)},
            )
            raise


async def send_presence(
    instance_name: str,
    phone: str,
    presence: str = "composing",
    delay_ms: int = 2000,
) -> None:
    """
    Send a presence update ("digitando..."/typing) via Evolution API.

    Best-effort: a failure here must NEVER block the actual reply, so all errors
    are swallowed (logged at debug/warning only).

    Args:
        instance_name: the Evolution instance name.
        phone: destination in E.164 without '+'.
        presence: "composing" (typing) | "recording" | "available" | "paused".
        delay_ms: how long Evolution should keep the presence active, in ms.
    """
    try:
        api_url, api_key = _validate_provider()
    except RuntimeError:
        return

    url = f"{api_url}/chat/sendPresence/{instance_name}"
    payload = {"number": phone, "delay": delay_ms, "presence": presence}
    headers = {"apikey": api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            logger.debug(
                "whatsapp_presence_sent",
                extra={"phone": phone, "instance": instance_name, "presence": presence},
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning(
                "whatsapp_presence_failed",
                extra={"phone": phone, "instance": instance_name, "error": str(exc)[:200]},
            )


async def mark_messages_as_read(
    instance_name: str,
    remote_jid: str,
    message_ids: list[str],
) -> None:
    """
    Mark inbound WhatsApp messages as read (blue ticks) via Evolution API.

    Best-effort: errors are swallowed so they can never block the reply flow.

    Args:
        instance_name: the Evolution instance name.
        remote_jid: the chat JID (e.g. "5511999999999@s.whatsapp.net").
        message_ids: Evolution message IDs (key.id from the inbound webhook).
    """
    ids = [mid for mid in message_ids if mid]
    if not ids:
        return

    try:
        api_url, api_key = _validate_provider()
    except RuntimeError:
        return

    url = f"{api_url}/chat/markMessageAsRead/{instance_name}"
    payload = {
        "readMessages": [
            {"remoteJid": remote_jid, "fromMe": False, "id": mid} for mid in ids
        ]
    }
    headers = {"apikey": api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            logger.debug(
                "whatsapp_marked_read",
                extra={"instance": instance_name, "count": len(ids)},
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning(
                "whatsapp_mark_read_failed",
                extra={"instance": instance_name, "error": str(exc)[:200]},
            )


async def send_media_message(
    instance_name: str,
    phone: str,
    media_type: str,
    media_url: str,
    caption: str = "",
    file_name: str = "",
) -> None:
    """
    Send a media WhatsApp message via Evolution API.

    Args:
        instance_name: the Evolution instance name.
        phone: destination in E.164 without '+'.
        media_type: 'audio', 'image', 'document'.
        media_url: base64 data URI or public URL of the media.
        caption: optional caption for images/documents.
        file_name: original file name for documents.
    """
    api_url, api_key = _validate_provider()

    # Evolution API expects raw base64 or a URL, not a data URI.
    # Strip the "data:...;base64," prefix if present.
    clean_media = media_url
    if clean_media.startswith("data:"):
        parts = clean_media.split(",", 1)
        if len(parts) == 2:
            clean_media = parts[1]

    # Audio uses a dedicated endpoint in Evolution API
    if media_type == "audio":
        url = f"{api_url}/message/sendWhatsAppAudio/{instance_name}"
        payload: dict = {
            "number": phone,
            "audio": clean_media,
        }
    else:
        url = f"{api_url}/message/sendMedia/{instance_name}"
        payload: dict = {
            "number": phone,
            "mediatype": media_type,
            "media": clean_media,
        }
        if caption:
            payload["caption"] = caption
        if file_name:
            payload["fileName"] = file_name

    headers = {"apikey": api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            logger.info(
                "whatsapp_media_sent",
                extra={"phone": phone, "instance": instance_name, "type": media_type},
            )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "whatsapp_media_send_http_error",
                extra={
                    "phone": phone,
                    "instance": instance_name,
                    "status": exc.response.status_code,
                    "response_body": exc.response.text[:500],
                },
            )
            raise
        except httpx.RequestError as exc:
            logger.error(
                "whatsapp_media_send_network_error",
                extra={"phone": phone, "instance": instance_name, "error": str(exc)},
            )
            raise
