import uuid
from enum import Enum as PyEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TenantScopedMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class UserRole(str, PyEnum):
    OWNER = "owner"
    ADMIN = "admin"
    RECEPTIONIST = "receptionist"
    PROFESSIONAL = "professional"
    VIEWER = "viewer"


class User(TenantScopedMixin, Base):
    __tablename__ = "users"

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
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(20), nullable=False, default=UserRole.RECEPTIONIST)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    tenant: Mapped["Tenant"] = relationship(back_populates="users")

    def __repr__(self) -> str:
        return f"<User email={self.email!r} role={self.role} tenant={self.tenant_id}>"
