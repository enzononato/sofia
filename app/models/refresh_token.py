"""
Persistent refresh token store.

We store only a SHA-256 hash of the token so a database leak does not yield
usable credentials. The plaintext token is returned to the client exactly once
on issuance.

Rotation contract:
  - Each successful POST /auth/refresh consumes the existing token (sets
    `revoked_at`) and issues a brand-new one. Reusing a previously-rotated
    token is treated as compromise: the entire family (all descendants of the
    same `family_id`) is revoked.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.tenant import Tenant


class RefreshToken(TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # The SHA-256 hex digest of the plaintext token — never store the token itself
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Tokens issued from the same login share a family_id. Reusing a rotated
    # token is detected by hash + revoked_at, and we then revoke the whole family.
    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped["User"] = relationship()
    tenant: Mapped["Tenant"] = relationship()

    __table_args__ = (
        Index("ix_refresh_tokens_user_revoked", "user_id", "revoked_at"),
    )

    def __repr__(self) -> str:
        return f"<RefreshToken user={self.user_id} family={self.family_id} revoked={self.revoked_at is not None}>"
