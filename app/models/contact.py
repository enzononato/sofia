import uuid
from datetime import date, datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
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


class CrmStage(str, PyEnum):
    """CRM pipeline stage (Kanban column). Distinct from ContactStatus —
    this tracks the sales/relationship funnel that Sofia and the team manage.

    A contact stays in NEW_LEAD until Sofia has enough signal to qualify it as
    COLD_LEAD (low intent / just researching / hesitant) or HOT_LEAD (clear
    buying intent, close to booking). SCHEDULED/ATTENDED are factual (driven by
    appointments), POST_CARE/LOST are set by Sofia or the team."""
    NEW_LEAD = "new_lead"
    COLD_LEAD = "cold_lead"
    HOT_LEAD = "hot_lead"
    SCHEDULED = "scheduled"
    ATTENDED = "attended"
    POST_CARE = "post_care"
    LOST = "lost"


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

    # CRM pipeline (Kanban). crm_stage_source = "ai" | "manual": a card moved by
    # hand ("manual") is respected by the AI (it won't auto-regress it).
    crm_stage: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=CrmStage.NEW_LEAD.value, index=True
    )
    crm_stage_source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="ai")
    crm_stage_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Denormalized activity timestamps powering the follow-up jobs (Fase C).
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # WhatsApp synced data
    whatsapp_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profile_picture_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Handoff flag: if True, Sofia will ignore inbound messages from this contact
    ai_paused: Mapped[bool] = mapped_column(server_default="false")

    # When the "still waiting for a human" alert was last sent for the CURRENT
    # pause episode (see app/services/followups.py::run_paused_alert). Reset
    # semantics are handled by that job itself, by comparing this timestamp to
    # the contact's latest inbound message rather than clearing the column
    # elsewhere: if a new inbound message arrives after this timestamp (or the
    # contact gets un-paused and paused again later with fresh messages), the
    # job treats it as a brand-new episode and alerts again.
    #
    # PENDING MIGRATION: this column does not exist in the DB yet. Another
    # workstream owns Alembic revisions this week — a migration adding
    # `contacts.handoff_alerted_at TIMESTAMPTZ NULL` must be created before
    # this is deployed (see plan summary for details).
    handoff_alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Temporary auto-pause (item D4 of the robustness plan): set/renewed to
    # now + HUMAN_TAKEOVER_PAUSE_MINUTES whenever staff reply to this patient
    # directly from their own phone/WhatsApp Web (fromMe=true,
    # wasSentByApi=false — see
    # app/api/v1/routes/webhooks.py::_process_human_outbound_message). While
    # this is in the future, Sofia skips generating a reply for this contact,
    # exactly like `ai_paused` — but it EXPIRES ON ITS OWN (no manual
    # reactivation): once "now" passes this timestamp, Sofia resumes
    # automatically on the patient's next message. Distinct from `ai_paused`
    # (permanent, one-way, only staff can un-pause via the Inbox). To inspect
    # in the DB: `SELECT id, phone, human_takeover_until FROM contacts WHERE
    # human_takeover_until > now();` lists contacts currently in the window.
    human_takeover_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # AI conversation history reference (thread_id from OpenAI Assistants, etc.)
    ai_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    tenant: Mapped["Tenant"] = relationship(back_populates="contacts")
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="contact", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Contact name={self.full_name!r} tenant={self.tenant_id}>"
