"""reclassify crm stages: in_conversation -> cold_lead (hot/cold leads)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-06 13:00:00.000000

The CRM funnel replaced the vague 'in_conversation' stage with two intent-based
stages, 'cold_lead' and 'hot_lead'. crm_stage is a plain VARCHAR (no native PG
enum), so this is a pure data migration. Existing 'in_conversation' contacts had
been engaged but not qualified — map them to 'cold_lead' (already contacted, not
yet hot); Sofia promotes them to 'hot_lead' on the next interaction if intent
shows. 'new_lead' now means "not yet qualified by Sofia".
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE contacts SET crm_stage = 'cold_lead' WHERE crm_stage = 'in_conversation'"
    )


def downgrade() -> None:
    # Collapse both intent stages back to the old single 'in_conversation'.
    op.execute(
        "UPDATE contacts SET crm_stage = 'in_conversation' "
        "WHERE crm_stage IN ('cold_lead', 'hot_lead')"
    )
