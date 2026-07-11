"""add handoff_alerted_at to contacts

Revision ID: 89644ef01ac7
Revises: d4e5f6a7b8c9
Create Date: 2026-07-11 12:05:21.886505

Backs the "paused-and-forgotten" alert (app/services/followups.py::run_paused_alert):
a nullable timestamp marking when the clinic was last emailed that a contact has
been paused (ai_paused=True) with an unanswered inbound message for too long.
Deduped against the contact's latest inbound message timestamp at read time (see
run_paused_alert), so no separate "reset" write is needed on un-pause/re-pause.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '89644ef01ac7'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column("handoff_alerted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contacts", "handoff_alerted_at")
