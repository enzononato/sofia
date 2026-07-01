"""
WhatsApp connection management for clinic owners.

POST   /tenants/me/whatsapp/connect     — create/reuse UAZAPI instance + return QR code
GET    /tenants/me/whatsapp/status      — poll connection state
DELETE /tenants/me/whatsapp/disconnect  — delete instance and clear status

Credentials (server URL, admin token) are global server-side env vars. Each clinic
has its own UAZAPI instance whose per-instance token is stored server-side; the
tenant only ever sees a QR code and a connection status.
"""

import logging
import secrets

import httpx
from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import attributes as sa_attributes

from app.api.deps import CurrentTenantId, CurrentUser, DBSession
from app.core.errors import ForbiddenError, NotFoundError, UnprocessableEntityError
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import whatsapp_instance as wi

logger = logging.getLogger(__name__)

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


def _persist_wa_settings(tenant: Tenant, wa_settings: dict) -> None:
    """Overwrite the whatsapp sub-key in tenant.settings and mark JSONB as dirty."""
    tenant.settings = {**(tenant.settings or {}), "whatsapp": wa_settings}
    sa_attributes.flag_modified(tenant, "settings")


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

    # SELECT FOR UPDATE serialises concurrent connect requests (double-click race):
    # the second request blocks here until the first commits, then reads the already-
    # saved token and skips the create entirely.
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id).with_for_update()
    )
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise NotFoundError("Tenant not found.")

    wa_settings = dict((tenant.settings or {}).get("whatsapp", {}))
    webhook_secret = wa_settings.get("webhook_secret") or secrets.token_urlsafe(32)
    instance_token = wa_settings.get("token")
    instance_id = wa_settings.get("instance")

    # ── Step 1 ── create the instance ONCE and persist its token IMMEDIATELY.
    # This is the only irreversible step; we commit before the flakier connect
    # call so that any later failure never causes a second orphan instance.
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
        except Exception as exc:
            logger.error("uazapi_create_unexpected_error", extra={"error": str(exc)})
            raise UnprocessableEntityError(f"Erro inesperado ao criar instância: {exc}")

        logger.info(
            "uazapi_create_response",
            extra={"keys": list(created.keys()) if isinstance(created, dict) else type(created).__name__,
                   "raw": str(created)[:500]},
        )

        try:
            instance_token = (
                created.get("token") or (created.get("instance") or {}).get("token")
            )
            instance_id = (created.get("instance") or {}).get("id") or created.get("id")
        except (AttributeError, TypeError) as exc:
            logger.error(
                "uazapi_create_parse_error",
                extra={"response": str(created)[:500], "error": str(exc)},
            )
            raise UnprocessableEntityError(
                f"UAZAPI retornou formato inesperado. Resposta: {str(created)[:200]}"
            )

        if not instance_token:
            logger.error("uazapi_create_no_token", extra={"response": str(created)[:500]})
            raise UnprocessableEntityError(
                f"UAZAPI não retornou um token de instância. Resposta: {str(created)[:200]}"
            )

        wa_settings = {
            **wa_settings,
            "instance": instance_id,
            "token": instance_token,
            "status": "connecting",
            "webhook_secret": webhook_secret,
        }
        _persist_wa_settings(tenant, wa_settings)
        try:
            await db.commit()
        except Exception as exc:
            logger.error("db_commit_after_create_failed", extra={"error": str(exc)})
            await db.rollback()
            raise UnprocessableEntityError(
                "Erro ao salvar a instância no banco de dados. Tente novamente."
            )

    # ── Step 2 ── configure webhook + start connection. Safe to retry because it
    # reuses the already-persisted token; a transient failure here never leaks a
    # new instance on UAZAPI.
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
        body = exc.response.text[:300]
        logger.error(
            "uazapi_connect_http_error",
            extra={"status": exc.response.status_code, "body": body},
        )
        if exc.response.status_code == 404:
            # Instance was deleted on the UAZAPI server — clear token so next click
            # creates a fresh one.
            wa_settings = {**wa_settings, "token": None, "instance": None, "status": "disconnected"}
            _persist_wa_settings(tenant, wa_settings)
            await db.commit()
            raise UnprocessableEntityError(
                "Instância WhatsApp não encontrada no servidor. "
                "Clique em Conectar novamente para criar uma nova."
            )
        raise UnprocessableEntityError(
            f"UAZAPI retornou erro {exc.response.status_code} ao gerar o QR. Tente novamente."
        )
    except Exception as exc:
        logger.error("uazapi_connect_unexpected_error", extra={"error": str(exc)})
        raise UnprocessableEntityError(f"Erro inesperado ao conectar: {exc}")

    inst = conn.get("instance") or {}
    if not instance_id:
        instance_id = inst.get("id")
    qr_code = inst.get("qrcode") or ""
    pair_code = inst.get("paircode") or ""
    status = "connected" if (conn.get("connected") or conn.get("loggedIn")) else "connecting"

    wa_settings = {
        **wa_settings,
        "instance": instance_id,
        "token": instance_token,
        "status": status,
        "webhook_secret": webhook_secret,
    }
    _persist_wa_settings(tenant, wa_settings)
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
    inst = payload.get("instance") or {}
    # The instance's own status string ("connecting" while waiting for the QR
    # scan) lets us distinguish "waiting to be scanned" from truly disconnected,
    # so the frontend keeps showing the QR instead of hiding it on the first poll.
    raw_state = str(inst.get("status") or st.get("status") or "").lower()
    logger.info(
        "uazapi_status_payload",
        extra={"connected": st.get("connected"), "loggedIn": st.get("loggedIn"),
               "raw_state": raw_state or "(empty)", "status_keys": list(st.keys()),
               "instance_keys": list(inst.keys())},
    )

    if st.get("connected") or st.get("loggedIn"):
        status = "connected"
    elif raw_state == "connecting":
        status = "connecting"
    else:
        status = "disconnected"

    if wa_settings.get("status") != status:
        _persist_wa_settings(tenant, {**wa_settings, "status": status})
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

    _persist_wa_settings(tenant, {"instance": None, "token": None, "status": "disconnected"})
    await db.commit()
