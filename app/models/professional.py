"""
Professional ↔ Service mapping + per-professional working hours (Fase 2).

A "professional" is a `User` with role=professional (or an owner/admin who also
attends patients). These tables let each clinic configure, entirely from the
system, *who does what* and *when each one works* — the data Sofia needs to
schedule per professional (Fase 3).
"""

import uuid
from datetime import time
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Table, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TenantScopedMixin

if TYPE_CHECKING:
    from app.models.user import User


# Many-to-many: which services each professional offers.
# tenant_id is intentionally omitted — both sides are tenant-scoped and the API
# validates that professional + service belong to the same tenant before linking.
professional_services = Table(
    "professional_services",
    Base.metadata,
    Column(
        "professional_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "service_id",
        UUID(as_uuid=True),
        ForeignKey("services.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class ProfessionalWorkHours(TenantScopedMixin, Base):
    """
    A single work block for a professional on a given weekday. Multiple blocks
    per weekday are allowed (split shifts) — the gap between blocks is the break
    (e.g. lunch). When a professional has no rows, availability falls back to the
    clinic `settings.schedule`.
    """

    __tablename__ = "professional_work_hours"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    professional_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # ISO: 1=Mon … 7=Sun
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    professional: Mapped["User"] = relationship(back_populates="work_hours")

    __table_args__ = (
        CheckConstraint("weekday >= 1 AND weekday <= 7", name="ck_work_hours_weekday"),
        CheckConstraint("end_time > start_time", name="ck_work_hours_time_order"),
    )

    def __repr__(self) -> str:
        return (
            f"<WorkHours professional={self.professional_id} weekday={self.weekday} "
            f"{self.start_time}-{self.end_time}>"
        )
