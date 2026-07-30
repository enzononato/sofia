"""move staff media data URI out of messages.content into media_url

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-07-28 10:00:00.000000

Data-only backfill (no schema change).

`POST /contacts/{id}/messages/media` used to store the whole base64 data URI in
`messages.content` for audio, and left `media_type` NULL. That broke
`app/services/ai.py::_history_text_for`, which keys off `media_type`: with it
NULL it fell through to `return msg.content` and fed the ENTIRE base64 blob to
Gemini as plain text on every subsequent turn for that contact — inflating cost
and eventually blowing the context limit, which made Sofia stop replying to that
patient with no visible error. The same blob was also served as the Inbox list
preview (`MessagePreview.content`).

The route now writes media the same way the inbound webhook does (data URI in
`media_url`, metadata in `media_type`/`media_mime_type`/`media_size_bytes`,
caption-or-empty in `content`). This migration repairs the rows already written
the old way.

Scope: only OUTBOUND rows whose `content` starts with 'data:' and that have no
`media_type` yet — inbound media has always been stored correctly, and rows
already carrying a `media_type` are left untouched. `media_size_bytes` is left
NULL for backfilled rows (computing the decoded length would mean base64-decoding
every blob in SQL for a field nothing reads for playback).
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # split_part(content, ':', 2) -> "audio/webm;base64,AAAA..."
    # split_part(..., ';', 1)     -> "audio/webm"   (the MIME type)
    # split_part(..., '/', 1)     -> "audio"        (our media_type bucket)
    op.execute(
        """
        UPDATE messages
        SET
            media_url = content,
            media_mime_type = split_part(split_part(content, ':', 2), ';', 1),
            media_type = CASE
                WHEN content LIKE 'data:audio/%' THEN 'audio'
                WHEN content LIKE 'data:image/%' THEN 'image'
                WHEN content LIKE 'data:video/%' THEN 'video'
                ELSE 'document'
            END,
            content = ''
        WHERE content LIKE 'data:%'
          AND media_type IS NULL
          AND lower(direction) = 'outbound'
        """
    )


def downgrade() -> None:
    # Put the data URI back in `content` for exactly the rows we moved. Rows that
    # already had media_url before this migration are excluded by the
    # `content = ''` guard (their content was never the blob).
    op.execute(
        """
        UPDATE messages
        SET
            content = media_url,
            media_url = NULL,
            media_mime_type = NULL,
            media_type = NULL
        WHERE content = ''
          AND media_url LIKE 'data:%'
          AND lower(direction) = 'outbound'
        """
    )
