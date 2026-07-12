"""add anonymization fields to contacts

Revision ID: b7c8d9e0f1a2
Revises: 8f929e98320e
Create Date: 2026-07-11 15:00:00.000000

NOTE: this revision was originally authored as 'd4e5f6a7b8c9' with
down_revision 'c3d4e5f6a7b8' in an isolated worktree that branched before the
rest of the Wave 1/Wave 2 migrations existed. Renamed to 'b7c8d9e0f1a2' and
re-chained onto '8f929e98320e' (the actual head at merge time) during
integration — the collision was with an unrelated Wave 1 migration
(messages.whatsapp_message_id uniqueness) that coincidentally used the same
revision id text.

LGPD manual "right to be forgotten" support. The clinic can now anonymize a
contact on the patient's request (see app/services/privacy.py). This adds:

  - contacts.anonymized_at: timestamp marking the contact as anonymized
    (NULL = never anonymized). Lets the (future) UI show the state.
  - contacts.anonymized_by_user_id: which staff user triggered the
    anonymization, for a minimal audit trail. SET NULL on user deletion so
    we never block user cleanup on this FK.

No automated retention/deletion job is introduced by this migration — the
capability is manual-only, triggered by an authenticated clinic user.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, None] = '8f929e98320e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('contacts', sa.Column('anonymized_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        'contacts',
        sa.Column('anonymized_by_user_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_contacts_anonymized_by_user_id_users',
        'contacts',
        'users',
        ['anonymized_by_user_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_contacts_anonymized_by_user_id_users', 'contacts', type_='foreignkey')
    op.drop_column('contacts', 'anonymized_by_user_id')
    op.drop_column('contacts', 'anonymized_at')
