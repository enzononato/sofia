"""appointment no-overlap-per-professional exclusion constraint

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-17 13:00:00.000000

Prevents two non-cancelled appointments of the SAME professional from
overlapping in time, enforced at the database level (race-proof). Only rows
with a professional_id and ends_at participate — capacity-mode appointments
(professional_id IS NULL) are unaffected.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # btree_gist lets us combine equality (=) on professional_id with the
    # range-overlap (&&) operator inside a single GiST exclusion constraint.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        """
        ALTER TABLE appointments
        ADD CONSTRAINT no_overlap_per_professional
        EXCLUDE USING gist (
            professional_id WITH =,
            tstzrange(scheduled_at, ends_at) WITH &&
        )
        WHERE (status <> 'cancelled' AND professional_id IS NOT NULL AND ends_at IS NOT NULL)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS no_overlap_per_professional")
    # btree_gist extension is left installed (harmless, may be used elsewhere).
