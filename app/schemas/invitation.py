import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole


class InvitationCreate(BaseModel):
    email: EmailStr
    role: UserRole = UserRole.PROFESSIONAL


class InvitationRead(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: UserRole
    expires_at: datetime
    accepted_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class InvitationCreateResponse(BaseModel):
    invitation: InvitationRead
    invite_link: str
    email_sent: bool


class AcceptInviteRequest(BaseModel):
    token: str = Field(..., min_length=16)
    full_name: str = Field(..., min_length=2, max_length=255)
    password: str = Field(..., min_length=8)
