"""
UAZAPI — instance lifecycle management.

The provider (SaaS owner) hosts a single UAZAPI server on their VPS. Each tenant
gets its own instance, created once via the admin token; the instance's own
`token` (returned on create) is then used to authenticate that clinic's calls.

UAZAPI identifies an instance by the `token` header (not by a name in the URL
path) — so callers pass the instance token, not a name. The token is a per-clinic
credential stored in tenant.settings["whatsapp"]["token"] and never exposed to clients.

Webhook auth: UAZAPI cannot send custom webhook headers, so the per-tenant secret
is embedded in the webhook URL as a `?token=` query param and validated on receipt.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Webhook events we subscribe to (UAZAPI enum): inbound messages, connection
# state changes, and the contact's typing/presence (drives the reply hold).
_WEBHOOK_EVENTS = ["messages", "connection", "presence"]


def _base_url() -> str:
    if not settings.UAZAPI_URL:
        raise RuntimeError("UAZAPI_URL is not configured.")
    return settings.UAZAPI_URL.rstrip("/")


def _admin_headers() -> dict:
    if not settings.UAZAPI_ADMIN_TOKEN:
        raise RuntimeError("UAZAPI_ADMIN_TOKEN is not configured.")
    return {"admintoken": settings.UAZAPI_ADMIN_TOKEN, "Content-Type": "application/json"}


def _token_headers(instance_token: str) -> dict:
    return {"token": instance_token, "Content-Type": "application/json"}


def webhook_url(tenant_slug: str, webhook_secret: str) -> str:
    """Public webhook URL for a tenant, with the shared secret as a query param
    (UAZAPI can't send custom headers, so the secret rides in the URL)."""
    return (
        f"{settings.APP_BASE_URL}/api/v1/webhooks/whatsapp/{tenant_slug}"
        f"?token={webhook_secret}"
    )


async def create_instance(name: str) -> dict:
    """
    Create a new UAZAPI instance (admin op). Returns the full JSON, which includes
    the per-instance `token` and an `instance` object (id, status, qrcode, ...).
    UAZAPI mints a NEW token on each call, so callers must persist it and reuse it
    on reconnect rather than creating again.
    """
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{_base_url()}/instance/create",
            headers=_admin_headers(),
            json={"name": name},
        )
        if resp.status_code not in (200, 201):
            logger.error(
                "uazapi_create_instance_error",
                extra={"instance_name": name, "status": resp.status_code, "body": resp.text[:500]},
            )
            resp.raise_for_status()
        data = resp.json()
    logger.info("uazapi_instance_created", extra={"instance_name": name})
    return data


async def set_webhook(instance_token: str, tenant_slug: str, webhook_secret: str) -> None:
    """
    Configure (upsert) the webhook for an instance. Safe to call repeatedly.
    """
    url = webhook_url(tenant_slug, webhook_secret)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_base_url()}/webhook",
            headers=_token_headers(instance_token),
            json={"enabled": True, "url": url, "events": _WEBHOOK_EVENTS},
        )
        if resp.status_code not in (200, 201):
            logger.error(
                "uazapi_set_webhook_error",
                extra={"tenant_slug": tenant_slug, "status": resp.status_code, "body": resp.text[:500]},
            )
            resp.raise_for_status()
    logger.info("uazapi_webhook_set", extra={"tenant_slug": tenant_slug, "url": url})


async def connect_instance(instance_token: str, phone: str | None = None) -> dict:
    """
    Start the WhatsApp connection for an instance and return the UAZAPI response,
    which contains the `instance` object with `qrcode` (base64) / `paircode`.
    """
    payload: dict = {}
    if phone:
        payload["phone"] = phone
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{_base_url()}/instance/connect",
            headers=_token_headers(instance_token),
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def get_status(instance_token: str) -> dict:
    """
    Return the UAZAPI status payload: {"status": {"connected", "loggedIn", ...},
    "instance": {...}}. Raises on transport/HTTP errors.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{_base_url()}/instance/status",
            headers=_token_headers(instance_token),
        )
        resp.raise_for_status()
        return resp.json()


async def delete_instance(instance_token: str) -> None:
    """Delete an instance. Silently ignores 404 (already gone)."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.delete(
            f"{_base_url()}/instance",
            headers=_token_headers(instance_token),
        )
        if resp.status_code == 404:
            return
        resp.raise_for_status()
    logger.info("uazapi_instance_deleted")


async def download_media_base64(
    instance_token: str, message_id: str
) -> tuple[str, str, int] | None:
    """
    Download media bytes for a received message via UAZAPI
    (POST /message/download, body {"id": <messageid>, "return_base64": true}).
    Response: {"base64Data": "...", "mimetype": "audio/ogg", "fileURL": "..."}.

    Returns (base64_data, mimetype, size_bytes) on success, or None on failure.
    """
    if not message_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_base_url()}/message/download",
                headers=_token_headers(instance_token),
                json={"id": message_id, "return_base64": True},
            )
            if resp.status_code != 200:
                logger.warning(
                    "uazapi_media_download_failed",
                    extra={"status": resp.status_code, "body": resp.text[:500]},
                )
                return None
            payload = resp.json()
            base64_data = payload.get("base64Data") or payload.get("base64")
            mimetype = payload.get("mimetype") or "application/octet-stream"
            if not base64_data:
                logger.warning(
                    "uazapi_media_download_empty",
                    extra={"payload_keys": list(payload.keys())},
                )
                return None
            size_bytes = (len(base64_data) * 3) // 4
            return base64_data, mimetype, size_bytes
    except (httpx.ConnectError, httpx.TimeoutException, RuntimeError) as exc:
        logger.warning("uazapi_media_download_unreachable", extra={"error": str(exc)})
        return None


async def fetch_profile_picture(instance_token: str, phone: str) -> str | None:
    """
    Fetch a contact's profile picture URL via UAZAPI (POST /chat/details).
    Best-effort: returns None if unavailable or the shape is unexpected.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(
                f"{_base_url()}/chat/details",
                headers=_token_headers(instance_token),
                json={"number": phone, "preview": True},
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                return (
                    data.get("imgUrl")
                    or data.get("image")
                    or data.get("profilePicUrl")
                    or data.get("profilePicture")
                )
            return None
        except Exception as exc:
            logger.warning(
                "uazapi_fetch_profile_picture_failed",
                extra={"phone": phone, "error": str(exc)[:200]},
            )
            return None
