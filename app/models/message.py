import uuid
from enum import Enum as PyEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TenantScopedMixin

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.tenant import Tenant


class MessageDirection(str, PyEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageChannel(str, PyEnum):
    WHATSAPP = "whatsapp"


class Message(TenantScopedMixin, Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    direction: Mapped[str] = mapped_column(String(10), nullable=False)   # inbound | outbound
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default=MessageChannel.WHATSAPP)
    # Text payload. For media messages, this holds the optional caption (empty string if none).
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # External ID from the WhatsApp provider (UAZAPI messageid)
    whatsapp_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # Which OpenAI model produced this reply (null for inbound messages)
    ai_model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Multimodal media. media_url holds the data URI for v1 ("data:image/jpeg;base64,...");
    # later it can become a real object-storage URL without changing the frontend contract.
    # content remains free for the optional caption when media has one.
    media_type: Mapped[str | None] = mapped_column(String(20), nullable=True)            # audio | image | video | document
    media_mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    media_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    media_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    tenant: Mapped["Tenant"] = relationship()
    contact: Mapped["Contact"] = relationship()

    def __repr__(self) -> str:
        return f"<Message direction={self.direction} channel={self.channel} contact={self.contact_id}>"
