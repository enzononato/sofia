"""
Tenant routes — settings and profile of the current clinic.

GET   /tenants/me  — return the authenticated clinic's data
PATCH /tenants/me  — update name, contact info, ai_config, settings
"""

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentTenantId, CurrentUser, DBSession
from app.core.errors import ForbiddenError, NotFoundError
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.schemas.tenant import _SENSITIVE_WHATSAPP_KEYS, TenantRead, TenantUpdate

router = APIRouter(prefix="/tenants", tags=["Tenants"])

_WRITE_ROLES = (UserRole.OWNER, UserRole.ADMIN)

# Keys inside settings.whatsapp that only the WhatsApp connect flow
# (app/api/v1/routes/whatsapp.py) may ever write. `_SENSITIVE_WHATSAPP_KEYS`
# (imported from schemas/tenant.py, the single source of truth for what's a
# *secret*) is reused here as-is so the read-side scrub and the write-side
# block can never drift apart on the secret set. `status`/`instance` are not
# secrets (TenantRead still returns them — the frontend doesn't currently rely
# on that, but nothing needs it hidden) yet are still exclusively server-set,
# so they're blocked on write here without being added to the secret set.
_SERVER_MANAGED_WHATSAPP_KEYS = _SENSITIVE_WHATSAPP_KEYS | {"status", "instance"}


@router.get("/me", response_model=TenantRead)
async def get_my_tenant(
    db: DBSession,
    tenant_id: CurrentTenantId,
    _: CurrentUser,
):
    """Return the current clinic's profile."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise NotFoundError("Tenant not found.")
    return tenant


@router.patch("/me", response_model=TenantRead)
async def update_my_tenant(
    payload: TenantUpdate,
    db: DBSession,
    tenant_id: CurrentTenantId,
    current_user: CurrentUser,
):
    if current_user.role not in _WRITE_ROLES:
        raise ForbiddenError("Only owners and admins can update clinic settings.")

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise NotFoundError("Tenant not found.")

    # `ai_config` and `settings` are JSONB blobs. A PATCH must MERGE so sending one
    # section never wipes keys it doesn't manage — e.g. saving the AI tab must not
    # erase `scheduling_mode`, nor the WhatsApp/clinic settings. We merge two levels
    # deep so a partial update of `settings.whatsapp` doesn't clobber `webhook_secret`.
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field in ("ai_config", "settings") and isinstance(value, dict):
            if field == "settings" and isinstance(value.get("whatsapp"), dict):
                # `whatsapp.token`/`webhook_secret`/`status`/`instance` (and the
                # legacy api_key/api_url/apikey) are server-managed — only the
                # WhatsApp connect flow (app/api/v1/routes/whatsapp.py) may set
                # them. Drop any client-supplied values before merging so a
                # PATCH /tenants/me can never overwrite them.
                value = {
                    **value,
                    "whatsapp": {
                        k: v
                        for k, v in value["whatsapp"].items()
                        if k not in _SERVER_MANAGED_WHATSAPP_KEYS
                    },
                }
            current = getattr(tenant, field) or {}
            merged = _deep_merge(current, value)
            if field == "ai_config":
                # The per-tenant Gemini key is never stored: the server's global
                # key is always used. Drop it on the way in (defence in depth).
                merged.pop("gemini_api_key", None)
            setattr(tenant, field, merged)
        else:
            setattr(tenant, field, value)

    await db.commit()
    await db.refresh(tenant)
    return tenant


def _deep_merge(base: dict, incoming: dict) -> dict:
    """Merge `incoming` into a copy of `base`, recursing one level into nested dicts
    so partial updates (e.g. settings.whatsapp) preserve sibling keys/secrets."""
    out = dict(base)
    for key, val in incoming.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = {**out[key], **val}
        else:
            out[key] = val
    return out
