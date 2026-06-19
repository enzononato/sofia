import uuid
from enum import Enum as PyEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.contact import Contact
    from app.models.appointment import Appointment
    from app.models.service import Service


class TenantPlan(str, PyEnum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class Tenant(TimestampMixin, Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    plan: Mapped[TenantPlan] = mapped_column(
        String(20), nullable=False, default=TenantPlan.FREE
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Contact / billing info
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)

    # AI / prompt configuration stored as JSONB for flexibility.
    # Example shape:
    # {
    #   "model": "gemini-2.5-flash",
    #   "system_prompt": "...",                    # BASE prompt (identity + invariant rules)
    #   "temperature": 0.7,
    #   "max_output_tokens": 1024,
    #   # NOTE: gemini_api_key is deprecated — the server's global key is always used,
    #   # and it is stripped from every API response (see app/schemas/tenant.py).
    #   "multimodal_enabled": false,               # toggles audio/image/video/document handling
    #   # Per-stage overlays — see app/services/ai_stages.py for default copy.
    #   "prompt_first_contact": "...",
    #   "prompt_imminent_appointment": "...",
    #   "prompt_post_appointment": "...",
    #   "prompt_active_patient": "...",
    #   "prompt_returning_lead": "...",
    #   "prompt_reactivation": "..."
    # }
    ai_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Operational settings stored as JSONB. Shape:
    # {
    #   "whatsapp": { "instance": "...", "status": "...", "webhook_secret": "..." },
    #   "schedule": { "timezone": "...", "working_days": [...], "open_time": "...",
    #                 "close_time": "...", "lunch_start": "...", "lunch_end": "...",
    #                 "slot_granularity_minutes": 30 },
    #   "clinic": {                                  # surfaced via get_clinic_info tool
    #     "address": "...",
    #     "phone": "...",
    #     "email": "...",
    #     "instagram": "@...",
    #     "payment_methods": ["pix", "cartão", "dinheiro"],
    #     "additional_info": "Estacionamento conveniado..."
    #   }
    # }
    settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    users: Mapped[list["User"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    contacts: Mapped[list["Contact"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    services: Mapped[list["Service"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Tenant slug={self.slug!r} plan={self.plan}>"
