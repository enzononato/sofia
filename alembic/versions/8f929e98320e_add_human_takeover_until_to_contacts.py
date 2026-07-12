"""add human_takeover_until to contacts

Revision ID: 8f929e98320e
Revises: 89644ef01ac7
Create Date: 2026-07-11 23:49:56.625211

Backs the temporary human-takeover auto-pause (item D4 of the robustness
plan): a nullable timestamp set/renewed to now + HUMAN_TAKEOVER_PAUSE_MINUTES
whenever staff reply to a patient directly from their own phone/WhatsApp Web
(see app/api/v1/routes/webhooks.py::_process_human_outbound_message). While
in the future, Sofia skips generating a reply for that contact — but unlike
`ai_paused` (permanent, staff-only reactivation), this expires on its own.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8f929e98320e'
down_revision: Union[str, None] = '89644ef01ac7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column("human_takeover_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contacts", "human_takeover_until")
