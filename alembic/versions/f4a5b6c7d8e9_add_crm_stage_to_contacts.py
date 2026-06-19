"""add crm_stage + activity timestamps to contacts

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-06-18 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'contacts',
        sa.Column('crm_stage', sa.String(length=30), nullable=False, server_default='new_lead'),
    )
    op.add_column(
        'contacts',
        sa.Column('crm_stage_source', sa.String(length=10), nullable=False, server_default='ai'),
    )
    op.add_column('contacts', sa.Column('crm_stage_updated_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('contacts', sa.Column('last_inbound_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('contacts', sa.Column('last_followup_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_contacts_crm_stage', 'contacts', ['crm_stage'])


def downgrade() -> None:
    op.drop_index('ix_contacts_crm_stage', table_name='contacts')
    op.drop_column('contacts', 'last_followup_at')
    op.drop_column('contacts', 'last_inbound_at')
    op.drop_column('contacts', 'crm_stage_updated_at')
    op.drop_column('contacts', 'crm_stage_source')
    op.drop_column('contacts', 'crm_stage')
