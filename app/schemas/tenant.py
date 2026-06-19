import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.tenant import TenantPlan

# Secrets that must NEVER be serialized back to any client. The clinic owner sets
# them, but once stored they stay server-side. `gemini_api_key` is deprecated
# (the server's global key is always used now) but may exist in old rows.
_SENSITIVE_AI_KEYS = {"gemini_api_key"}
_SENSITIVE_WHATSAPP_KEYS = {"webhook_secret", "api_key", "api_url", "apikey"}


def _scrub_dict(data: Any, drop_keys: set[str]) -> Any:
    if not isinstance(data, dict):
        return data
    return {k: v for k, v in data.items() if k not in drop_keys}


class TenantBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    email: EmailStr
    phone: str | None = None
    address: str | None = None
    plan: TenantPlan = TenantPlan.FREE
    ai_config: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None


class TenantCreate(TenantBase):
    pass


class TenantUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    email: EmailStr | None = None
    phone: str | None = None
    address: str | None = None
    plan: TenantPlan | None = None
    is_active: bool | None = None
    ai_config: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None


class TenantRead(TenantBase):
    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("ai_config", mode="after")
    @classmethod
    def _scrub_ai_config(cls, value: Any) -> Any:
        """Strip the (deprecated) per-tenant Gemini key before it reaches a client."""
        return _scrub_dict(value, _SENSITIVE_AI_KEYS)

    @field_validator("settings", mode="after")
    @classmethod
    def _scrub_settings(cls, value: Any) -> Any:
        """Strip WhatsApp secrets (webhook_secret, provider keys) from settings."""
        if not isinstance(value, dict):
            return value
        out = dict(value)
        if isinstance(out.get("whatsapp"), dict):
            out["whatsapp"] = _scrub_dict(out["whatsapp"], _SENSITIVE_WHATSAPP_KEYS)
        return out
