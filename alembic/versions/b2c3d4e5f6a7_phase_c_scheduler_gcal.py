"""phase C: appointment reminders + google calendar credentials

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-18 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('appointments', sa.Column('reminders', JSONB(), nullable=True))
    op.add_column('appointments', sa.Column('google_event_id', sa.String(length=255), nullable=True))

    op.create_table(
        'google_calendar_credentials',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('encrypted_refresh_token', sa.Text(), nullable=False),
        sa.Column('calendar_id', sa.String(length=255), nullable=False, server_default='primary'),
        sa.Column('scope', sa.Text(), nullable=True),
        sa.Column('connected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_gcal_creds_tenant_id', 'google_calendar_credentials', ['tenant_id'])
    op.create_index('ix_gcal_creds_user_id', 'google_calendar_credentials', ['user_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_gcal_creds_user_id', table_name='google_calendar_credentials')
    op.drop_index('ix_gcal_creds_tenant_id', table_name='google_calendar_credentials')
    op.drop_table('google_calendar_credentials')
    op.drop_column('appointments', 'google_event_id')
    op.drop_column('appointments', 'reminders')
