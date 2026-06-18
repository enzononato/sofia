"""professional_services and work_hours

Revision ID: c1d2e3f4a5b6
Revises: b3c4d5e6f7a8
Create Date: 2026-06-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # M:N professional (user) <-> service
    op.create_table(
        'professional_services',
        sa.Column('professional_id', sa.UUID(), nullable=False),
        sa.Column('service_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['professional_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['service_id'], ['services.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('professional_id', 'service_id'),
    )
    op.create_index(
        op.f('ix_professional_services_service_id'),
        'professional_services', ['service_id'], unique=False,
    )

    # Per-professional work blocks (split shifts allowed)
    op.create_table(
        'professional_work_hours',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('professional_id', sa.UUID(), nullable=False),
        sa.Column('weekday', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('weekday >= 1 AND weekday <= 7', name='ck_work_hours_weekday'),
        sa.CheckConstraint('end_time > start_time', name='ck_work_hours_time_order'),
        sa.ForeignKeyConstraint(['professional_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_professional_work_hours_tenant_id'),
        'professional_work_hours', ['tenant_id'], unique=False,
    )
    op.create_index(
        op.f('ix_professional_work_hours_professional_id'),
        'professional_work_hours', ['professional_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_professional_work_hours_professional_id'), table_name='professional_work_hours')
    op.drop_index(op.f('ix_professional_work_hours_tenant_id'), table_name='professional_work_hours')
    op.drop_table('professional_work_hours')
    op.drop_index(op.f('ix_professional_services_service_id'), table_name='professional_services')
    op.drop_table('professional_services')
