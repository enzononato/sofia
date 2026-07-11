"""messages: real uniqueness for (tenant_id, whatsapp_message_id)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-11 10:00:00.000000

`messages.whatsapp_message_id` was only a plain (non-unique) index. The
webhook protected against duplicate delivery with a SELECT-before-INSERT
check, which does NOT protect against two concurrent deliveries of the same
UAZAPI webhook — both can pass the SELECT before either commits, producing two
rows for the same WhatsApp message.

This migration adds a real database-level guarantee: a UNIQUE index on
(tenant_id, whatsapp_message_id), partial (WHERE whatsapp_message_id IS NOT
NULL) so rows without a provider id (e.g. any legacy/synthetic messages) are
unaffected. Before creating the index, any pre-existing duplicate rows are
deduped — keeping the oldest row per (tenant_id, whatsapp_message_id) and
deleting the rest — since the index creation would otherwise fail on a
database that already has duplicates.

downgrade() only drops the index; the dedup delete is NOT reversible (there is
no way to resurrect deleted duplicate rows), which is expected and accepted
for this kind of cleanup migration.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Dedupe: keep the oldest row (by created_at, then id as a tiebreaker)
    #    per (tenant_id, whatsapp_message_id); delete the rest. Only rows with
    #    a non-null whatsapp_message_id participate — nothing else is touched.
    op.execute(
        """
        DELETE FROM messages m
        USING (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY tenant_id, whatsapp_message_id
                       ORDER BY created_at ASC, id ASC
                   ) AS rn
            FROM messages
            WHERE whatsapp_message_id IS NOT NULL
        ) dup
        WHERE m.id = dup.id AND dup.rn > 1
        """
    )

    # 2) Enforce uniqueness at the database level so two concurrent webhook
    #    deliveries for the same message can no longer both succeed.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_messages_tenant_whatsapp_message_id_unique
        ON messages (tenant_id, whatsapp_message_id)
        WHERE whatsapp_message_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_messages_tenant_whatsapp_message_id_unique")
    # The dedup DELETE above is intentionally not reversed — deleted duplicate
    # rows cannot be recovered, and re-introducing them would defeat the point
    # of this migration.
