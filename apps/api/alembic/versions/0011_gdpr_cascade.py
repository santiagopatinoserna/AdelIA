"""GDPR right-to-erasure: user-deletion cascades.

Revision ID: 0011_gdpr_cascade
Revises: 0010_count_indexes
Create Date: 2026-06-10 00:00:00.000000

DELETE FROM users failed on documents (FK without CASCADE), and
briefings.user_id / share_links.user_id had NO foreign key at all —
deleting a user would orphan their briefings and share links (live
public links to medical data of an erased account!). Article 17
requires the whole graph to go.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0011_gdpr_cascade"
down_revision: Union[str, None] = "0010_count_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("documents_user_id_fkey", "documents", type_="foreignkey")
    op.create_foreign_key(
        "documents_user_id_fkey", "documents", "users",
        ["user_id"], ["id"], ondelete="CASCADE",
    )
    # Orphan guard before adding the new FKs (idempotent on clean DBs).
    op.execute("DELETE FROM share_links WHERE user_id NOT IN (SELECT id FROM users)")
    op.execute("DELETE FROM briefings WHERE user_id NOT IN (SELECT id FROM users)")
    op.create_foreign_key(
        "briefings_user_id_fkey", "briefings", "users",
        ["user_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "share_links_user_id_fkey", "share_links", "users",
        ["user_id"], ["id"], ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("share_links_user_id_fkey", "share_links", type_="foreignkey")
    op.drop_constraint("briefings_user_id_fkey", "briefings", type_="foreignkey")
    op.drop_constraint("documents_user_id_fkey", "documents", type_="foreignkey")
    op.create_foreign_key(
        "documents_user_id_fkey", "documents", "users", ["user_id"], ["id"],
    )
