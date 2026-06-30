"""
Evolution API — instance lifecycle management.

The provider (SaaS owner) hosts a single Evolution API on their VPS.
Each tenant gets a named instance auto-derived from their slug.
Credentials (api_url, api_key) are global env vars — never exposed to tenants.

Instance naming: "clinic-{tenant_slug}" (deterministic, prevents collisions).
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _headers() -> dict:
    return {"apikey": settings.EVOLUTION_API_KEY or "", "Content-Type": "application/json"}


def _base_url() -> str:
    if not settings.EVOLUTION_API_URL:
        raise RuntimeError("EVOLUTION_API_URL is not configured.")
    if not settings.EVOLUTION_API_KEY:
        raise RuntimeError("EVOLUTION_API_KEY is not configured.")
    return settings.EVOLUTION_API_URL.rstrip("/")


async def create_or_fetch_instance(tenant_slug: str, webhook_secret: str) -> str:
    """
    Create an Evolution instance for a tenant (idempotent — 409 means already exists).
    Always re-applies the webhook config afterwards so that pre-existing instances
    pick up the latest URL / events / secret if the code has evolved.
    Returns the instance name.
    """
    instance_name = f"clinic-{tenant_slug}"
    webhook_url = f"{settings.APP_BASE_URL}/api/v1/webhooks/whatsapp/{tenant_slug}"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_base_url()}/instance/create",
            headers=_headers(),
            json={
                "instanceName": instance_name,
                "qrcode": True,
                "integration": "WHATSAPP-BAILEYS",
                "webhook": {
                    "enabled": True,
                    "url": webhook_url,
                    "headers": {"X-Webhook-Secret": webhook_secret},
                    "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE", "PRESENCE_UPDATE"],
                },
            },
        )
        already_exists = resp.status_code == 409 or (
            resp.status_code == 403 and "already in use" in resp.text.lower()
        )
        if resp.status_code not in (200, 201) and not already_exists:
            logger.error(
                "evolution_create_instance_error",
                extra={
                    "instance": instance_name,
                    "status": resp.status_code,
                    "body": resp.text[:500],
                },
            )
            resp.raise_for_status()

    # Always re-apply webhook config — covers existing instances that may have
    # been provisioned with stale URL/events/secret in previous code versions.
    await set_webhook(instance_name, webhook_secret, tenant_slug)

    logger.info(
        "evolution_instance_ready",
        extra={"instance": instance_name, "tenant_slug": tenant_slug},
    )
    return instance_name


async def set_webhook(instance_name: str, webhook_secret: str, tenant_slug: str) -> None:
    """
    Idempotently configure (or re-configure) the webhook for an Evolution instance.
    Safe to call repeatedly — Evolution treats this as upsert.
    """
    webhook_url = f"{settings.APP_BASE_URL}/api/v1/webhooks/whatsapp/{tenant_slug}"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_base_url()}/webhook/set/{instance_name}",
            headers=_headers(),
            json={
                "webhook": {
                    "enabled": True,
                    "url": webhook_url,
                    "headers": {"X-Webhook-Secret": webhook_secret},
                    "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE", "PRESENCE_UPDATE"],
                }
            },
        )
        if resp.status_code not in (200, 201):
            logger.error(
                "evolution_set_webhook_error",
                extra={
                    "instance": instance_name,
                    "status": resp.status_code,
                    "body": resp.text[:500],
                },
            )
            resp.raise_for_status()

    logger.info(
        "evolution_webhook_set",
        extra={"instance": instance_name, "url": webhook_url},
    )


async def get_qr_code(instance_name: str) -> dict:
    """
    Return the current QR code data from Evolution API.
    Shape: {"code": "base64...", "type": "qrcode"}
    Raises httpx.HTTPStatusError if already connected (Evolution returns 4xx).
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{_base_url()}/instance/connect/{instance_name}",
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def get_connection_state(instance_name: str) -> str:
    """
    Return the raw Evolution connection state: 'open' | 'close' | 'connecting'.
    Falls back to 'close' on any unexpected response shape.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{_base_url()}/instance/connectionState/{instance_name}",
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json().get("instance", {}).get("state", "close")


async def delete_instance(instance_name: str) -> None:
    """
    Delete an Evolution instance. Silently ignores 404 (already gone).
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.delete(
            f"{_base_url()}/instance/delete/{instance_name}",
            headers=_headers(),
        )
        if resp.status_code == 404:
            return
        resp.raise_for_status()

    logger.info("evolution_instance_deleted", extra={"instance": instance_name})


async def download_media_base64(
    instance_name: str, webhook_data: dict
) -> tuple[str, str, int] | None:
    """
    Download media bytes (audio, image, video, document) from a WhatsApp message.

    Evolution API endpoint: POST /chat/getBase64FromMediaMessage/{instance}
    Body: {"message": <full data["message"] from webhook>}
    Response: {"base64": "...", "mimetype": "audio/ogg", "fileName": "..." | null}

    Args:
        instance_name: Evolution instance for this tenant (e.g. "clinic-foo").
        webhook_data:  The `data` dict from the webhook payload — must contain `key`
                       and `message`. We send the whole shape so Evolution can locate
                       the media regardless of the underlying mediaKey/url variant.

    Returns:
        (base64_data, mimetype, size_bytes) on success, or None if Evolution failed
        or returned an unexpected shape. Always logs the cause on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_base_url()}/chat/getBase64FromMediaMessage/{instance_name}",
                headers=_headers(),
                json={"message": webhook_data, "convertToMp4": False},
            )
            if resp.status_code != 200:
                logger.warning(
                    "evolution_media_download_failed",
                    extra={
                        "instance": instance_name,
                        "status": resp.status_code,
                        "body": resp.text[:500],
                    },
                )
                return None

            payload = resp.json()
            base64_data = payload.get("base64")
            mimetype = payload.get("mimetype") or "application/octet-stream"
            if not base64_data:
                logger.warning(
                    "evolution_media_download_empty",
                    extra={"instance": instance_name, "payload_keys": list(payload.keys())},
                )
                return None

            # base64 size = ~4/3 of binary; we report binary bytes
            size_bytes = (len(base64_data) * 3) // 4
            return base64_data, mimetype, size_bytes
    except (httpx.ConnectError, httpx.TimeoutException, RuntimeError) as exc:
        logger.warning(
            "evolution_media_download_unreachable",
            extra={"instance": instance_name, "error": str(exc)},
        )
        return None


async def fetch_profile_picture(instance_name: str, phone: str) -> str | None:
    """
    Fetch the profile picture URL of a WhatsApp contact.
    Silently fails and returns None if the user has no picture or Evolution API is unreachable.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(
                f"{_base_url()}/chat/fetchProfilePictureUrl/{instance_name}",
                headers=_headers(),
                json={"number": phone},
            )
            resp.raise_for_status()
            return resp.json().get("profilePictureUrl")
        except Exception as exc:
            logger.warning(
                "evolution_fetch_profile_picture_failed",
                extra={"instance": instance_name, "phone": phone, "error": str(exc)},
            )
            return None
