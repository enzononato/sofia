"""add_multimodal_fields_to_messages

Revision ID: b3c4d5e6f7a8
Revises: a1187bfdff32
Create Date: 2026-05-06 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a1187bfdff32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('media_type', sa.String(length=20), nullable=True))
    op.add_column('messages', sa.Column('media_mime_type', sa.String(length=100), nullable=True))
    op.add_column('messages', sa.Column('media_size_bytes', sa.Integer(), nullable=True))
    op.add_column('messages', sa.Column('media_url', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'media_url')
    op.drop_column('messages', 'media_size_bytes')
    op.drop_column('messages', 'media_mime_type')
    op.drop_column('messages', 'media_type')
