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


class MessageCreate(BaseModel):
    content: str
    direction: MessageDirection = MessageDirection.OUTBOUND
    channel: MessageChannel = MessageChannel.WHATSAPP
