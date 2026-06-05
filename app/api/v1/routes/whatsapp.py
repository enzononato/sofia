"""
WhatsApp connection management for clinic owners.

POST   /tenants/me/whatsapp/connect     — create Evolution instance + return QR code
GET    /tenants/me/whatsapp/status      — poll connection state
DELETE /tenants/me/whatsapp/disconnect  — delete instance and clear status

Credentials (api_url, api_key) are global server-side env vars.
The tenant only ever sees a QR code and a connection status.
"""

import secrets

import httpx
from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentTenantId, CurrentUser, DBSession
from app.core.errors import ForbiddenError, NotFoundError, UnprocessableEntityError
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import whatsapp_instance as wi

router = APIRouter(prefix="/tenants/me/whatsapp", tags=["WhatsApp"])

_OWNER_ADMIN = (UserRole.OWNER, UserRole.ADMIN)


async def _get_tenant(db: DBSession, tenant_id) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise NotFoundError("Tenant not found.")
    return tenant


@router.post("/connect", status_code=200)
async def connect_whatsapp(
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    """
    Provision (or re-provision) the Evolution instance for this clinic and
    return a QR code for the owner to scan with WhatsApp Business.

    If the instance already exists in Evolution, the QR code refreshes.
    If the phone is already connected, Evolution returns an error — this
    endpoint surfaces it as a 422 with a friendly message.
    """
    if current_user.role not in _OWNER_ADMIN:
        raise ForbiddenError("Only OWNER or ADMIN can connect WhatsApp.")

    tenant = await _get_tenant(db, tenant_id)

    wa_settings = (tenant.settings or {}).get("whatsapp", {})
    webhook_secret = wa_settings.get("webhook_secret") or secrets.token_urlsafe(32)

    try:
        instance_name = await wi.create_or_fetch_instance(tenant.slug, webhook_secret)
    except RuntimeError as exc:
        raise UnprocessableEntityError(
            "Evolution API não está configurada no servidor. "
            "Defina EVOLUTION_API_URL e EVOLUTION_API_KEY no arquivo .env."
        )
    except httpx.ConnectError:
        raise UnprocessableEntityError(
            "Não foi possível conectar à Evolution API. "
            "Verifique se a URL está correta e se o servidor está acessível."
        )
    except httpx.TimeoutException:
        raise UnprocessableEntityError(
            "A Evolution API não respondeu a tempo. Tente novamente em alguns segundos."
        )
    except httpx.HTTPStatusError as exc:
        raise UnprocessableEntityError(
            f"Evolution API retornou erro {exc.response.status_code} ao criar instância. "
            "Verifique as credenciais no .env."
        )

    try:
        qr_data = await wi.get_qr_code(instance_name)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 409):
            raise UnprocessableEntityError(
                "WhatsApp is already connected. Disconnect first to get a new QR code."
            )
        raise
    except httpx.ConnectError:
        raise UnprocessableEntityError(
            "Não foi possível conectar à Evolution API para gerar o QR Code."
        )

    tenant.settings = {
        **(tenant.settings or {}),
        "whatsapp": {
            **wa_settings,
            "instance": instance_name,
            "status": "connecting",
            "webhook_secret": webhook_secret,
        },
    }
    await db.commit()

    return {"instance": instance_name, "qr_code": qr_data}


@router.get("/status")
async def whatsapp_status(
    db: DBSession,
    tenant_id: CurrentTenantId,
    _: CurrentUser,
):
    """
    Return the current WhatsApp connection status for this clinic.
    Also refreshes the stored status from the live Evolution API state.
    """
    tenant = await _get_tenant(db, tenant_id)

    wa_settings = (tenant.settings or {}).get("whatsapp", {})
    instance_name = wa_settings.get("instance")

    if not instance_name:
        return {"status": "not_configured", "instance": None}

    try:
        raw_state = await wi.get_connection_state(instance_name)
    except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException):
        # Can't reach Evolution — return last known status from DB
        return {"status": wa_settings.get("status", "unknown"), "instance": instance_name}

    state_map = {"open": "connected", "close": "disconnected", "connecting": "connecting"}
    status = state_map.get(raw_state, "disconnected")

    if wa_settings.get("status") != status:
        tenant.settings = {
            **(tenant.settings or {}),
            "whatsapp": {**wa_settings, "status": status},
        }
        await db.commit()

    return {"status": status, "instance": instance_name}


@router.delete("/disconnect", status_code=204)
async def disconnect_whatsapp(
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    """
    Delete the Evolution instance and mark this clinic as disconnected.
    Requires OWNER or ADMIN role.
    """
    if current_user.role not in _OWNER_ADMIN:
        raise ForbiddenError("Only OWNER or ADMIN can disconnect WhatsApp.")

    tenant = await _get_tenant(db, tenant_id)

    wa_settings = (tenant.settings or {}).get("whatsapp", {})
    instance_name = wa_settings.get("instance")

    if instance_name:
        try:
            await wi.delete_instance(instance_name)
        except (httpx.ConnectError, httpx.TimeoutException, RuntimeError, httpx.HTTPStatusError):
            # Evolution API is unreachable or returned an error — still clear local state
            pass

    tenant.settings = {
        **(tenant.settings or {}),
        "whatsapp": {"instance": None, "status": "disconnected"},
    }
    await db.commit()
