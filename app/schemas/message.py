import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.message import MessageChannel, MessageDirection


class MessageRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    contact_id: uuid.UUID
    direction: MessageDirection
    channel: MessageChannel
    content: str
    whatsapp_message_id: str | None
    ai_model_used: str | None
    created_at: datetime
    media_type: str | None = None
    media_mime_type: str | None = None
    media_size_bytes: int | None = None
    media_url: str | None = None

    model_config = {"from_attributes": True}


class MessagePreview(BaseModel):
    """Lightweight last-message preview for the contacts LIST (Inbox sidebar).

    Deliberately omits `media_url` — that field can be a multi-MB base64 data
    URI, and the listing only ever needs a label (e.g. "🎤 Áudio") built from
    `media_type`, never the actual bytes. The full media payload is still
    served in full by `GET /contacts/{id}/messages` (via `MessageRead`) for the
    currently-open conversation, which is the only place it's actually played
    back / rendered.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    contact_id: uuid.UUID
    direction: MessageDirection
    channel: MessageChannel
    content: str
    ai_model_used: str | None
    created_at: datetime
    media_type: str | None = None

    model_config = {"from_attributes": True}


class MessageCreate(BaseModel):
    content: str
    direction: MessageDirection = MessageDirection.OUTBOUND
    channel: MessageChannel = MessageChannel.WHATSAPP


class SuggestedReply(BaseModel):
    """Draft reply produced by the Inbox "Sugerir resposta" (staff copilot).
    Not persisted or sent — the human edits it and sends via the normal
    POST /contacts/{id}/messages path."""

    suggestion: str
