import uuid
from datetime import datetime, time

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models.user import UserRole


class UserBase(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    role: UserRole = UserRole.RECEPTIONIST
    is_active: bool = True


class UserCreate(UserBase):
    # Optional: when omitted (e.g. a professional who is only a bookable resource
    # and won't log in), the server generates a strong random password.
    password: str | None = Field(None, min_length=8)


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=255)
    email: EmailStr | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=8)


class UserRead(UserBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Professional configuration (Fase 2) ──────────────────────────────────────

class WorkHourBlock(BaseModel):
    """A single work block on a weekday (ISO: 1=Mon … 7=Sun)."""
    weekday: int = Field(..., ge=1, le=7)
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def _check_order(self) -> "WorkHourBlock":
        if self.end_time <= self.start_time:
            raise ValueError("end_time deve ser maior que start_time")
        return self


class WorkHoursUpdate(BaseModel):
    """Full replacement of a professional's work blocks."""
    blocks: list[WorkHourBlock] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_no_overlap(self) -> "WorkHoursUpdate":
        by_day: dict[int, list[tuple[time, time]]] = {}
        for b in self.blocks:
            by_day.setdefault(b.weekday, []).append((b.start_time, b.end_time))
        for day, ranges in by_day.items():
            ranges.sort()
            for prev, curr in zip(ranges, ranges[1:]):
                if curr[0] < prev[1]:
                    raise ValueError(f"Blocos de horário sobrepostos no dia {day}.")
        return self


class ServiceAssignmentUpdate(BaseModel):
    """Full replacement of the services a professional offers."""
    service_ids: list[uuid.UUID] = Field(default_factory=list)


class UserDetailRead(UserRead):
    """UserRead + professional config (services offered + work hours)."""
    service_ids: list[uuid.UUID] = Field(default_factory=list)
    work_hours: list[WorkHourBlock] = Field(default_factory=list)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
