"""
WhatsApp connection management for clinic owners.

POST   /tenants/me/whatsapp/connect     — create/reuse UAZAPI instance + return QR code
GET    /tenants/me/whatsapp/status      — poll connection state
DELETE /tenants/me/whatsapp/disconnect  — delete instance and clear status

Credentials (server URL, admin token) are global server-side env vars. Each clinic
has its own UAZAPI instance whose per-instance token is stored server-side; the
tenant only ever sees a QR code and a connection status.
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

_NOT_CONFIGURED = (
    "UAZAPI não está configurada no servidor. "
    "Defina UAZAPI_URL e UAZAPI_ADMIN_TOKEN no arquivo .env."
)


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
    Provision (or reuse) the UAZAPI instance for this clinic and return a QR code
    for the owner to scan. The instance token is created once and reused on
    subsequent reconnects (UAZAPI mints a new token on every create).
    """
    if current_user.role not in _OWNER_ADMIN:
        raise ForbiddenError("Only OWNER or ADMIN can connect WhatsApp.")

    tenant = await _get_tenant(db, tenant_id)

    wa_settings = dict((tenant.settings or {}).get("whatsapp", {}))
    webhook_secret = wa_settings.get("webhook_secret") or secrets.token_urlsafe(32)
    instance_token = wa_settings.get("token")
    instance_id = wa_settings.get("instance")

    # Step 1 — create the instance ONCE, and persist its token IMMEDIATELY. This is
    # the only mutating/irreversible step, so we commit before the flakier connect
    # step: otherwise any later error would drop the token and every retry (or a
    # double-click) would mint a brand-new orphan instance on UAZAPI.
    if not instance_token:
        try:
            created = await wi.create_instance(f"clinic-{tenant.slug}")
        except RuntimeError:
            raise UnprocessableEntityError(_NOT_CONFIGURED)
        except (httpx.ConnectError, httpx.TimeoutException):
            raise UnprocessableEntityError(
                "Não foi possível conectar à UAZAPI. Verifique a URL e se o servidor está acessível."
            )
        except httpx.HTTPStatusError as exc:
            raise UnprocessableEntityError(
                f"UAZAPI retornou erro {exc.response.status_code} ao criar a instância."
            )

        instance_token = created.get("token") or (created.get("instance") or {}).get("token")
        instance_id = (created.get("instance") or {}).get("id") or created.get("id")
        if not instance_token:
            raise UnprocessableEntityError("UAZAPI não retornou um token de instância.")

        wa_settings = {
            **wa_settings,
            "instance": instance_id,
            "token": instance_token,
            "status": "connecting",
            "webhook_secret": webhook_secret,
        }
        tenant.settings = {**(tenant.settings or {}), "whatsapp": wa_settings}
        await db.commit()

    # Step 2 — configure the webhook + start the connection. Safe to retry: it
    # reuses the stored token, so a transient failure never leaks a new instance.
    try:
        await wi.set_webhook(instance_token, tenant.slug, webhook_secret)
        conn = await wi.connect_instance(instance_token)
    except RuntimeError:
        raise UnprocessableEntityError(_NOT_CONFIGURED)
    except (httpx.ConnectError, httpx.TimeoutException):
        raise UnprocessableEntityError(
            "A UAZAPI não respondeu a tempo. Tente gerar o QR novamente em alguns segundos."
        )
    except httpx.HTTPStatusError as exc:
        raise UnprocessableEntityError(
            f"UAZAPI retornou erro {exc.response.status_code} ao gerar o QR. Tente novamente."
        )

    inst = conn.get("instance") or {}
    if not instance_id:
        instance_id = inst.get("id")
    qr_code = inst.get("qrcode") or ""
    pair_code = inst.get("paircode") or ""
    status = "connected" if (conn.get("connected") or conn.get("loggedIn")) else "connecting"

    tenant.settings = {
        **(tenant.settings or {}),
        "whatsapp": {
            **wa_settings,
            "instance": instance_id,
            "token": instance_token,
            "status": status,
            "webhook_secret": webhook_secret,
        },
    }
    await db.commit()

    return {
        "instance": instance_id,
        "status": status,
        "qr_code": {"code": qr_code, "pair_code": pair_code, "type": "qrcode"},
    }


@router.get("/status")
async def whatsapp_status(
    db: DBSession,
    tenant_id: CurrentTenantId,
    _: CurrentUser,
):
    """
    Return the current WhatsApp connection status, refreshing it from the live
    UAZAPI instance state.
    """
    tenant = await _get_tenant(db, tenant_id)

    wa_settings = (tenant.settings or {}).get("whatsapp", {})
    instance_token = wa_settings.get("token")
    instance_id = wa_settings.get("instance")

    if not instance_token:
        return {"status": "not_configured", "instance": None}

    try:
        payload = await wi.get_status(instance_token)
    except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException, RuntimeError):
        # Can't reach UAZAPI — return last known status from DB
        return {"status": wa_settings.get("status", "unknown"), "instance": instance_id}

    st = payload.get("status") or {}
    if st.get("connected") or st.get("loggedIn"):
        status = "connected"
    else:
        status = "disconnected"

    if wa_settings.get("status") != status:
        tenant.settings = {
            **(tenant.settings or {}),
            "whatsapp": {**wa_settings, "status": status},
        }
        await db.commit()

    return {"status": status, "instance": instance_id}


@router.delete("/disconnect", status_code=204)
async def disconnect_whatsapp(
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    """
    Delete the UAZAPI instance and mark this clinic as disconnected.
    Requires OWNER or ADMIN role.
    """
    if current_user.role not in _OWNER_ADMIN:
        raise ForbiddenError("Only OWNER or ADMIN can disconnect WhatsApp.")

    tenant = await _get_tenant(db, tenant_id)

    wa_settings = (tenant.settings or {}).get("whatsapp", {})
    instance_token = wa_settings.get("token")

    if instance_token:
        try:
            await wi.delete_instance(instance_token)
        except (httpx.ConnectError, httpx.TimeoutException, RuntimeError, httpx.HTTPStatusError):
            # UAZAPI unreachable or errored — still clear local state
            pass

    tenant.settings = {
        **(tenant.settings or {}),
        "whatsapp": {"instance": None, "token": None, "status": "disconnected"},
    }
    await db.commit()
