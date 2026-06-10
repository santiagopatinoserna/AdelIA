"""briefings.id server default — sync DB with ORM.

Revision ID: 0007_briefings_id_default
Revises: 0006_profiles
Create Date: 2026-06-10 00:00:00.000000

The Briefing ORM declares `server_default=gen_random_uuid()` on `id`, but
migration 0001 created the column without a default. Every INSERT that
relies on the server generating the id (briefing_repo.create_briefing)
fails with NotNullViolation. briefing_citations was created correctly in
0003 and is not touched.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0007_briefings_id_default"
down_revision: Union[str, None] = "0006_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE briefings ALTER COLUMN id SET DEFAULT gen_random_uuid()")


def downgrade() -> None:
    op.execute("ALTER TABLE briefings ALTER COLUMN id DROP DEFAULT")
