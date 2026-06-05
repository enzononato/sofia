import uuid
from datetime import date
from enum import Enum as PyEnum
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TenantScopedMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.models.appointment import Appointment


class ContactStatus(str, PyEnum):
    LEAD = "lead"
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"


class Contact(TenantScopedMixin, Base):
    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Medical / clinical notes stored in JSONB for flexibility across specialties
    medical_notes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[ContactStatus] = mapped_column(
        String(20), nullable=False, default=ContactStatus.LEAD
    )

    # WhatsApp synced data
    whatsapp_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profile_picture_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Handoff flag: if True, Sofia will ignore inbound messages from this contact
    ai_paused: Mapped[bool] = mapped_column(server_default="false")

    # AI conversation history reference (thread_id from OpenAI Assistants, etc.)
    ai_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    tenant: Mapped["Tenant"] = relationship(back_populates="contacts")
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="contact", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Contact name={self.full_name!r} tenant={self.tenant_id}>"
