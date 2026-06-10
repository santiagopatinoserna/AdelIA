"""document_id indexes for entities/chunks — list-view count aggregation.

Revision ID: 0010_count_indexes
Revises: 0009_users_id_default
Create Date: 2026-06-10 00:00:00.000000

GET /documents aggregates entity/chunk counts per document; without these
the planner seq-scans both tables (O(total rows across ALL users) per
dashboard load). Partial index on entities matches the deleted_at filter.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0010_count_indexes"
down_revision: Union[str, None] = "0009_users_id_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_entities_document_id",
        "entities",
        ["document_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_index("ix_entities_document_id", table_name="entities")
