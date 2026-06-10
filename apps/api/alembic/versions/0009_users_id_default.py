"""users.id server default — raw-SQL inserters (Auth.js adapter) need it.

Revision ID: 0009_users_id_default
Revises: 0008_verification_tokens
Create Date: 2026-06-10 00:00:00.000000

The SQLAlchemy ORM generates ids client-side (default=uuid.uuid4), so the
API never noticed. But the web Auth.js adapter inserts users with raw SQL
and no id — magic-link signups for NEW users violated NOT NULL. Same class
of bug as 0007 (briefings.id).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0009_users_id_default"
down_revision: Union[str, None] = "0008_verification_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN id SET DEFAULT gen_random_uuid()")


def downgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN id DROP DEFAULT")
